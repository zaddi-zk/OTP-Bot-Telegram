"""PostgreSQL-backed user database management for the OTP bot.

All user records are stored in Railway PostgreSQL via SQLAlchemy.
No SQLite or JSON-based user store is used.
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text


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

from config import CONF_DIR, DATABASE_URL, FREE_TRIAL_TOTAL

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
    # Server-side entitlement balances. NULL free_calls == never seeded yet.
    free_calls = Column(Integer, nullable=True)
    purchase_count = Column(Integer, nullable=False, default=0)
    loyalty_gift_count = Column(Integer, nullable=False, default=0)


class PremiumKeyRecord(Base):
    __tablename__ = "premium_keys"

    token = Column(String, primary_key=True)
    days = Column(Integer, nullable=False, default=0)
    free_calls = Column(Integer, nullable=True)
    created_by = Column(String, nullable=False, default="")
    created_at = Column(String, nullable=False)
    key_type = Column(String, nullable=False, default="premium")
    used = Column(Integer, nullable=False, default=0)
    used_by = Column(String, nullable=True)
    used_at = Column(String, nullable=True)
    claimed_by = Column(String, nullable=True)


_engine = None
_SessionLocal = None
_use_postgres: Optional[bool] = None
_last_pg_attempt: float = 0.0
PG_RETRY_INTERVAL: float = 60.0
_ENGINE_LOCK = Lock()


def _make_sqlite_fallback() -> Any:
    """Create (or recreate) the local SQLite engine used as an offline fallback."""
    global _engine, _SessionLocal, _use_postgres
    sqlite_path = (CONF_DIR / "users.sqlite3").resolve()
    sqlite_url = f"sqlite:///{sqlite_path}"
    engine = create_engine(sqlite_url, future=True)
    Base.metadata.create_all(engine)
    _ensure_schema(engine)
    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _use_postgres = False
    return engine


def _ensure_schema(engine: Any) -> None:
    """Add entitlement columns to an existing `users` table and create tables.

    `create_all` only creates missing tables — it never adds columns to a table
    that already exists. This migrates existing deployments (Postgres and the
    local SQLite fallback) by adding any missing columns with ALTER TABLE.
    """
    try:
        from sqlalchemy import inspect as sa_inspect

        if not sa_inspect(engine).has_table("users"):
            return
        existing = {c["name"] for c in sa_inspect(engine).get_columns("users")}
        additions = []
        if "free_calls" not in existing:
            additions.append("free_calls INTEGER")
        if "purchase_count" not in existing:
            additions.append("purchase_count INTEGER NOT NULL DEFAULT 0")
        if "loyalty_gift_count" not in existing:
            additions.append("loyalty_gift_count INTEGER NOT NULL DEFAULT 0")
        for ddl in additions:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {ddl}"))
        if additions:
            logger.info("✅ Added entitlement columns to users table: %s", ", ".join(additions))
    except Exception as exc:
        logger.warning("⚠️  Could not add entitlement columns to users table: %s", exc)


def _try_postgres() -> bool:
    """Attempt to connect to PostgreSQL. On success, swap the app to Postgres."""
    global _engine, _SessionLocal, _use_postgres, _last_pg_attempt
    if not DATABASE_URL:
        return False
    try:
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=5,
            max_overflow=10,
            future=True,
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        Base.metadata.create_all(engine)
        _ensure_schema(engine)
        _engine = engine
        _SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        _use_postgres = True
        logger.info("✅ PostgreSQL user database initialized")
        return True
    except Exception as exc:
        _last_pg_attempt = time.monotonic()
        logger.warning("PostgreSQL connection unavailable (%s); using SQLite fallback", exc)
        try:
            engine.dispose()
        except Exception:
            pass
        return False


def _build_engine():
    """Create the SQLAlchemy engine once and reuse it.

    Prefer PostgreSQL when a usable DATABASE_URL is available. If it is
    temporarily unreachable, fall back to a local SQLite store but keep
    retrying Postgres on a timer so the DB is adopted the moment it comes
    back (avoids permanently caching a dead fallback).
    """
    global _use_postgres, _last_pg_attempt
    with _ENGINE_LOCK:
        if _use_postgres is True:
            return _engine

        if _use_postgres is None:
            if DATABASE_URL and _try_postgres():
                return _engine
            _make_sqlite_fallback()
            logger.warning("DATABASE_URL not configured or unreachable; using local SQLite user store")
            return _engine

        # _use_postgres is False: periodically retry PostgreSQL.
        if DATABASE_URL and (time.monotonic() - _last_pg_attempt) >= PG_RETRY_INTERVAL:
            if _try_postgres():
                return _engine
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
        migrate_legacy_entitlements()
        if _use_postgres:
            logger.info("✅ PostgreSQL user database initialized")
        else:
            logger.warning("⚠️ Using local SQLite fallback (PostgreSQL unavailable) — data will NOT survive redeploys")
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


def set_user_subscription_end_date(user_id: str, end_dt: datetime, role: str = "premium") -> bool:
    """Set a user's subscription end date to an exact datetime (DB authoritative).

    This writes the exact expiry to the database (ISO format), marks the user premium
    and updates last activity. Use this when you have computed the canonical expiry
    (for example during key redemption) and want the database to match it exactly.
    """
    session = get_session()
    if session is None:
        return False

    try:
        with _SessionTransaction(session):
            user = _ensure_user_exists(session, user_id)
            user.subscription_end_date = end_dt.isoformat()
            user.is_premium = 1
            user.role = role or "premium"
            user.last_activity = _timestamp_now()

        logger.info(f"✅ Set subscription end for {user_id} to {user.subscription_end_date}")
        return True
    except Exception as exc:
        logger.error(f"❌ Failed to set subscription end date for {user_id}: {exc}")
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
        # Include time so UIs can show exact expiry (day + HH:MM)
        return end_date.strftime("%d/%m/%Y %H:%M")
    except Exception as exc:
        logger.error(f"❌ Failed to get subscription end date for {user_id}: {exc}")
        return None
    finally:
        session.close()


def get_subscription_end_datetime(user_id: str) -> Optional[datetime]:
    """Return the parsed subscription end datetime, or None."""
    session = get_session()
    if session is None:
        return None
    try:
        user = session.get(UserRecord, str(user_id))
        if not user or not user.subscription_end_date:
            return None
        return _parse_datetime(user.subscription_end_date)
    except Exception as exc:
        logger.error(f"❌ Failed to get subscription end datetime for {user_id}: {exc}")
        return None
    finally:
        session.close()


def is_full_premium(user_id: str) -> bool:
    """Return True only for full paid premium users (role == 'premium').

    This is useful to distinguish purchased premium (full access) from
    key-scoped grants which may set role to 'premium_key'.
    """
    session = get_session()
    if session is None:
        return False
    try:
        user = session.get(UserRecord, str(user_id))
        if user is None:
            return False
        return (user.role == "premium") and bool(user.is_premium)
    except Exception as exc:
        logger.error(f"❌ Failed to check full premium for {user_id}: {exc}")
        return False
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
                    end_date_str = end_dt.strftime("%d/%m/%Y %H:%M")
                else:
                    status = "EXPIRED"
                    end_date_str = end_dt.strftime("%d/%m/%Y %H:%M") if end_dt else user.subscription_end_date
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


def get_active_premium_users() -> List[Dict[str, Any]]:
    """Return all premium-flagged users with parsed subscription end datetimes.

    Used by the subscription maintenance worker to detect subscriptions that are
    about to expire or have just expired.
    """
    session = get_session()
    if session is None:
        return []
    try:
        results = []
        for user in session.query(UserRecord).filter(UserRecord.is_premium == 1).all():
            end_dt = _parse_datetime(user.subscription_end_date)
            results.append(
                {
                    "user_id": user.user_id,
                    "subscription_end": end_dt,
                    "is_active": end_dt is None or end_dt >= datetime.now(),
                }
            )
        return results
    except Exception as exc:
        logger.error(f"❌ Failed to get premium users for notifications: {exc}")
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
                end_date_str = end_dt.strftime("%d/%m/%Y %H:%M")
                days_left = (end_dt - datetime.now()).days
            else:
                status = "EXPIRED"
                end_date_str = end_dt.strftime("%d/%m/%Y %H:%M") if end_dt else user.subscription_end_date
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


def migrate_legacy_entitlements() -> int:
    """One-time import of existing entitlement state into the database.

    Only fills values that are still missing in the DB (never overwrites):
      - per-user free_calls.txt / free_calls_master.json balances
      - subs.txt expiries
      - conf/premium_keys.json
    This guarantees nothing already granted is lost while making Postgres the
    only authority going forward.
    """
    if not DATABASE_URL:
        return 0
    imported = 0
    try:
        from core.files import (
            _read_master_free_calls,
            user_conf_path,
            read_user_file,
        )
    except Exception as exc:
        logger.warning("⚠️  Skipping legacy entitlement import: %s", exc)
        return 0

    # 1) Per-user free-call balances from the master JSON + per-user files.
    try:
        master = _read_master_free_calls() or {}
        for uid, bal in master.items():
            if seed_free_calls_once(str(uid), int(bal)):
                imported += 1
    except Exception as exc:
        logger.warning("⚠️  Failed to import master free-call balances: %s", exc)

    # Per-user files only when no master entry exists for them, honoring the
    # file's actual balance (so exhausted users are not re-granted a trial).
    try:
        if CONF_DIR.exists():
            for entry in CONF_DIR.iterdir():
                if not (entry.is_dir() and entry.name.isdigit()):
                    continue
                uid = entry.name
                if uid in master:
                    continue
                try:
                    file_bal = int(read_user_file(uid, "free_calls.txt", "") or "")
                except (TypeError, ValueError):
                    file_bal = None
                if file_bal is not None:
                    if seed_free_calls_once(uid, file_bal):
                        imported += 1
                else:
                    if seed_free_calls_once(uid, FREE_TRIAL_TOTAL):
                        imported += 1
    except Exception as exc:
        logger.warning("⚠️  Failed to seed trial balances from legacy files: %s", exc)

    # 2) subs.txt expiries -> DB subscription end dates.
    try:
        if CONF_DIR.exists():
            for entry in CONF_DIR.iterdir():
                if not (entry.is_dir() and entry.name.isdigit()):
                    continue
                uid = entry.name
                sub = read_user_file(uid, "subs.txt", "")
                if not sub or sub == "LIFETIME":
                    continue
                user = None
                session = get_session()
                if session is None:
                    continue
                try:
                    user = session.get(UserRecord, str(uid))
                finally:
                    session.close()
                if user is not None and user.subscription_end_date:
                    continue
                parsed = _parse_datetime(sub)
                if parsed is None or parsed < datetime.now():
                    continue
                if set_user_subscription_end_date(str(uid), parsed, role="premium"):
                    imported += 1
    except Exception as exc:
        logger.warning("⚠️  Failed to import subs.txt expiries: %s", exc)

    # 3) Legacy premium keys JSON.
    try:
        keys_path = CONF_DIR / "premium_keys.json"
        if keys_path.exists():
            keys = json.loads(keys_path.read_text(encoding="utf-8"))
            existing = set()
            for key in list_premium_keys_db():
                existing.add(key["token"])
            for key in keys:
                token = str(key.get("token", "")).upper()
                if not token or token in existing:
                    continue
                rec = PremiumKeyRecord(
                    token=token,
                    days=int(key.get("days") or 0),
                    free_calls=int(key["free_calls"]) if key.get("free_calls") is not None else None,
                    created_by=str(key.get("created_by") or ""),
                    created_at=str(key.get("created_at") or datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
                    key_type=str(key.get("type") or key.get("key_type") or "premium"),
                    used=1 if key.get("used") else 0,
                    used_by=str(key.get("used_by")) if key.get("used_by") else None,
                    used_at=str(key.get("used_at")) if key.get("used_at") else None,
                    claimed_by=str(key.get("claimed_by")) if key.get("claimed_by") else None,
                )
                session = get_session()
                if session is None:
                    continue
                try:
                    with _SessionTransaction(session):
                        session.add(rec)
                    imported += 1
                finally:
                    session.close()
            logger.info("🔑 Imported legacy premium keys from premium_keys.json")
    except Exception as exc:
        logger.warning("⚠️  Failed to import legacy premium keys: %s", exc)

    if imported:
        logger.info(f"🧬 Imported {imported} legacy entitlement records into PostgreSQL")
    return imported


# ======================================================================
# ENTITLEMENTS — server-side source of truth
# ======================================================================
# All values live in the database only. User-editable files (free_calls.txt,
# subs.txt, premium_keys.json) are *never* consulted for grants. When the DB
# is unavailable the helpers fail closed (return safe defaults + log).

def _skip_or_mark(session: Session, user_id: str) -> None:
    _ensure_user_exists(session, user_id)


def _consult_db() -> bool:
    """Return True when the authoritative DB is usable.

    Fail-closed policy:
      - On a deployment (DATABASE_URL set), Postgres must actually be adopted,
        otherwise nothing is granted (a transient SQLite fallback would be
        wiped on the next redeploy and could silently reset trials).
      - In dev (no DATABASE_URL), the local SQLite engine is authoritative.
    """
    if DATABASE_URL:
        if _use_postgres is not True:
            _build_engine()  # retry adoption once
        if _use_postgres is not True:
            logger.error("⚠️  PostgreSQL unavailable — entitlement checks failing closed (granting nothing).")
            return False
    if get_session() is None:
        logger.error("⚠️  Entitlement check failed: database unavailable. Failing closed (granting nothing).")
        return False
    return True


# -- Free calls ---------------------------------------------------------
def get_free_calls_db(user_id: str) -> Optional[int]:
    """Return the user's seeded free-call balance, or None if never seeded."""
    if not _consult_db():
        return None
    session = get_session()
    if session is None:
        return None
    try:
        user = session.get(UserRecord, str(user_id))
        if user is None:
            return None
        return user.free_calls
    except Exception as exc:
        logger.error(f"❌ Failed to get free calls for {user_id}: {exc}")
        return None
    finally:
        session.close()


