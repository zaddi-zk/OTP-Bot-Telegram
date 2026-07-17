#!/usr/bin/env python3
"""Helper script to run only the Telegram polling loop as a worker on PythonAnywhere.

Usage: run this as an Always-on task or in a persistent console.
"""
import logging

from bot import bot, start_background_threads, start_bot_polling, force_delete_telegram_webhook

logging.basicConfig()
logger = logging.getLogger("start_polling")
logger.setLevel(logging.INFO)

if __name__ == "__main__":
    # Start lightweight background threads used by the bot (scheduler, rate limiter cleanup)
    start_background_threads()
    logger.info("Starting resilient Telegram polling (start_polling.py)")
    if bot is not None:
        try:
            try:
                bot.remove_webhook()
                logger.info("Telegram webhook removed via library before polling startup.")
            except Exception:
                logger.debug("bot.remove_webhook() failed; attempting HTTP API deleteWebhook fallback.")
                if force_delete_telegram_webhook():
                    logger.info("Telegram webhook removed via HTTP API fallback before polling startup.")
                else:
                    logger.warning("Failed to remove Telegram webhook via both library and HTTP API.")
        except Exception as e:
            logger.warning(f"Failed to remove existing Telegram webhook before polling: {e}")
    try:
        start_bot_polling(
            allowed_updates=["message", "callback_query", "chat_member"],
            base_delay=2,
        )
        # Keep the main process alive while polling runs in background thread
        while True:
            import time
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutdown requested. Stopping polling.")
    except Exception as e:
        logger.error(f"Polling watchdog failed: {e}", exc_info=True)
