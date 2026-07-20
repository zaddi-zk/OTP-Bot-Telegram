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

from sqlalchemy import Column, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config import CONF_DIR, DATABASE_URL
from core.files import ensure_user_path, write_user_file, read_user_file

logger = logging.getLogger("OTP-Bot.verification")

# Global thread-safe lock to prevent overlapping write collisions.
_SAVE_LOCK = Lock()

# ======================================================================
# Constants
# ======================================================================
VERIFICATIONS_PATH = CONF_DIR / "pending_verifications.json"
APPROVED_PATH = CONF_DIR / "approved_purchases.json"

Base = declarative_base()


class VerificationRecord(Base):
    __tablename__ = "verification_requests"

    verification_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    username = Column(String, nullable=True)
    plan = Column(String, nullable=True)
    plan_name = Column(String, nullable=True)
    price = Column(String, nullable=True)
    days = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending", index=True)
    created_at = Column(String, nullable=True)
    proof_file_id = Column(String, nullable=True)
    proof_type = Column(String, nullable=True)
    proof_submitted_at = Column(String, nullable=True)
    approved_at = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    rejected_at = Column(String, nullable=True)
    rejection_reason = Column(String, nullable=True)
    payload = Column(Text, nullable=True)


class ApprovedPurchaseRecord(Base):
    __tablename__ = "approved_purchases"

    verification_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    plan = Column(String, nullable=True)
    plan_name = Column(String, nullable=True)
    price = Column(String, nullable=True)
    days = Column(String, nullable=True)
    approved_at = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    expiry = Column(String, nullable=True)
    payload = Column(Text, nullable=True)


_engine = None
_SessionLocal = None


def _build_engine():
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    if not DATABASE_URL:
        return None
    _engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=10,
        future=True,
    )
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_session() -> Optional[Session]:
    engine = _build_engine()
    if engine is None or _SessionLocal is None:
        return None
    return _SessionLocal()


def init_verification_db() -> None:
    engine = _build_engine()
    if engine is None:
        return
    Base.metadata.create_all(engine)
    _migrate_legacy_json_records()


def _migrate_legacy_json_records() -> None:
    if not DATABASE_URL:
        return
    session = get_session()
    if session is None:
        return
    try:
        with session.begin():
            existing_pending = session.query(VerificationRecord).count()
            if existing_pending == 0 and VERIFICATIONS_PATH.exists():
                try:
                    payload = json.loads(VERIFICATIONS_PATH.read_text(encoding="utf-8"))
                    if isinstance(payload, list):
                        for item in payload:
                            if isinstance(item, dict):
                                save_verification_record(session, item)
                except Exception as exc:
                    logger.warning(f"⚠️ Unable to migrate pending verifications JSON: {exc}")

            existing_purchases = session.query(ApprovedPurchaseRecord).count()
            if existing_purchases == 0 and APPROVED_PATH.exists():
                try:
                    payload = json.loads(APPROVED_PATH.read_text(encoding="utf-8"))
                    if isinstance(payload, list):
                        for item in payload:
                            if isinstance(item, dict):
                                save_approved_purchase_record(session, item)
                except Exception as exc:
                    logger.warning(f"⚠️ Unable to migrate approved purchases JSON: {exc}")
    finally:
        session.close()


def _serialize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(record)
    payload.pop("verification_id", None)
    payload.pop("user_id", None)
    payload.pop("username", None)
    payload.pop("plan", None)
    payload.pop("plan_name", None)
    payload.pop("price", None)
    payload.pop("days", None)
    payload.pop("status", None)
    payload.pop("created_at", None)
    payload.pop("proof_file_id", None)
    payload.pop("proof_type", None)
    payload.pop("proof_submitted_at", None)
    payload.pop("approved_at", None)
    payload.pop("approved_by", None)
    payload.pop("rejected_at", None)
    payload.pop("rejection_reason", None)
    return payload


def _update_verification_record(record: VerificationRecord, payload: Dict[str, Any]) -> None:
    record.user_id = payload.get("user_id")
    record.username = payload.get("username")
    record.plan = payload.get("plan")
    record.plan_name = payload.get("plan_name")
    record.price = payload.get("price")
    record.days = payload.get("days")
    record.status = payload.get("status") or "pending"
    record.created_at = payload.get("created_at")
    record.proof_file_id = payload.get("proof_file_id")
    record.proof_type = payload.get("proof_type")
    record.proof_submitted_at = payload.get("proof_submitted_at")
    record.approved_at = payload.get("approved_at")
    record.approved_by = payload.get("approved_by")
    record.rejected_at = payload.get("rejected_at")
    record.rejection_reason = payload.get("rejection_reason")
    record.payload = json.dumps(_serialize_record(payload), ensure_ascii=False)