def set_free_calls_db(user_id: str, count: int) -> bool:
    """Write the user's free-call balance. Returns False if DB unavailable."""
    if not _consult_db():
        return False
    session = get_session()
    if session is None:
        return False
    try:
        with _SessionTransaction(session):
            user = _ensure_user_exists(session, user_id)
            user.free_calls = max(0, int(count))
        return True
    except Exception as exc:
        logger.error(f"❌ Failed to set free calls for {user_id}: {exc}")
        return False
    finally:
        session.close()


def seed_free_calls_once(user_id: str, total: int) -> bool:
    """Grant the free-trial allocation only when the account was never seeded.

    Keyed by user_id in the database, so deleting the bot, clearing chat
    history, or wiping local files can never re-harvest a trial.
    """
    if not _consult_db():
        return False
    session = get_session()
    if session is None:
        return False
    try:
        with _SessionTransaction(session):
            user = _ensure_user_exists(session, user_id)
            # Only skip seeding for users with an ACTIVE premium subscription.
            # A lapsed premium user (column=1 but end date passed) still gets
            # their trial, matching the previous /start behaviour.
            if user.is_premium:
                end_dt = _parse_datetime(user.subscription_end_date)
                if end_dt is None or end_dt >= datetime.now():
                    return False
            if user.free_calls is None:
                user.free_calls = max(0, int(total))
                return True
            return False
    except Exception as exc:
        logger.error(f"❌ Failed to seed free calls for {user_id}: {exc}")
        return False
    finally:
        session.close()


