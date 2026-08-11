"""
config.py – Unified configuration with env + settings.txt fallback.
All settings are accessible as attributes of the `config` object.
"""
import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
CONF_DIR = BASE_DIR / "conf"
SETTINGS_FILE = CONF_DIR / "settings.txt"

def _load_settings_txt() -> Dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

_settings_txt = _load_settings_txt()

def _get(key: str, default=None) -> Any:
    """Get from env, fallback to settings.txt."""
    val = os.getenv(key)
    if val is not None:
        return val
    # Try various key forms in settings.txt
    for k in [key, key.lower(), key.upper(), key.replace("_", "")]:
        if k in _settings_txt:
            return _settings_txt[k]
    return default

# =============================================================================
# Configuration values
# =============================================================================

# Telegram
BOT_TOKEN = _get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Twilio
ACCOUNT_SID = _get("TWILIO_ACCOUNT_SID", "YOUR_TWILIO_SID_HERE")
TWILIO_ACCOUNT_SID = ACCOUNT_SID
AUTH_TOKEN = _get("TWILIO_AUTH_TOKEN", "YOUR_TWILIO_AUTH_TOKEN_HERE")
TWILIO_AUTH_TOKEN = AUTH_TOKEN
TWILIO_PHONE_NUMBER = _get("TWILIO_PHONE_NUMBER", "+1234567890")
# Separate outbound caller ID: toll-free numbers (+1855, +1888, +1800) are often
# blocked by carriers for outbound calls. Set OUTBOUND_CALLER_ID to a local
# (non-toll-free) Twilio number to bypass carrier spam filters. Falls back to
# TWILIO_PHONE_NUMBER if not set.
OUTBOUND_CALLER_ID = _get("OUTBOUND_CALLER_ID", "").strip() or TWILIO_PHONE_NUMBER
NGROK_URL = _get("NGROK_URL", "https://your-ngrok-url.ngrok-free.dev")

# =============================================================================
# Twilio Proxy number pool (multi-number concurrency)
# =============================================================================
# The Proxy Service SID is the authoritative pool registry. PROXY_POOL_NUMBERS
# is the comma-separated E.164 fallback list used when the Proxy Service is not
# reachable/configured.
PROXY_SERVICE_SID = _get("PROXY_SERVICE_SID", "").strip()
PROXY_POOL_NUMBERS = _get("PROXY_POOL_NUMBERS", "")
PROXY_POOL = [n.strip() for n in PROXY_POOL_NUMBERS.split(",") if n.strip()]
_pool_configured = bool(PROXY_SERVICE_SID or PROXY_POOL)
PROXY_POOL_ENABLED = _get(
    "PROXY_POOL_ENABLED", "true" if _pool_configured else "false"
).strip().lower() in ("true", "1", "yes", "on")
PROXY_LEASE_TTL_SECONDS = int(_get("PROXY_LEASE_TTL_SECONDS", "3600"))
PROXY_QUEUE_TTL_SECONDS = int(_get("PROXY_QUEUE_TTL_SECONDS", "120"))
NGROK_TOKEN = _get("NGROK_TOKEN", "")

# Channels
MAIN_CHANNEL_URL = _get("MAIN_CHANNEL_URL", "https://t.me/your_main_channel")
BACKUP_CHANNEL_URL = _get("BACKUP_CHANNEL_URL", "https://t.me/your_backup_channel")
VOUCH_CHANNEL_URL = _get("VOUCH_CHANNEL_URL", "https://t.me/your_vouch_channel")
MAIN_CHANNEL_ID = _get("MAIN_CHANNEL_ID", "")
BACKUP_CHANNEL_ID = _get("BACKUP_CHANNEL_ID", "")
VOUCH_CHANNEL_ID = _get("VOUCH_CHANNEL_ID", "-1004364877298")

# Admins
OWNER_ID = _get("OWNER_ID")
if OWNER_ID is not None:
    try:
        OWNER_ID = int(OWNER_ID)
    except:
        OWNER_ID = None

ADMIN_ID = _get("ADMIN_ID")
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

# Free trial
FREE_TRIAL_TOTAL = int(_get("FREE_TRIAL_CALLS", "5"))