def save_verification_record(session: Session, payload: Dict[str, Any]) -> None:
    verification_id = payload.get("verification_id")
    if not verification_id:
        return
    record = session.get(VerificationRecord, str(verification_id))
    if record is None:
        record = VerificationRecord(verification_id=str(verification_id))
        session.add(record)
    _update_verification_record(record, payload)


def save_approved_purchase_record(session: Session, payload: Dict[str, Any]) -> None:
    verification_id = payload.get("verification_id")
    if not verification_id:
        return
    record = session.get(ApprovedPurchaseRecord, str(verification_id))
    if record is None:
        record = ApprovedPurchaseRecord(verification_id=str(verification_id))
        session.add(record)
    record.user_id = payload.get("user_id")
    record.plan = payload.get("plan")
    record.plan_name = payload.get("plan_name")
    record.price = payload.get("price")
    record.days = payload.get("days")
    record.approved_at = payload.get("approved_at")
    record.approved_by = payload.get("approved_by")
    record.expiry = payload.get("expiry")
    record.payload = json.dumps(payload, ensure_ascii=False)

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
    """Load all verification requests from PostgreSQL, falling back to the legacy JSON file if needed."""
    session = get_session()
    if session is None:
        if not VERIFICATIONS_PATH.exists():
            return []
        try:
            with open(VERIFICATIONS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load verifications: {e}")
            return []

    try:
        rows = session.query(VerificationRecord).all()
        return [
            {
                "verification_id": row.verification_id,
                "user_id": row.user_id,
                "username": row.username,
                "plan": row.plan,
                "plan_name": row.plan_name,
                "price": row.price,
                "days": row.days,
                "status": row.status,
                "created_at": row.created_at,
                "proof_file_id": row.proof_file_id,
                "proof_type": row.proof_type,
                "proof_submitted_at": row.proof_submitted_at,
                "approved_at": row.approved_at,
                "approved_by": row.approved_by,
                "rejected_at": row.rejected_at,
                "rejection_reason": row.rejection_reason,
                "payload": row.payload,
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Failed to load verifications: {e}")
        return []
    finally:
        session.close()

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
    """Persist verifications into PostgreSQL."""
    session = get_session()
    if session is None:
        _atomic_json_write(verifications, VERIFICATIONS_PATH, "Failed to save verifications")
        return

    try:
        with session.begin():
            for verification in verifications:
                save_verification_record(session, verification)
    except Exception as exc:
        logger.error(f"Failed to save verifications: {exc}")
        _atomic_json_write(verifications, VERIFICATIONS_PATH, "Failed to save verifications")
    finally:
        session.close()

def load_approved_purchases() -> List[Dict[str, Any]]:
    """Load all approved purchases from PostgreSQL."""
    session = get_session()
    if session is None:
        if not APPROVED_PATH.exists():
            return []
        try:
            with open(APPROVED_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load approved purchases: {e}")
            return []

    try:
        rows = session.query(ApprovedPurchaseRecord).all()
        return [
            {
                "verification_id": row.verification_id,
                "user_id": row.user_id,
                "plan": row.plan,
                "plan_name": row.plan_name,
                "price": row.price,
                "days": row.days,
                "approved_at": row.approved_at,
                "approved_by": row.approved_by,
                "expiry": row.expiry,
                "payload": row.payload,
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Failed to load approved purchases: {e}")
        return []
    finally:
        session.close()

def save_approved_purchases(purchases: List[Dict[str, Any]]) -> None:
    """Persist approved purchases into PostgreSQL."""
    session = get_session()
    if session is None:
        _atomic_json_write(purchases, APPROVED_PATH, "Failed to save approved purchases")
        return

    try:
        with session.begin():
            for purchase in purchases:
                save_approved_purchase_record(session, purchase)
    except Exception as exc:
        logger.error(f"Failed to save approved purchases: {exc}")
        _atomic_json_write(purchases, APPROVED_PATH, "Failed to save approved purchases")
    finally:
        session.close()

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