def decrement_free_call_db(user_id: str) -> int:
    """Atomically decrement the free-call balance. Returns the new balance,
    or -1 when the user has none left (or the DB is unavailable).

    Single UPDATE with a guard — safe under concurrency (no double-spend).
    """
    if not _consult_db():
        return -1
    session = get_session()
    if session is None:
        return -1
    is_pg = _use_postgres is True
    try:
        engine = _engine
        dialect = getattr(engine.dialect, "name", "") if engine is not None else ""
        with _SessionTransaction(session):
            if dialect == "postgresql":
                result = session.execute(
                    text(
                        "UPDATE users SET free_calls = free_calls - 1 "
                        "WHERE user_id = :u AND free_calls IS NOT NULL AND free_calls > 0 "
                        "RETURNING free_calls"
                    ),
                    {"u": str(user_id)},
                )
                row = result.first()
                return int(row[0]) if row else -1
            result = session.execute(
                text(
                    "UPDATE users SET free_calls = free_calls - 1 "
                    "WHERE user_id = :u AND free_calls IS NOT NULL AND free_calls > 0"
                ),
                {"u": str(user_id)},
            )
            if not result.rowcount:
                return -1
            user = session.get(UserRecord, str(user_id))
            return int(user.free_calls) if user is not None and user.free_calls is not None else -1
    except Exception as exc:
        logger.error(f"❌ Failed to decrement free call for {user_id}: {exc}")
        session.rollback()
        return -1
    finally:
        session.close()


