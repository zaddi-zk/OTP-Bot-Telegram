"""
Adapter to send Telegram Web App links for Live Listen and handle `/hangup` via python-telegram-bot.

This module is optional: you can call `send_live_listen_button(chat_id, call_sid)` from your existing bot logic to post a Web App button.
"""
import os
from urllib.parse import urlencode
from config import BOT_TOKEN, NGROK_URL
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

bot = Bot(
    token=BOT_TOKEN,
    base_url="https://tg-api-proxy.zaddocklangat8.workers.dev/bot",
    base_file_url="https://tg-api-proxy.zaddocklangat8.workers.dev/bot",
)


def live_webapp_url(call_id: str) -> str:
    # Point to your deployed web app (ngrok during dev)
    params = urlencode({'call_id': call_id})
    return f"{NGROK_URL}/live?{params}"


def send_live_listen_button(chat_id: int, call_id: str, text: str = 'Open Live Listen'):
    url = live_webapp_url(call_id)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton('🟢 Live Listen', url=url)]])
    return bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
