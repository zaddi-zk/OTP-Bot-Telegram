"""Server-side entitlement authority for OTP-Bot-Telegram.

Every access-control decision (free calls, premium keys, subscription status,
purchase/loyalty counters) lands here. The database is the ONLY source of
truth; user-editable files (free_calls.txt, subs.txt, premium_keys.json) are
never consulted for grants. If the DB is unavailable the helpers fail closed
(grant nothing) and log loudly, so entitlements can't be cheated or silently
reset by a redeploy of Render's ephemeral disk.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from config import FREE_TRIAL_TOTAL
from core import user_manager as um


logger = logging.getLogger("OTP-Bot.entitlements")


# ----------------------------------------------------------------------
# Privilege
# ----------------------------------------------------------------------
def is_privileged_user(user_id: str) -> bool:
    from config import OWNER_ID, ADMIN_ID, DEVELOPER_IDS
    uid = int(user_id)
    if OWNER_ID is not None and uid == OWNER_ID:
        return True
    if ADMIN_ID is not None and uid == ADMIN_ID:
        return True
    if uid in DEVELOPER_IDS:
        return True
    return False


# ----------------------------------------------------------------------
# Subscription
# ----------------------------------------------------------------------
def check_subscription(user_id: str) -> str:
    """DB-authoritative subscription state: 'ACTIVE' or 'EXPIRED'."""
    if is_privileged_user(user_id):
        return "ACTIVE"
    try:
        if um.is_premium(user_id):
            return "ACTIVE"
    except Exception as exc:
        logger.error("⚠️  Subscription check failed for %s: %s", user_id, exc)
    return "EXPIRED"


def is_premium_user(user_id: str) -> bool:
    return check_subscription(user_id) == "ACTIVE"


def is_full_premium_user(user_id: str) -> bool:
    """True only for full purchased premium (role == 'premium') or privileged."""
    if is_privileged_user(user_id):
        return True
    try:
        info = um.get_user_info(user_id)
        if not info:
            return False
        return info.get("role") == "premium"
    except Exception as exc:
        logger.error("⚠️  Full-premium check failed for %s: %s", user_id, exc)
        return False


# ----------------------------------------------------------------------
# Free calls
# ----------------------------------------------------------------------
def get_free_calls(user_id: str) -> int:
    value = um.get_free_calls_db(user_id)
    if value is None:
        return 0
    return max(0, int(value))


def set_free_calls(user_id: str, count: int) -> None:
    um.set_free_calls_db(user_id, count)


def seed_free_trial_if_needed(user_id: str) -> bool:
    """Grant the 3-call trial once per Telegram user_id. Never re-harvestable."""
    return um.seed_free_calls_once(user_id, FREE_TRIAL_TOTAL)


def decrement_free_call(user_id: str) -> int:
    """Atomically decrement the free-call balance.

    Returns the remaining balance (>= 0), or -1 when the user has none left
    or the authoritative DB is unavailable (fail closed).
    """
    return um.decrement_free_call_db(user_id)


# ----------------------------------------------------------------------
# Purchase / loyalty counters
# ----------------------------------------------------------------------
def get_purchase_count(user_id: str) -> int:
    return um.get_purchase_count_db(user_id)


def increment_purchase_count(user_id: str, amount: int = 1) -> int:
    return um.increment_purchase_count_db(user_id, amount)


def reset_purchase_count(user_id: str) -> None:
    um.reset_purchase_count_db(user_id)


def set_purchase_count(user_id: str, count: int) -> None:
    um.set_purchase_count_db(user_id, count)


def get_loyalty_gift_count(user_id: str) -> int:
    return um.get_loyalty_gift_count_db(user_id)


def increment_loyalty_gift_count(user_id: str, amount: int = 1) -> int:
    return um.increment_loyalty_gift_count_db(user_id, amount)


# ----------------------------------------------------------------------
# Premium keys — stored & claimed in the database
# ----------------------------------------------------------------------
def load_premium_keys() -> List[Dict[str, Any]]:
    return um.list_premium_keys_db()


def save_premium_keys(keys: List[Dict[str, Any]]) -> None:
    """Compatibility shim. Keys are stored in the DB; this logs a warning.

    Real generation goes through generate_premium_key / create_premium_key_db,
    so callers that previously did load/append/save are redirected there.
    """
    logger.warning("🛑 save_premium_keys() is obsolete — keys now live in the DB; ignoring write.")


def generate_premium_key(days: int, created_by: str) -> Optional[Dict[str, Any]]:
    """Create a new premium key in the database. Returns the key dict or None."""
    return um.create_premium_key_db(days, created_by, key_type="premium")


def generate_custom_duration_key(days: int, created_by: str) -> Optional[Dict[str, Any]]:
    return um.create_premium_key_db(days, created_by, key_type="CUSTOM_DURATION")


def generate_free_calls_key(count: int, created_by: str) -> Optional[Dict[str, Any]]:
    return um.create_premium_key_db(0, created_by, key_type="FREE_CALLS", free_calls=count)


def generate_loyalty_key(user_id: str, days: int = 1) -> Optional[Dict[str, Any]]:
    return um.create_premium_key_db(days, "PAYMENT_LOYALTY_SYSTEM", key_type="LOYALTY_GIFT_AUTO", claimed_by=user_id)


def find_premium_key(token: str) -> Optional[Dict[str, Any]]:
    return um.find_premium_key_db(token)


def get_unused_premium_keys() -> List[Dict[str, Any]]:
    return um.get_unused_premium_keys_db()


def get_used_premium_keys() -> List[Dict[str, Any]]:
    return um.get_used_premium_keys_db()


def get_key_stats() -> Dict[str, Any]:
    return um.get_key_stats_db()


def purge_redeemed_keys() -> int:
    """Deletion for the admin /keygc maintenance command. Returns count removed."""
    return um.purge_redeemed_keys_db()


def redeem_premium_key(user_id: str, token: str) -> Tuple[bool, str]:
    """Atomically claim a key and apply it (premium days or free-call package).

    Returns (success, message). The DB claim is guarded on used=0 so a key
    can never be double-redeemed even under concurrency. Grants are persisted
    to the DB only.
    """
    ok, result = um.redeem_premium_key_db(user_id, token)
    if not ok:
        return False, result

    key = result
    key_type = key.get("key_type") or "premium"

    # Free-calls package key.
    if key_type == "FREE_CALLS" or key.get("free_calls") is not None:
        grant = int(key.get("free_calls") or 0)
        current = get_free_calls(user_id)
        set_free_calls(user_id, current + grant)
        logger.info(f"✅ KEY REDEEMED (free-calls): {token} by {user_id} (+{grant} calls)")
        return True, f"{grant} free calls added."

    # Premium duration key.
    days = int(key.get("days") or 0)
    if days <= 0:
        return False, "Invalid premium key configuration."
    now = datetime.now()
    base = now
    current_end = um.get_subscription_end_datetime(user_id)
    if current_end is not None and current_end > now:
        base = current_end
    expiry = base + timedelta(days=days)
    expiry_str = expiry.strftime("%d/%m/%Y")
    db_ok = um.set_user_subscription_end_date(user_id, expiry, role="premium_key")
    if not db_ok:
        return False, "Database write failed. Your key was not applied."
    # Purchase-count adjustment (legacy loyalty behavior, kept for continuity).
    purchases = um.get_purchase_count_db(user_id)
    um.reset_purchase_count_db(user_id)
    um.increment_purchase_count_db(user_id, max(0, purchases - 5))
    logger.info(f"✅ KEY REDEEMED: {token} by {user_id} (+{days} days, expires {expiry_str})")
    return True, expiry_str