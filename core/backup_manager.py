"""
Backup utilities for OTP-Bot-Telegram.
Provides user-conf backup creation and restore operations.
"""
import logging
from pathlib import Path

from .files import archive_user_conf, list_user_conf_backups, restore_user_conf_from_archive

logger = logging.getLogger("OTP-Bot.backup_manager")


def backup_user_conf(user_id: str, tag: str = None) -> Path:
    """Create a timestamped backup archive for a user."""
    archive = archive_user_conf(user_id, tag)
    if archive:
        logger.info(f"Created backup for user {user_id}: {archive.name}")
        return archive
    raise RuntimeError(f"Failed to create backup for user {user_id}")


def list_user_backups(user_id: str):
    """Return sorted list of backup archive Paths for a user."""
    return list_user_conf_backups(user_id)


def restore_user_conf_from_backup(user_id: str, archive_name: str) -> bool:
    """Restore a user backup archive."""
    success = restore_user_conf_from_archive(user_id, archive_name)
    if success:
        logger.info(f"Restored backup {archive_name} for user {user_id}")
    return success
