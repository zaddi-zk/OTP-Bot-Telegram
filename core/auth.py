import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from config import (
    OWNER_ID, ADMIN_ID, DEVELOPER_IDS, FREE_TRIAL_TOTAL,
)
from core.files import read_user_file, write_user_file, user_conf_path, ensure_user_path, get_master_free_calls, set_master_free_calls, delete_master_free_calls
from core import user_manager

logger = logging.getLogger("OTP-Bot.auth")

def is_privileged_user(user_id: str) -> bool:
    uid = int(user_id)
    if OWNER_ID is not None and uid == OWNER_ID:
        return True
    if ADMIN_ID is not None and uid == ADMIN_ID:
        return True
    if uid in DEVELOPER_IDS:
        return True
    return False

def check_subscription(user_id: str) -> str:
    if is_privileged_user(user_id):
        return "ACTIVE"
    # Prefer Postgres as the source of truth when available.
    try:
        # If DB reports premium/active, return ACTIVE and keep file in sync.
        if user_manager.is_premium(user_id):
            db_sub_end = user_manager.get_subscription_end_date(user_id)
            if db_sub_end:
                # Ensure file matches DB formatted date
                try:
                    file_expiry = read_user_file(user_id, "subs.txt", "")
                    if file_expiry != db_sub_end:
                        write_user_file(user_id, "subs.txt", db_sub_end)
                        logger.debug(f"Synced subs.txt for {user_id} to DB expiry {db_sub_end}")
                except Exception:
                    pass
            return "ACTIVE"
    except Exception:
        # DB unavailable or error — fall back to file-based check
        pass

    expiry_str = read_user_file(user_id, "subs.txt", "")
    if not expiry_str:
        return "EXPIRED"
    try:
        expiry = datetime.strptime(expiry_str, "%d/%m/%Y")
        return "ACTIVE" if expiry >= datetime.now() else "EXPIRED"
    except:
        return "EXPIRED"

def get_free_calls(user_id: str) -> int:
    try:
        # Prefer the master store (server-side authoritative)
        master = get_master_free_calls(user_id)
        if master is not None:
            return int(master)
        # Fallback to legacy per-user file
        return int(read_user_file(user_id, "free_calls.txt", "0"))
    except:
        return 0

def set_free_calls(user_id: str, count: int) -> None:
    # Persist both in master store and per-user file for compatibility
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
    if check_subscription(user_id) == "ACTIVE":
        expiry = read_user_file(user_id, "subs.txt", "Unknown")
        return (
            f"🛡️ Role: {role}\n"
            f"💎 Plan: PREMIUM\n"
            f"⏳ Subscription: Active until {expiry}\n"
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
