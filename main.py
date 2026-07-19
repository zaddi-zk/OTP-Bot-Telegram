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
        # On Railway, Flask runs on an internal port only (not exposed)
        # FastAPI (uvicorn) binds to the PORT env var and is exposed to the internet
        flask_port = int(os.getenv("INTERNAL_FLASK_PORT", "5000"))
        logger.info(f"Starting Flask server on port {flask_port} (internal only)")
        flask_app.run(host="127.0.0.1", port=flask_port, debug=False, use_reloader=False, threaded=True)
    except Exception as exc:
        logger.exception(f"Flask startup failed: {exc}")


def start_otp_bot() -> None:
    ensure_conf_dir()
    start_background_threads()

    runtime_mode = get_runtime_mode(bot)
    logger.info(f"Starting application in {runtime_mode} mode.")

    flask_thread = threading.Thread(target=start_flask_server, daemon=True, name="FlaskThread")
    flask_thread.start()
    logger.info("Flask server thread started (internal only).")

    if runtime_mode == "full":
        if USE_WEBHOOK:
            if set_telegram_webhook():
                logger.info("Webhook enabled; polling disabled.")
            else:
                logger.warning("Telegram webhook setup failed; falling back to polling.")
                mark_webhook_mode(False)
                start_bot_polling(allowed_updates=["message", "callback_query", "chat_member"])
        else:
            try:
                bot.remove_webhook()
                logger.info("Telegram webhook removed before polling startup.")
            except Exception as remove_exc:
                logger.debug(f"bot.remove_webhook() failed: {remove_exc}")
                if not force_delete_telegram_webhook():
                    logger.warning("Could not remove webhook via HTTP fallback; continuing to start polling.")
            mark_webhook_mode(False)
            start_bot_polling(allowed_updates=["message", "callback_query", "chat_member"])
    else:
        logger.info("Skipping Telegram webhook and polling startup because the bot is not configured.")


# Start the bot immediately on module load
start_otp_bot()

# Export FastAPI app as `app` for uvicorn to bind to Railway's PORT
# This is the primary entrypoint that Railway exposes to the internet
app = fastapi_app

# Register startup/shutdown logging
@app.on_event("startup")
async def startup():
    port = os.getenv("PORT", "5001")
    logger.info(f"FastAPI app starting on PORT={port}")

@app.on_event("shutdown")
async def shutdown():
    logger.info("FastAPI app shutting down")

if __name__ == "__main__":
    # Fallback for local testing: keep the process alive
    logger.info("Running in standalone mode (Railway will use uvicorn to bind FastAPI app)")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")

