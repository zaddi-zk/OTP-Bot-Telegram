"""PostgreSQL-backed user database management for the OTP bot.

All user records are stored in Railway PostgreSQL via SQLAlchemy.
No SQLite or JSON-based user store is used.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class _SessionTransaction:
    def __init__(self, session: Any):
        self._session = session
        self._started = False

    def __enter__(self):
        if hasattr(self._session, "begin"):
            self._transaction = self._session.begin()
            return self._transaction.__enter__()
        self._started = True
        return self._session

    def __exit__(self, exc_type, exc, tb):
        if hasattr(self._session, "begin"):
            return self._transaction.__exit__(exc_type, exc, tb)
        if exc_type is None:
            if hasattr(self._session, "commit"):
                self._session.commit()
            return False
        if hasattr(self._session, "rollback"):
            self._session.rollback()
        return False

from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config import CONF_DIR, DATABASE_URL

logger = logging.getLogger("OTP-Bot.user_manager")

Base = declarative_base()


class UserRecord(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True)
    is_premium = Column(Integer, nullable=False, default=0, index=True)
    subscription_end_date = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    last_activity = Column(String, nullable=False)
    role = Column(String, nullable=False, default="free", index=True)
    notes = Column(Text, nullable=True)


_engine = None
_SessionLocal = None


def _build_engine():
    """Create the SQLAlchemy engine once and reuse it."""
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine

    if not DATABASE_URL:
        logger.error("\n" + "="*70)
        logger.error("🚨 CRITICAL: DATABASE_URL is NOT configured!")
        logger.error("   Users WILL NOT persist to PostgreSQL")
        logger.error("   View Users button will show: 'No users found'")
        logger.error("   Premium status updates will NOT work")
        logger.error("")
        logger.error("   FIX: Set DATABASE_URL in Railway environment variables")
        logger.error("   Then restart the bot")
        logger.error("="*70 + "\n")
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
    """Return a session bound to PostgreSQL."""
    engine = _build_engine()
    if engine is None or _SessionLocal is None:
        return None
    return _SessionLocal()


def _timestamp_now() -> str:
    return datetime.now().isoformat()


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        for fmt in ("%d/%m/%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def _ensure_user_exists(session: Session, user_id: str) -> UserRecord:
    record = session.get(UserRecord, str(user_id))
    if record is None:
        now = _timestamp_now()
        record = UserRecord(
            user_id=str(user_id),
            is_premium=0,
            created_at=now,
            last_activity=now,
            role="free",
            notes="",
        )
        session.add(record)
    return record


def init_user_db() -> None:
    """Initialize the PostgreSQL schema and migrate any legacy JSON users."""
    engine = _build_engine()
    if engine is None:
        return

    try:
        Base.metadata.create_all(engine)
        migrate_legacy_json_users()
        logger.info("✅ PostgreSQL user database initialized")
    except Exception as exc:
        logger.error(f"❌ Failed to initialize user database: {exc}")


def add_user_if_not_exists(user_id: str) -> bool:
    """Create a user in PostgreSQL when they do not already exist."""
    session = get_session()
    if session is None:
        logger.warning(f"⚠️  Cannot add user {user_id}: DATABASE_URL not configured (PostgreSQL disabled)")
        return False

    try:
        with _SessionTransaction(session):
            existing = session.get(UserRecord, str(user_id))
            if existing is not None:
                logger.debug(f"User {user_id} already exists")
                return False

            now = _timestamp_now()
            user = UserRecord(
                user_id=str(user_id),
                is_premium=0,
                created_at=now,
                last_activity=now,
                role="free",
                notes="",
            )
            session.add(user)

        logger.info(f"✅ NEW USER CREATED in PostgreSQL: {user_id}")
        return True
    except Exception as exc:
        logger.error(f"❌ Failed to add user {user_id}: {exc}")
        return False
    finally:
        session.close()


def update_last_activity(user_id: str) -> None:
    """Update the user's last activity timestamp."""
    session = get_session()
    if session is None:
        return

    try:
        with _SessionTransaction(session):
            user = _ensure_user_exists(session, user_id)
            user.last_activity = _timestamp_now()
    except Exception as exc:
        logger.error(f"❌ Failed to update activity for {user_id}: {exc}")
    finally:
        session.close()


