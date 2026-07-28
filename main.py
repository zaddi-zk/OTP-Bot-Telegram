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
from starlette.middleware.wsgi import WSGIMiddleware
from starlette.applications import Starlette
from starlette.routing import Mount

logger = logging.getLogger(__name__)

app = Starlette(
    routes=[
        Mount("/", app=WSGIMiddleware(flask_app)),
    ],
)

startup_done = False


@app.on_event("startup")
async def startup_event():
    global startup_done
    if startup_done:
        return
    startup_done = True

    bot.remove_webhook()
    time.sleep(0.5)

    from bot import get_runtime_mode, start_bot_polling
    runtime_mode = get_runtime_mode(bot)

    logger.info("Starting bot in %s mode", runtime_mode)

    if runtime_mode == "webhook":
        from bot import set_telegram_webhook, mark_webhook_mode
        base_url = os.getenv("PUBLIC_URL", "")
        if base_url:
            set_telegram_webhook(bot, base_url)
            mark_webhook_mode()
        else:
            logger.warning("PUBLIC_URL not set, falling back to polling")
            start_bot_polling()
    else:
        start_bot_polling()

    start_background_threads()


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", FLASK_PORT))
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=1)
