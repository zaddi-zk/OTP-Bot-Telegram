"""
Payment Verification System for OTP-Bot-Telegram.
Handles proof submission, admin approval, and tracking of premium purchases.
Stores pending verifications with automatic forwarding to admin & developer.
"""
import json
import logging
import os
import secrets
import string
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Optional, Dict, List, Any, Tuple

from core.files import ensure_user_path, write_user_file, read_user_file

logger = logging.getLogger("OTP-Bot.verification")

# Global thread-safe lock to prevent overlapping write collisions.
_SAVE_LOCK = Lock()

# ======================================================================
# Constants
# ======================================================================
VERIFICATIONS_PATH = Path("conf") / "pending_verifications.json"
APPROVED_PATH = Path("conf") / "approved_purchases.json"

PLAN_MAPPING = {
    "plan_3hourtrial": {"name": "3 Hour Trial", "price": "$5", "days": 0.125},
    "plan_1day": {"name": "1 Day", "price": "$16", "days": 1},
    "plan_3days": {"name": "3 Days", "price": "$35", "days": 3},
    "plan_1week": {"name": "1 Week", "price": "$70", "days": 7},
    "plan_lifetime": {"name": "Lifetime", "price": "$95", "days": 9999},
}

# ======================================================================
# Verification Storage
# ======================================================================
def load_verifications() -> List[Dict[str, Any]]:
    """Load all pending verifications."""
    if not VERIFICATIONS_PATH.exists():
        return []
    try:
        with open(VERIFICATIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load verifications: {e}")
        return []

def _atomic_json_write(data: Any, target_path: Path, error_label: str) -> None:
    """Persist JSON atomically using an isolation lock and os.replace()."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(".tmp")

    with _SAVE_LOCK:
        try:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass

            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            os.replace(temp_path, target_path)
        except Exception as e:
            logger.error(f"{error_label}: {e}", exc_info=True)
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            raise


def save_verifications(verifications: List[Dict[str, Any]]) -> None:
    """Save verifications atomically and safely."""
    _atomic_json_write(verifications, VERIFICATIONS_PATH, "Failed to save verifications")

def load_approved_purchases() -> List[Dict[str, Any]]:
    """Load all approved purchases."""
    if not APPROVED_PATH.exists():
        return []
    try:
        with open(APPROVED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load approved purchases: {e}")
        return []

def save_approved_purchases(purchases: List[Dict[str, Any]]) -> None:
    """Save approved purchases atomically and safely."""
    _atomic_json_write(purchases, APPROVED_PATH, "Failed to save approved purchases")

# ======================================================================
# Verification Creation
# ======================================================================
def create_verification_request(
    user_id: str,
    plan_key: str,
    username: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Create a new verification request for a plan.
    
    Args:
        user_id: Telegram user ID
        plan_key: Plan identifier (e.g., "plan_1day")
        username: Optional Telegram username
    
    Returns:
        Verification request dict or None if plan not found
    """
    plan_info = PLAN_MAPPING.get(plan_key)
    if not plan_info:
        return None
    
    # Generate unique verification ID
    verification_id = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    
    verification = {
        "verification_id": verification_id,
        "user_id": user_id,
        "username": username or f"User{user_id}",
        "plan": plan_key,
        "plan_name": plan_info["name"],
        "price": plan_info["price"],
        "days": plan_info["days"],
        "status": "pending",
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "proof_file_id": None,
        "proof_type": None,  # "photo", "document", "text"
        "approved_at": None,
        "approved_by": None,
    }
    
    verifications = load_verifications()
    verifications.append(verification)
    save_verifications(verifications)
    
    logger.info(f"Created verification {verification_id} for user {user_id} - Plan: {plan_key}")
    return verification

def find_user_pending_verification(user_id: str) -> Optional[Dict[str, Any]]:
    """Find a user's pending verification request."""
    verifications = load_verifications()
    for v in verifications:
        if v.get("user_id") == user_id and v.get("status") == "pending":
            return v
    return None

def add_proof_to_verification(
    verification_id: str,
    file_id: str,
    proof_type: str,
) -> bool:
    """
    Add proof attachment to a verification request.
    
    Args:
        verification_id: ID of verification
        file_id: Telegram file_id of proof
        proof_type: "photo", "document", or "text"
    
    Returns:
        True if successful
    """
    verifications = load_verifications()
    for v in verifications:
        if v.get("verification_id") == verification_id:
            v["proof_file_id"] = file_id
            v["proof_type"] = proof_type
            v["proof_submitted_at"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            save_verifications(verifications)
            logger.info(f"Proof added to verification {verification_id}")
            return True
    return False

# ======================================================================
# Admin Approval
# ======================================================================
def generate_approval_key(user_id: str, days: float) -> str:
    """Generate a key for admin to use with /approve command."""
    return f"/approve {user_id} {int(days) if days != 0.125 else '3h'}"

def approve_verification(
    verification_id: str,
    approved_by: str,
) -> Tuple[bool, str]:
    """
    Approve a verification and apply premium.
    
    Args:
        verification_id: ID of verification to approve
        approved_by: Admin user ID who approved
    
    Returns:
        (success: bool, message: str)
    """
    verifications = load_verifications()
    
    for v in verifications:
        if v.get("verification_id") == verification_id:
            if v.get("status") == "approved":
                return False, "This verification is already approved."
            
            user_id = v.get("user_id")
            days = v.get("days", 0)
            plan_name = v.get("plan_name", "Unknown Plan")
            price = v.get("price", "$0")
            
            # Calculate expiry date
            if days == 9999:  # Lifetime
                expiry = datetime.now() + timedelta(days=36500)  # 100 years
                expiry_str = "LIFETIME"
            elif days == 0.125:  # 3 hours
                expiry = datetime.now() + timedelta(hours=3)
                expiry_str = expiry.strftime("%d/%m/%Y %H:%M")
            else:
                expiry = datetime.now() + timedelta(days=days)
                expiry_str = expiry.strftime("%d/%m/%Y")
            
            # Update verification
            v["status"] = "approved"
            v["approved_at"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            v["approved_by"] = approved_by
            
            # Apply premium to user
            write_user_file(user_id, "subs.txt", expiry_str)
            
            # Save to approved purchases
            purchase = {
                "verification_id": verification_id,
                "user_id": user_id,
                "plan": v.get("plan"),
                "plan_name": plan_name,
                "price": price,
                "days": days,
                "approved_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "approved_by": approved_by,
                "expiry": expiry_str,
            }
            
            approved = load_approved_purchases()
            approved.append(purchase)
            save_approved_purchases(approved)
            
            # Save verifications
            save_verifications(verifications)
            
            logger.info(f"Verification {verification_id} approved by {approved_by}")
            return True, f"✅ User {user_id} approved for {plan_name} - Expires: {expiry_str}"
    
    return False, "Verification not found."

def reject_verification(verification_id: str, reason: str = "") -> Tuple[bool, str]:
    """Reject a verification request."""
    verifications = load_verifications()
    
    for v in verifications:
        if v.get("verification_id") == verification_id:
            v["status"] = "rejected"
            v["rejected_at"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            v["rejection_reason"] = reason
            save_verifications(verifications)
            logger.info(f"Verification {verification_id} rejected")
            return True, f"Verification {verification_id} rejected."
    
    return False, "Verification not found."

# ======================================================================
# Query & Stats
# ======================================================================
def get_pending_verifications() -> List[Dict[str, Any]]:
    """Get all pending verifications."""
    return [v for v in load_verifications() if v.get("status") == "pending"]

def get_verification_by_id(verification_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific verification by ID."""
    for v in load_verifications():
        if v.get("verification_id") == verification_id:
            return v
    return None

def format_verification_for_admin(verification: Dict[str, Any]) -> str:
    """
    Format a verification for display to admin with copy-paste approval command.
    
    Returns:
        Formatted text with verification details and approval instruction
    """
    verification_id = verification.get("verification_id", "N/A")
    user_id = verification.get("user_id", "N/A")
    username = verification.get("username", "N/A")
    plan_name = verification.get("plan_name", "N/A")
    price = verification.get("price", "N/A")
    days = verification.get("days", "N/A")
    created_at = verification.get("created_at", "N/A")
    
    # Approval command suggestion
    if days == 0.125:
        time_str = "3h"
    elif days == 9999:
        time_str = "lifetime"
    else:
        time_str = f"{int(days)}d"
    
    approval_cmd = f"/approve {user_id} {time_str}"
    
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💳 <b>PAYMENT VERIFICATION RECEIVED</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Verification ID:</b> <code>{verification_id}</code>\n"
        f"<b>User:</b> <code>{username}</code> (ID: <code>{user_id}</code>)\n"
        f"<b>Plan:</b> {plan_name}\n"
        f"<b>Amount:</b> {price}\n"
        f"<b>Duration:</b> {days} day(s)\n"
        f"<b>Submitted:</b> {created_at}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ <b>TO APPROVE - COPY & PASTE:</b>\n"
        f"<code>{approval_cmd}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    return text