def set_user_premium(user_id: str, is_premium: bool = True, days_duration: int = 30) -> bool:
    """Set a user as premium or free in PostgreSQL."""
    session = get_session()
    if session is None:
        return False

    try:
        with _SessionTransaction(session):
            user = _ensure_user_exists(session, user_id)
            if is_premium:
                user.is_premium = 1
                user.subscription_end_date = (datetime.now() + timedelta(days=days_duration)).isoformat()
                user.role = "premium"
            else:
                user.is_premium = 0
                user.subscription_end_date = None
                user.role = "free"
            user.last_activity = _timestamp_now()

        return True
    except Exception as exc:
        logger.error(f"❌ Failed to set premium for {user_id}: {exc}")
        return False
    finally:
        session.close()


def extend_subscription(user_id: str, days: int = 30) -> bool:
    """Extend an existing subscription by the requested number of days."""
    session = get_session()
    if session is None:
        return False

    try:
        with _SessionTransaction(session):
            user = session.get(UserRecord, str(user_id))
            if user is None:
                return set_user_premium(user_id, True, days)

            current_end = _parse_datetime(user.subscription_end_date)
            if current_end is None:
                current_end = datetime.now()
            user.subscription_end_date = (current_end + timedelta(days=days)).isoformat()
            user.is_premium = 1
            user.role = "premium"
            user.last_activity = _timestamp_now()

        logger.info(f"⏱️ User {user_id} subscription extended to {user.subscription_end_date}")
        return True
    except Exception as exc:
        logger.error(f"❌ Failed to extend subscription for {user_id}: {exc}")
        return False
    finally:
        session.close()


def is_premium(user_id: str) -> bool:
    """Check if the user currently has an active premium subscription."""
    session = get_session()
    if session is None:
        return False

    try:
        user = session.get(UserRecord, str(user_id))
        if user is None or not user.is_premium:
            return False
        if not user.subscription_end_date:
            return True
        end_date = _parse_datetime(user.subscription_end_date)
        is_active = end_date is not None and end_date >= datetime.now()
        if is_active:
            logger.debug(f"✅ User {user_id} is PREMIUM (expires: {user.subscription_end_date})")
        return is_active
    except Exception as exc:
        logger.error(f"❌ Failed to check premium status for {user_id}: {exc}")
        return False
    finally:
        session.close()


def get_subscription_end_date(user_id: str) -> Optional[str]:
    """Return the formatted subscription end date for a user."""
    session = get_session()
    if session is None:
        return None

    try:
        user = session.get(UserRecord, str(user_id))
        if not user or not user.subscription_end_date:
            return None
        end_date = _parse_datetime(user.subscription_end_date)
        if end_date is None:
            return user.subscription_end_date
        return end_date.strftime("%d/%m/%Y")
    except Exception as exc:
        logger.error(f"❌ Failed to get subscription end date for {user_id}: {exc}")
        return None
    finally:
        session.close()


def get_all_users_with_status() -> List[Dict[str, Any]]:
    """Get all users with their premium status and subscription info."""
    session = get_session()
    if session is None:
        return []

    try:
        users = []
        for user in session.query(UserRecord).order_by(UserRecord.user_id).all():
            if user.is_premium and user.subscription_end_date:
                end_dt = _parse_datetime(user.subscription_end_date)
                if end_dt is not None and end_dt >= datetime.now():
                    status = "PREMIUM"
                    end_date_str = end_dt.strftime("%d/%m/%Y")
                else:
                    status = "EXPIRED"
                    end_date_str = end_dt.strftime("%d/%m/%Y") if end_dt else user.subscription_end_date
            elif user.is_premium:
                status = "PREMIUM"
                end_date_str = "Unlimited"
            else:
                status = "FREE"
                end_date_str = "-"

            users.append(
                {
                    "user_id": user.user_id,
                    "is_premium": bool(user.is_premium),
                    "status": status,
                    "subscription_end": end_date_str,
                    "created": user.created_at,
                    "role": user.role,
                }
            )
        return users
    except Exception as exc:
        logger.error(f"❌ Failed to get all users: {exc}")
        return []
    finally:
        session.close()


