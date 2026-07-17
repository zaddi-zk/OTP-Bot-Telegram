#!/usr/bin/env python3
"""Railway entrypoint for OTP Bot.

This module exposes the FastAPI ASGI app for Railway's default ASGI start
behavior, while also starting the Flask-based Telegram bot and background
services in a separate thread.
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
        logger.info(f"Starting Flask server on port {FLASK_PORT}")
        flask_app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False, threaded=True)
    except Exception as exc:
        logger.exception(f"Flask startup failed: {exc}")


def start_otp_bot() -> None:
    ensure_conf_dir()
    start_background_threads()

    runtime_mode = get_runtime_mode(bot)
    logger.info(f"Starting application in {runtime_mode} mode.")

    flask_thread = threading.Thread(target=start_flask_server, daemon=True, name="FlaskThread")
    flask_thread.start()
    logger.info("Flask server thread started.")

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


def _main() -> None:
    start_otp_bot()
    if __name__ == "__main__":
        fastapi_port = int(os.getenv("FASTAPI_PORT", os.getenv("PORT", "5001")))
        try:
            import uvicorn

            logger.info(f"Starting uvicorn FastAPI app on port {fastapi_port}")
            uvicorn.run("main:app", host="0.0.0.0", port=fastapi_port, log_level="info")
        except Exception as exc:
            logger.exception(f"Failed to start uvicorn: {exc}")
        finally:
            while True:
                time.sleep(60)


app = fastapi_app

if __name__ == "__main__":
    _main()
