import logging
import os
import asyncio
from contextlib import asynccontextmanager

from bot import (
    app as flask_app,
    bot,
    start_background_threads,
    get_runtime_mode,
    start_bot_polling,
    set_telegram_webhook,
    mark_webhook_mode,
    USE_WEBHOOK,
    FLASK_PORT,
)
from live_listen.server import build_app as build_live_listen_app

logger = logging.getLogger(__name__)

startup_done = False


@asynccontextmanager
async def lifespan(app):
    global startup_done
    if not startup_done:
        startup_done = True

        bot.remove_webhook()
        await asyncio.sleep(0.5)

        runtime_mode = get_runtime_mode(bot)

        logger.info("Starting bot in %s mode", runtime_mode)

        if runtime_mode == "webhook":
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
    yield


app = build_live_listen_app(flask_app)
app.router.lifespan_context = lifespan


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", FLASK_PORT))
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=1)