# Payment addresses
PAYMENT_ADDRESSES = {
    "BTC": _get("PAYMENT_BTC", "YOUR_WALLET_ADDRESS_HERE"),
    "ETH": _get("PAYMENT_ETH", "YOUR_WALLET_ADDRESS_HERE"),
    "LTC": _get("PAYMENT_LTC", "YOUR_WALLET_ADDRESS_HERE"),
    "USDT_ERC20": _get("PAYMENT_USDT", "YOUR_WALLET_ADDRESS_HERE"),
}



# Live Listen URL (defaults to NGROK_URL)
LIVE_LISTEN_URL = _get("LIVE_LISTEN_URL", NGROK_URL)
LIVE_LISTEN_SECRET = _get("LIVE_LISTEN_SECRET", "")

# Abstract API
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

# Twilio validation override (default: disabled for development)
DISABLE_TWILIO_VALIDATION = _get("DISABLE_TWILIO_VALIDATION", "false").lower() in ("true", "1", "yes")

# Disable DummyBot fallback
DISABLE_DUMMY_BOT = _get("DISABLE_DUMMY_BOT", "false").lower() in ("true", "1", "yes")

# Telegram webhook mode
USE_WEBHOOK = _get("USE_WEBHOOK", "false").lower() in ("true", "1", "yes")
WEBHOOK_URL = _get("WEBHOOK_URL", "").strip()
WEBHOOK_PATH = _get("WEBHOOK_PATH", "/telegram_webhook").strip()
TELEGRAM_API_BASE_URL = _get("TELEGRAM_API_BASE_URL", "https://tg-api-proxy.zaddocklangat8.workers.dev/bot").rstrip("/")

# Database
DATABASE_URL = _get("DATABASE_URL", "").strip()  # Railway PostgreSQL connection string
USE_POSTGRES = bool(DATABASE_URL)

# Log DATABASE_URL status on module load (without exposing the actual URL)
if USE_POSTGRES:
    import logging as _config_log
    _log = _config_log.getLogger("config")
    _log.info("✅ DATABASE_URL is configured - PostgreSQL user persistence ENABLED")
else:
    import logging as _config_log
    _log = _config_log.getLogger("config")
    _log.warning("⚠️  DATABASE_URL not configured - PostgreSQL user persistence DISABLED (users will not persist!)")

# Derived channel IDs (if URLs given but IDs not)
def _derive_channel_id(url: str, fallback: str) -> str:
    if fallback:
        return fallback
    if not url:
        return ""
    url = url.strip().rstrip("/")
    if url.endswith("t.me"):
        return ""
    last = url.split("/")[-1]
    if not last:
        return ""
    if last.startswith("@"):
        return last
    if last.startswith("+"):
        return url
    return "@" + last

MAIN_CHANNEL_ID = _derive_channel_id(MAIN_CHANNEL_URL, MAIN_CHANNEL_ID)
BACKUP_CHANNEL_ID = _derive_channel_id(BACKUP_CHANNEL_URL, BACKUP_CHANNEL_ID)

REQUIRED_CHANNELS = [ch for ch in [MAIN_CHANNEL_ID, BACKUP_CHANNEL_ID, VOUCH_CHANNEL_ID] if ch]