def get_user_info(user_id: str) -> Optional[Dict[str, Any]]:
    """Get detailed info about a specific user."""
    session = get_session()
    if session is None:
        return None

    try:
        user = session.get(UserRecord, str(user_id))
        if user is None:
            return None

        created_str = "Unknown"
        if user.created_at:
            created_dt = _parse_datetime(user.created_at)
            created_str = created_dt.strftime("%d/%m/%Y %H:%M") if created_dt else user.created_at

        if user.is_premium and user.subscription_end_date:
            end_dt = _parse_datetime(user.subscription_end_date)
            if end_dt and end_dt >= datetime.now():
                status = "PREMIUM"
                end_date_str = end_dt.strftime("%d/%m/%Y")
                days_left = (end_dt - datetime.now()).days
            else:
                status = "EXPIRED"
                end_date_str = end_dt.strftime("%d/%m/%Y") if end_dt else user.subscription_end_date
                days_left = -1
        elif user.is_premium:
            status = "PREMIUM"
            end_date_str = "Unlimited"
            days_left = -1
        else:
            status = "FREE"
            end_date_str = "-"
            days_left = 0

        return {
            "user_id": user.user_id,
            "is_premium": bool(user.is_premium),
            "status": status,
            "subscription_end": end_date_str,
            "days_left": days_left,
            "created": created_str,
            "role": user.role,
            "notes": user.notes or "",
        }
    except Exception as exc:
        logger.error(f"❌ Failed to get user info for {user_id}: {exc}")
        return None
    finally:
        session.close()


def get_free_vs_premium_count() -> Tuple[int, int]:
    """Get counts for free and active premium users."""
    session = get_session()
    if session is None:
        return 0, 0

    try:
        users = session.query(UserRecord).all()
        free_count = sum(1 for user in users if not user.is_premium)
        premium_count = sum(
            1
            for user in users
            if user.is_premium and (not user.subscription_end_date or _parse_datetime(user.subscription_end_date) is None or _parse_datetime(user.subscription_end_date) >= datetime.now())
        )
        return free_count, premium_count
    except Exception as exc:
        logger.error(f"❌ Failed to count users: {exc}")
        return 0, 0
    finally:
        session.close()


def get_expired_premium_users() -> List[str]:
    """Return IDs for users whose premium subscriptions have expired."""
    session = get_session()
    if session is None:
        return []

    try:
        expired = []
        for user in session.query(UserRecord).filter(UserRecord.is_premium == 1).all():
            if user.subscription_end_date:
                end_dt = _parse_datetime(user.subscription_end_date)
                if end_dt is not None and end_dt < datetime.now():
                    expired.append(user.user_id)
        return expired
    except Exception as exc:
        logger.error(f"❌ Failed to get expired users: {exc}")
        return []
    finally:
        session.close()


def reset_expired_subscriptions() -> int:
    """Reset expired premium users back to free status."""
    session = get_session()
    if session is None:
        return 0

    try:
        expired_ids = get_expired_premium_users()
        if not expired_ids:
            return 0

        with _SessionTransaction(session):
            for user_id in expired_ids:
                user = session.get(UserRecord, str(user_id))
                if user is not None:
                    user.is_premium = 0
                    user.role = "free"
                    user.subscription_end_date = None

        logger.info(f"♻️ Reset {len(expired_ids)} expired users back to free")
        return len(expired_ids)
    except Exception as exc:
        logger.error(f"❌ Failed to reset expired subscriptions: {exc}")
        return 0
    finally:
        session.close()


def _extract_user_ids_from_payload(payload: Any) -> List[str]:
    """Extract user IDs from common JSON payload shapes."""
    if isinstance(payload, dict):
        user_ids = []
        for key, value in payload.items():
            if isinstance(value, dict):
                user_id = value.get("user_id") or value.get("id")
                if user_id is not None:
                    user_ids.append(str(user_id))
            elif isinstance(value, list):
                user_ids.extend(_extract_user_ids_from_payload(value))
        if user_ids:
            return user_ids
        return [str(key) for key in payload.keys() if str(key) != ""]

    if isinstance(payload, list):
        user_ids = []
        for item in payload:
            if isinstance(item, dict):
                user_id = item.get("user_id") or item.get("id")
                if user_id is not None:
                    user_ids.append(str(user_id))
            elif isinstance(item, str):
                user_ids.append(item)
        return user_ids

    if isinstance(payload, str):
        return [payload]
    return []


def migrate_legacy_json_users() -> int:
    """Import any user identifiers from legacy JSON files into PostgreSQL."""
    if not DATABASE_URL:
        return 0

    migrated = set()
    legacy_files = [CONF_DIR / "pending_verifications.json", CONF_DIR / "approved_purchases.json"]

    for path in legacy_files:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for user_id in _extract_user_ids_from_payload(payload):
                if add_user_if_not_exists(user_id):
                    migrated.add(user_id)
        except Exception as exc:
            logger.warning(f"⚠️ Unable to import legacy JSON from {path}: {exc}")

    if migrated:
        logger.info(f"🧬 Migrated {len(migrated)} legacy users into PostgreSQL")
    return len(migrated)


# Initialize database on module load.
try:
    init_user_db()
except Exception as exc:
    logger.error(f"Failed to initialize user database: {exc}")