# -- Purchase / loyalty counters ----------------------------------------
def get_purchase_count_db(user_id: str) -> int:
    if not _consult_db():
        return 0
    session = get_session()
    if session is None:
        return 0
    try:
        user = session.get(UserRecord, str(user_id))
        return int(user.purchase_count) if user is not None else 0
    except Exception as exc:
        logger.error(f"❌ Failed to get purchase count for {user_id}: {exc}")
        return 0
    finally:
        session.close()


def increment_purchase_count_db(user_id: str, amount: int = 1) -> int:
    if not _consult_db():
        return 0
    session = get_session()
    if session is None:
        return 0
    try:
        with _SessionTransaction(session):
            user = _ensure_user_exists(session, user_id)
            user.purchase_count = int(user.purchase_count or 0) + int(amount)
            return int(user.purchase_count)
    except Exception as exc:
        logger.error(f"❌ Failed to increment purchase count for {user_id}: {exc}")
        return 0
    finally:
        session.close()


def get_loyalty_gift_count_db(user_id: str) -> int:
    if not _consult_db():
        return 0
    session = get_session()
    if session is None:
        return 0
    try:
        user = session.get(UserRecord, str(user_id))
        return int(user.loyalty_gift_count) if user is not None else 0
    except Exception as exc:
        logger.error(f"❌ Failed to get loyalty gift count for {user_id}: {exc}")
        return 0
    finally:
        session.close()


