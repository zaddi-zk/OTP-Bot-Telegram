#!/usr/bin/env python3
"""
Set the Telegram webhook immediately using the running local ngrok tunnel.
This updates .env and conf/settings.txt atomically and calls Telegram's setWebhook API.
Run: python scripts/set_telegram_webhook_now.py
Or pass --url https://abc.ngrok.io to force a URL.
"""
from pathlib import Path
from urllib.parse import urlparse
import argparse
import tempfile
import os
import json
import sys
import requests

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
SETTINGS_PATH = ROOT / "conf" / "settings.txt"

NGROK_API = "http://127.0.0.1:4040/api/tunnels"


def get_ngrok_public_url(port: int = 4040) -> str | None:
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/api/tunnels", timeout=3)
        resp.raise_for_status()
        data = resp.json()
        for t in data.get("tunnels", []):
            if t.get("proto") == "https" and t.get("public_url"):
                return t.get("public_url")
        for t in data.get("tunnels", []):
            if t.get("public_url"):
                return t.get("public_url")
    except Exception as e:
        return None


def normalize_url(raw: str) -> str:
    parsed = urlparse(raw)
    return f"{parsed.scheme}://{parsed.netloc}"


def atomic_update_env(key: str, value: str) -> None:
    text = ""
    if ENV_PATH.exists():
        text = ENV_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    new_lines = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    content = "\n".join(new_lines)
    if content and not content.endswith("\n"):
        content += "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(ENV_PATH.parent), delete=False) as f:
        f.write(content)
        temp = Path(f.name)
    os.replace(str(temp), str(ENV_PATH))


def atomic_update_settings_ngrok(url: str) -> None:
    if not SETTINGS_PATH.exists():
        return
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    data["ngrok_url"] = url
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(SETTINGS_PATH.parent), delete=False) as f:
        json.dump(data, f, indent=2)
        temp = Path(f.name)
    os.replace(str(temp), str(SETTINGS_PATH))


def call_telegram_set_webhook(bot_token: str, webhook_url: str) -> dict:
    api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    try:
        resp = requests.post(api_url, json={"url": webhook_url, "allowed_updates": ["message", "callback_query", "chat_member"]}, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Override ngrok public URL")
    parser.add_argument("--bot-token", help="Telegram bot token (optional, reads from .env if omitted)")
    parser.add_argument("--no-env", action="store_true", help="Do not write .env")
    args = parser.parse_args()

    public = args.url or get_ngrok_public_url()
    if not public:
        print("Could not detect a public ngrok URL. Ensure ngrok is running locally (http://127.0.0.1:4040).")
        sys.exit(2)
    base = normalize_url(public)
    print("Detected ngrok base:", base)

    # Load bot token from .env if available
    bot_token = args.bot_token
    if not bot_token and ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("BOT_TOKEN="):
                bot_token = line.split("=", 1)[1].strip()
                break
    if not bot_token:
        print("BOT_TOKEN not provided and not found in .env. Provide --bot-token or set BOT_TOKEN in .env.")
        sys.exit(3)

    # Build webhook URL
    # Default path used by the bot
    WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/telegram_webhook")
    if not WEBHOOK_PATH.startswith("/"):
        WEBHOOK_PATH = "/" + WEBHOOK_PATH
    webhook_url = f"{base}{WEBHOOK_PATH}"

    print(f"Setting Telegram webhook to: {webhook_url}")

    # Atomically update config files if requested
    if not args.no_env:
        atomic_update_env("NGROK_URL", base)
        atomic_update_env("WEBHOOK_URL", base)
        print("Updated .env with NGROK_URL and WEBHOOK_URL")
    atomic_update_settings_ngrok(base)

    # Call Telegram API
    result = call_telegram_set_webhook(bot_token, webhook_url)
    print("Telegram setWebhook response:", result)
    if not result.get("ok"):
        print("setWebhook failed; check bot token and network connectivity.")
        sys.exit(4)
    print("Done. Telegram webhook updated.")


if __name__ == "__main__":
    main()
