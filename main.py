#!/usr/bin/env python3
"""Render entrypoint for OTP Bot.

This module exposes the FastAPI ASGI app for Render's ASGI start behavior,
while also starting the Flask-based Telegram bot and background services
in a separate thread.

Render will start this app using the configured start command.
The FastAPI app is automatically run via uvicorn as the PORT-bound entrypoint.
"""
import logging
import os
import sys
import threading
import time
from pathlib import Path

from bot import (
    app as flask_app,
    bot,
    start_background_threads,
    get_runtime_mode,
    start_bot_polling,
    set_telegram_webhook,
    mark_webhook_mode,
    force_delete_telegram_webhook,
    USE_WEBHOOK,
    FLASK_PORT,
)
from live_listen.server import app as fastapi_app
from starlette.types import ASGIApp, Scope, Receive, Send

logger = logging.getLogger("HOTTBOIIHITZZ")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

logger.warning("[MAIN_STARTUP] Imported FastAPI app; router has %s routes", len(fastapi_app.router.routes))
print(f"[MAIN_ROUTE_TABLE] Imported FastAPI app; router has {len(fastapi_app.router.routes)} routes")
for idx, route in enumerate(fastapi_app.router.routes):
    route_path = getattr(route, "path", None) or getattr(route, "prefix", None)
    logger.warning("[MAIN_ROUTE_TABLE] %s: %s %s", idx, route.__class__.__name__, route_path)
    print(f"[MAIN_ROUTE_TABLE] {idx}: {route.__class__.__name__} {route_path}")


def ensure_conf_dir() -> None:
    try:
        Path("conf").mkdir(exist_ok=True)
    except Exception as exc:
        logger.warning(f"Could not create conf directory: {exc}")


def start_flask_server() -> None:
    try:
        # On Render, Flask is mounted into FastAPI by default, so we don't run it separately
        # Only run Flask standalone if FORCE_FLASK_STANDALONE is set
        if os.getenv("FORCE_FLASK_STANDALONE") == "true":
            flask_port = int(os.getenv("INTERNAL_FLASK_PORT", "5000"))
            logger.info(f"Starting Flask server on port {flask_port} (internal only)")
            flask_app.run(host="127.0.0.1", port=flask_port, debug=False, use_reloader=False, threaded=True)
        else:
            logger.info("Flask app mounted to FastAPI; skipping standalone Flask server")
    except Exception as exc:
        logger.exception(f"Flask startup failed: {exc}")


def start_otp_bot() -> None:
    ensure_conf_dir()
    start_background_threads()

    runtime_mode = get_runtime_mode(bot)
    logger.info(f"Starting application in {runtime_mode} mode.")
    
    # Log webhook configuration EARLY for diagnostics
    from bot import get_telegram_webhook_url
    logger.warning(f"[WEBHOOK_CONFIG] USE_WEBHOOK={USE_WEBHOOK}, WEBHOOK_URL={get_telegram_webhook_url()}")

    # Only start Flask thread if not on Railway (or if forced)
    if os.getenv("FORCE_FLASK_STANDALONE") == "true":
        flask_thread = threading.Thread(target=start_flask_server, daemon=True, name="FlaskThread")
        flask_thread.start()
        logger.info("Flask server thread started (internal only).")
    else:
        logger.info("Flask mounted to FastAPI; skipping standalone Flask thread.")

    # NOTE: Webhook setup is deferred to async startup event to ensure
    # FastAPI+Flask are fully initialized and can receive requests
    if runtime_mode != "full":
        logger.info("Skipping Telegram webhook and polling startup because the bot is not configured.")


# Start the bot immediately on module load
start_otp_bot()

# Export FastAPI app as `app` for uvicorn to bind to Railway's PORT
# This is the primary entrypoint that Railway exposes to the internet
# NOTE: Startup/shutdown events are registered in live_listen/server.py
app = fastapi_app

# =====================================================================
# ASGI CANARY: outermost ASGI layer that logs EVERY incoming connection
# before FastAPI routing or Flask mounts are reached.
# If Twilio's WebSocket connection reaches the server at all, this will
# log it — regardless of whether routing or TLS succeeds.
# =====================================================================
class _ASGICanary:
    def __init__(self, inner: ASGIApp):
        self.inner = inner

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        stype = scope.get("type", "?")
        path = scope.get("path", "/")
        headers_raw = scope.get("headers", [])
        upgrade = ""
        for k, v in headers_raw:
            if k == b"upgrade":
                upgrade = v.decode("utf-8", errors="replace")
                break
        print(
            f"[ASGI_CANARY] type={stype} path={path}"
            f"{' upgrade='+upgrade if upgrade else ''}",
            flush=True,
        )
        if stype == "websocket":
            print(
                f"[ASGI_CANARY_WS] *** WEBSOCKET CONNECTION ARRIVED *** path={path} upgrade={upgrade}",
                flush=True,
            )
            for k, v in headers_raw:
                kd = k.decode("utf-8", errors="replace")
                vd = v.decode("utf-8", errors="replace")
                print(f"[ASGI_CANARY_WS_HEADER]   {kd}: {vd}", flush=True)
        await self.inner(scope, receive, send)

app = _ASGICanary(app)
print("[ASGI_CANARY] ASGI canary wrapper installed at outermost layer", flush=True)

if __name__ == "__main__":
    # When run directly, start uvicorn server to bind FastAPI app and trigger startup events
    # Render will use the app start command configured in its service settings.
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting uvicorn server on port {port}")
    logger.warning(f"[MAIN_STARTUP] uvicorn will now call FastAPI startup event")
    uvicorn.run(app, host="0.0.0.0", port=port, workers=1)