def increment_loyalty_gift_count_db(user_id: str, amount: int = 1) -> int:
    if not _consult_db():
        return 0
    session = get_session()
    if session is None:
        return 0
    try:
        with _SessionTransaction(session):
            user = _ensure_user_exists(session, user_id)
            user.loyalty_gift_count = int(user.loyalty_gift_count or 0) + int(amount)
            return int(user.loyalty_gift_count)
    except Exception as exc:
        logger.error(f"❌ Failed to increment loyalty gift count for {user_id}: {exc}")
        return 0
    finally:
        session.close()


def reset_purchase_count_db(user_id: str) -> bool:
    if not _consult_db():
        return False
    session = get_session()
    if session is None:
        return False
    try:
        with _SessionTransaction(session):
            user = _ensure_user_exists(session, user_id)
            user.purchase_count = 0
        return True
    except Exception as exc:
        logger.error(f"❌ Failed to reset purchase count for {user_id}: {exc}")
        return False
    finally:
        session.close()


def set_purchase_count_db(user_id: str, count: int) -> bool:
    """Set an exact purchase count (legacy compatibility API)."""
    if not _consult_db():
        return False
    session = get_session()
    if session is None:
        return False
    try:
        with _SessionTransaction(session):
            user = _ensure_user_exists(session, user_id)
            user.purchase_count = max(0, int(count))
        return True
    except Exception as exc:
        logger.error(f"❌ Failed to set purchase count for {user_id}: {exc}")
        return False
    finally:
        session.close()


# -- Premium keys -------------------------------------------------------
def _key_row_to_dict(row: PremiumKeyRecord) -> dict:
    return {
        "token": row.token,
        "days": int(row.days or 0),
        "free_calls": int(row.free_calls) if row.free_calls is not None else None,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "key_type": row.key_type,
        "used": bool(row.used),
        "used_by": row.used_by,
        "used_at": row.used_at,
        "claimed_by": row.claimed_by,
    }


def create_premium_key_db(
    days: int,
    created_by: str,
    key_type: str = "premium",
    free_calls: Optional[int] = None,
    claimed_by: Optional[str] = None,
) -> Optional[dict]:
    """Generate and persist a new premium key in the database."""
    if not _consult_db():
        return None
    session = get_session()
    if session is None:
        return None
    token = "".join(__import__("secrets").choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(12))
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    try:
        with _SessionTransaction(session):
            row = PremiumKeyRecord(
                token=token,
                days=int(days or 0),
                free_calls=int(free_calls) if free_calls is not None else None,
                created_by=str(created_by or ""),
                created_at=now,
                key_type=key_type or "premium",
                used=0,
            )
            session.add(row)
        logger.info(f"🔑 Premium key generated by {created_by}: {token} ({days} days)")
        return _key_row_to_dict(row)
    except Exception as exc:
        logger.error(f"❌ Failed to create premium key: {exc}")
        session.rollback()
        return None
    finally:
        session.close()