# =============================================================================
# Helper functions
# =============================================================================
def _normalize_public_base_url(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return None
    normalized = f"{parsed.scheme}://{parsed.netloc}"
    return normalized.rstrip("/")


def build_public_base_url() -> str:
    """Return one canonical public base URL for webhooks and media stream endpoints."""
    candidates = [
        ("PUBLIC_URL (os.environ)", os.getenv("PUBLIC_URL")),
        ("BASE_URL (os.environ)", os.getenv("BASE_URL")),
        ("WEBHOOK_URL (os.environ)", os.getenv("WEBHOOK_URL")),
        ("NGROK_URL (os.environ)", os.getenv("NGROK_URL")),
        ("LIVE_LISTEN_URL (os.environ)", os.getenv("LIVE_LISTEN_URL")),
        ("_get PUBLIC_URL", _get("PUBLIC_URL", "")),
        ("_get BASE_URL", _get("BASE_URL", "")),
        ("_get WEBHOOK_URL", _get("WEBHOOK_URL", "")),
        ("_get NGROK_URL", _get("NGROK_URL", "")),
        ("_get LIVE_LISTEN_URL", _get("LIVE_LISTEN_URL", "")),
    ]
    print("=" * 60, flush=True)
    print("MEDIA STREAM URL PROVENANCE", flush=True)
    print("=" * 60, flush=True)
    for label, value in candidates:
        if value:
            print(f"  {label} = {value}", flush=True)
        else:
            print(f"  {label} = (empty/None)", flush=True)
    for label, candidate in candidates:
        normalized = _normalize_public_base_url(candidate)
        if normalized:
            print(f"  >>> WINNER: {label} = {normalized}", flush=True)
            print("=" * 60, flush=True)
            return normalized
    print("  >>> NO CANDIDATE FOUND - returning empty string", flush=True)
    print("=" * 60, flush=True)
    return ""


def is_twilio_configured() -> bool:
    """Check if Twilio credentials are properly set."""
    if not ACCOUNT_SID or "YOUR_" in ACCOUNT_SID:
        return False
    if not AUTH_TOKEN or "YOUR_" in AUTH_TOKEN:
        return False
    if not TWILIO_PHONE_NUMBER or "1234567890" in TWILIO_PHONE_NUMBER:
        return False
    if not NGROK_URL or "your-ngrok-url" in NGROK_URL:
        return False
    return NGROK_URL.startswith("http")

def is_privileged_user(user_id: str) -> bool:
    uid = int(user_id)
    if OWNER_ID is not None and uid == OWNER_ID:
        return True
    if ADMIN_ID is not None and uid == ADMIN_ID:
        return True
    if uid in DEVELOPER_IDS:
        return True
    return False
# SMS provider settings
SMS_PROVIDER = _get("SMS_PROVIDER", "twilio")  # 'twilio' or 'generic'
SMS_API_URL = _get("SMS_API_URL", "")
SMS_API_KEY = _get("SMS_API_KEY", "")

# =============================================================================
# Voice Configuration
# =============================================================================

# Default voice for new users (fallback when no voice is selected)
DEFAULT_VOICE_ID = _get("DEFAULT_VOICE_ID", "")

# =============================================================================
# AI SETTINGS
# =============================================================================

# Enable/disable AI flow globally (support both AI_FLOW_ENABLED and USE_AI_FLOW env names)
AI_FLOW_ENABLED = _get("AI_FLOW_ENABLED", _get("USE_AI_FLOW", "true")).lower() in ("true", "1", "yes")
USE_AI_FLOW = AI_FLOW_ENABLED

# Groq LLM API (fast, production-ready)
GROQ_API_KEY = _get("GROQ_API_KEY", "YOUR_GROQ_API_KEY_HERE")
GROQ_MODEL = _get("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_FALLBACK_MODEL = _get("GROQ_FALLBACK_MODEL", "llama-3.3-70b-versatile")

# Groq Whisper API for speech-to-text (ASR)
WHISPER_MODEL = _get("WHISPER_MODEL", "whisper-large-v3")

# Compatibility: Ollama local LLM settings used by legacy scripts/tests
OLLAMA_URL = _get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = _get("OLLAMA_MODEL", "llama3.1:8b")

# =============================================================================
# VAPI CONFIGURATION
# =============================================================================
VAPI_API_KEY = _get("VAPI_API_KEY", "YOUR_VAPI_API_KEY_HERE")
VAPI_ASSISTANT_ID = _get("VAPI_ASSISTANT_ID", "")
VAPI_PHONE_NUMBER_ID = _get("VAPI_PHONE_NUMBER_ID", "")
VAPI_WEBHOOK_SECRET = _get("VAPI_WEBHOOK_SECRET", "")
VAPI_MODEL = _get("VAPI_MODEL", "chat-latest")
VAPI_MODEL_PROVIDER = _get("VAPI_MODEL_PROVIDER", "groq")
VAPI_MODEL_NAME = _get("VAPI_MODEL_NAME", "llama-3.1-8b-instant")
# Optional mapping from legacy voice IDs -> Vapi voice IDs.
# Fill with known mappings if you have Vapi voice IDs for existing legacy voices.
LEGACY_VOICE_ID_MAP = {}
