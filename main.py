#!/usr/bin/env python3
"""Railway entrypoint for OTP Bot.

This module exposes the FastAPI ASGI app for Railway's default ASGI start
behavior, while also starting the Flask-based Telegram bot and background
services in a separate thread.

Railway will start with: `python main.py`
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

logger = logging.getLogger("HOTTBOIIHITZZ")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


def ensure_conf_dir() -> None:
    try:
        Path("conf").mkdir(exist_ok=True)
    except Exception as exc:
        logger.warning(f"Could not create conf directory: {exc}")


def start_flask_server() -> None:
    try:
        # On Railway, Flask is mounted into FastAPI, so we don't run it separately
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

if __name__ == "__main__":
    # Fallback for local testing: keep the process alive
    logger.info("Running in standalone mode (Railway will use uvicorn to bind FastAPI app)")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")