def list_premium_keys_db() -> list:
    if not _consult_db():
        return []
    session = get_session()
    if session is None:
        return []
    try:
        rows = session.query(PremiumKeyRecord).all()
        return [_key_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.error(f"❌ Failed to list premium keys: {exc}")
        return []
    finally:
        session.close()


def get_unused_premium_keys_db() -> list:
    if not _consult_db():
        return []
    session = get_session()
    if session is None:
        return []
    try:
        rows = session.query(PremiumKeyRecord).filter(PremiumKeyRecord.used == 0).all()
        return [_key_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.error(f"❌ Failed to list unused premium keys: {exc}")
        return []
    finally:
        session.close()


def get_used_premium_keys_db() -> list:
    if not _consult_db():
        return []
    session = get_session()
    if session is None:
        return []
    try:
        rows = session.query(PremiumKeyRecord).filter(PremiumKeyRecord.used == 1).all()
        return [_key_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.error(f"❌ Failed to list used premium keys: {exc}")
        return []
    finally:
        session.close()


def find_premium_key_db(token: str) -> Optional[dict]:
    if not _consult_db():
        return None
    session = get_session()
    if session is None:
        return None
    try:
        row = session.get(PremiumKeyRecord, token.strip().upper())
        return _key_row_to_dict(row) if row is not None else None
    except Exception as exc:
        logger.error(f"❌ Failed to find premium key {token}: {exc}")
        return None
    finally:
        session.close()


def redeem_premium_key_db(user_id: str, token: str) -> tuple:
    """Atomically claim a key. Returns (ok: bool, err_or_key: str|dict).

    The UPDATE is guarded on `used = 0` and rowcount is checked, so two
    concurrent redemptions can never both succeed (no JSON-file race).
    """
    token = token.strip().upper()
    if not _consult_db():
        return False, "Database unavailable. Try again in a moment."
    session = get_session()
    if session is None:
        return False, "Database unavailable. Try again in a moment."
    engine = _engine
    dialect = getattr(engine.dialect, "name", "") if engine is not None else ""
    try:
        with _SessionTransaction(session):
            if dialect == "postgresql":
                result = session.execute(
                    text(
                        "UPDATE premium_keys SET used = 1, used_by = :u, used_at = :now "
                        "WHERE token = :t AND used = 0 RETURNING token"
                    ),
                    {"u": str(user_id), "now": datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "t": token},
                )
                claimed = result.first() is not None
            else:
                result = session.execute(
                    text(
                        "UPDATE premium_keys SET used = 1, used_by = :u, used_at = :now "
                        "WHERE token = :t AND used = 0"
                    ),
                    {"u": str(user_id), "now": datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "t": token},
                )
                claimed = bool(result.rowcount)
            if not claimed:
                existing = session.get(PremiumKeyRecord, token)
                if existing is not None:
                    return False, "This premium key has already been used."
                return False, "Premium key not found. Please check your code and try again."
            row = session.get(PremiumKeyRecord, token)
            logger.info(f"✅ KEY REDEEMED: {token} by {user_id}")
            return True, _key_row_to_dict(row)
    except Exception as exc:
        logger.error(f"❌ Failed to redeem premium key {token} for {user_id}: {exc}")
        session.rollback()
        return False, "Redeem failed. Please try again."
    finally:
        session.close()


def get_key_stats_db() -> dict:
    if not _consult_db():
        return {"total": 0, "used": 0, "unused": 0, "generated_today": 0}
    session = get_session()
    if session is None:
        return {"total": 0, "used": 0, "unused": 0, "generated_today": 0}
    try:
        rows = session.query(PremiumKeyRecord).all()
        total = len(rows)
        used = sum(1 for r in rows if r.used)
        today = datetime.now().strftime("%d/%m/%Y")
        generated_today = sum(1 for r in rows if r.created_at.startswith(today))
        return {"total": total, "used": used, "unused": total - used, "generated_today": generated_today}
    except Exception as exc:
        logger.error(f"❌ Failed to get key stats: {exc}")
        return {"total": 0, "used": 0, "unused": 0, "generated_today": 0}
    finally:
        session.close()


def purge_redeemed_keys_db() -> int:
    """Delete all used keys from the database. Returns number deleted."""
    if not _consult_db():
        return 0
    session = get_session()
    if session is None:
        return 0
    try:
        result = session.execute(text("DELETE FROM premium_keys WHERE used = 1"))
        session.commit()
        logger.info(f"🧹 Purged {result.rowcount} redeemed premium keys")
        return int(result.rowcount)
    except Exception as exc:
        logger.error(f"❌ Failed to purge redeemed keys: {exc}")
        session.rollback()
        return 0
    finally:
        session.close()


# Initialize database on module load.
try:
    init_user_db()
except Exception as exc:
    logger.error(f"Failed to initialize user database: {exc}")
