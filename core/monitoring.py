"""
Monitoring helpers for OTP-Bot-Telegram.
Provides statistics and usage reports for user conf files.
"""
import logging
from pathlib import Path
from typing import Dict, List

from .files import user_conf_path, get_user_conf_size

logger = logging.getLogger("OTP-Bot.monitoring")


def get_user_conf_metrics(user_id: str) -> Dict[str, int]:
    """Return basic storage metrics for a user's conf directory."""
    path = user_conf_path(user_id)
    return {
        "file_count": len([p for p in path.rglob("*") if p.is_file()]) if path.exists() else 0,
        "total_size_bytes": get_user_conf_size(user_id),
    }


def get_conf_usage_report() -> List[Dict[str, int]]:
    """Return storage usage summary for all users."""
    base = user_conf_path("")
    if not base.exists():
        return []

    report = []
    for user_dir in base.iterdir():
        if not user_dir.is_dir():
            continue
        report.append({
            "user_id": user_dir.name,
            "file_count": len([p for p in user_dir.rglob("*") if p.is_file()]),
            "total_size_bytes": get_user_conf_size(user_dir.name),
        })
    return report
