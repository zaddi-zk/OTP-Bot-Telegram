"""
Data migration utilities for OTP-Bot-Telegram conf files.
Supports migrating legacy filenames and directory structures.
"""
import logging
import shutil
from pathlib import Path
from typing import Dict

from .files import user_conf_path, ensure_user_path, normalize_legacy_user_filename

logger = logging.getLogger("OTP-Bot.migration")

LEGACY_FILENAME_MAP: Dict[str, str] = {
    "name.txt": "name.txt",
    "company name.txt": "company_name.txt",
    "phonenum.txt": "phone_number.txt",
    "caller id.txt": "caller_id.txt",
    "from name.txt": "from_name.txt",
    "voice.txt": "voice_id.txt",
    "voicename.txt": "voice_name.txt",
    "digits.txt": "otp_digits.txt",
    "delivery.txt": "delivery.txt",
    "language.txt": "language.txt",
    "subs.txt": "subs.txt",
    "free_calls.txt": "free_calls.txt",
    "purchase_count.txt": "purchase_count.txt",
    "custom_script.txt": "custom_script.txt",
    "state.txt": "state.txt",
}


def migrate_user_conf_dir(user_id: str) -> None:
    """Migrate legacy user conf filenames into a normalized structure."""
    path = user_conf_path(user_id)
    if not path.exists() or not path.is_dir():
        return

    ensure_user_path(user_id)
    for file_path in path.iterdir():
        if not file_path.is_file():
            continue
        normalized = normalize_legacy_user_filename(file_path.name)
        target_path = path / normalized
        if target_path.exists() and target_path != file_path:
            logger.debug(f"Skipping rename of {file_path.name} because {target_path.name} already exists")
            continue
        if file_path.name != target_path.name:
            try:
                file_path.rename(target_path)
                logger.info(f"Migrated legacy file {file_path.name} -> {target_path.name}")
            except Exception as e:
                logger.error(f"Failed to migrate {file_path.name} for user {user_id}: {e}")


def normalize_legacy_user_filename(filename: str) -> str:
    """Return a canonical filename for legacy keys."""
    return LEGACY_FILENAME_MAP.get(filename.strip().lower(), filename.strip())
