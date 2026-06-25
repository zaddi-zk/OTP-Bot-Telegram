#!/usr/bin/env python3
"""Helper script to run only the Telegram polling loop as a worker on PythonAnywhere.

Usage: run this as an Always-on task or in a persistent console.
"""
from bot import bot, start_background_threads, start_bot_polling
import logging

logging.basicConfig()
logger = logging.getLogger("start_polling")
logger.setLevel(logging.INFO)

if __name__ == "__main__":
    # Start lightweight background threads used by the bot (scheduler, rate limiter cleanup)
    start_background_threads()
    logger.info("Starting resilient Telegram polling (start_polling.py)")
    try:
        start_bot_polling(
            allowed_updates=["message", "callback_query", "chat_member"],
            max_retries=0,
            base_delay=2,
        )
    except Exception as e:
        logger.error(f"Polling watchdog failed to start: {e}", exc_info=True)
