"""
Configuration management helper for OTP-Bot-Telegram.
Works with conf/settings.txt and provides atomic load/save semantics.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from config import CONF_DIR
from .files import _atomic_write_json, _safe_read_json

logger = logging.getLogger("OTP-Bot.config_manager")

SETTINGS_FILE = CONF_DIR / "settings.txt"


def load_settings() -> Dict[str, Any]:
    """Load JSON settings from conf/settings.txt."""
    return _safe_read_json(SETTINGS_FILE, {})


def save_settings(settings: Dict[str, Any]) -> None:
    """Write configuration settings atomically."""
    try:
        _atomic_write_json(SETTINGS_FILE, settings)
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")
        raise


def get_setting(key: str, default: Any = None) -> Any:
    """Get a single setting value from conf/settings.txt."""
    settings = load_settings()
    return settings.get(key, default)


def set_setting(key: str, value: Any) -> None:
    """Set a single configuration value and persist it."""
    settings = load_settings()
    settings[key] = value
    save_settings(settings)
