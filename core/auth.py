import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from config import (
    OWNER_ID, ADMIN_ID, DEVELOPER_IDS, FREE_TRIAL_TOTAL,
)
from core.entitlements import (
    is_privileged_user,
    check_subscription,
    get_free_calls,
    set_free_calls,
    decrement_free_call,
    get_purchase_count,
    increment_purchase_count,
)

logger = logging.getLogger("OTP-Bot.auth")

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
        from core import user_manager as _um
        expiry = _um.get_subscription_end_date(user_id) or "Active"
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
