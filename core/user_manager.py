"""
user_manager.py - User database management with premium status tracking.
Stores user information including premium status, subscription dates, and user roles.
Uses SQLite for persistence and compatibility with Railway deployment.
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("OTP-Bot.user_manager")

# Database path in conf directory
DB_PATH = Path("conf/users.db")


def init_user_db() -> None:
    """Initialize user database with schema if it doesn't exist."""
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                is_premium INTEGER DEFAULT 0,
                subscription_end_date TEXT,
                created_at TEXT,
                last_activity TEXT,
                role TEXT DEFAULT 'free',
                notes TEXT
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"✅ User database initialized at {DB_PATH}")
    except Exception as e:
        logger.error(f"❌ Failed to initialize user database: {e}")


def add_user_if_not_exists(user_id: str) -> bool:
    """Add user to database if they don't already exist."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if cursor.fetchone():
            conn.close()
            return False
        
        # Add new user
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO users (user_id, is_premium, created_at, last_activity, role)
            VALUES (?, 0, ?, ?, 'free')
        """, (user_id, now, now))
        
        conn.commit()
        conn.close()
        logger.info(f"➕ New user added: {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to add user {user_id}: {e}")
        return False


def update_last_activity(user_id: str) -> None:
    """Update user's last activity timestamp."""
    try:
        add_user_if_not_exists(user_id)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        cursor.execute(
            "UPDATE users SET last_activity = ? WHERE user_id = ?",
            (now, user_id)
        )
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Failed to update activity for {user_id}: {e}")


def set_user_premium(user_id: str, is_premium: bool = True, days_duration: int = 30) -> bool:
    """Set user as premium with optional subscription duration."""
    try:
        add_user_if_not_exists(user_id)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if is_premium:
            end_date = (datetime.now() + timedelta(days=days_duration)).isoformat()
            role = "premium"
            logger.info(f"✅ User {user_id} set to PREMIUM (expires: {end_date})")
        else:
            end_date = None
            role = "free"
            logger.info(f"❌ User {user_id} set to FREE")
        
        cursor.execute("""
            UPDATE users 
            SET is_premium = ?, subscription_end_date = ?, role = ?, last_activity = ?
            WHERE user_id = ?
        """, (1 if is_premium else 0, end_date, role, datetime.now().isoformat(), user_id))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ Failed to set premium for {user_id}: {e}")
        return False


def extend_subscription(user_id: str, days: int = 30) -> bool:
    """Extend existing subscription by specified days."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT subscription_end_date FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return set_user_premium(user_id, True, days)
        
        current_end = result[0]
        if current_end:
            try:
                end_dt = datetime.fromisoformat(current_end)
            except:
                end_dt = datetime.now()
        else:
            end_dt = datetime.now()
        
        new_end = (end_dt + timedelta(days=days)).isoformat()
        cursor.execute(
            "UPDATE users SET subscription_end_date = ? WHERE user_id = ?",
            (new_end, user_id)
        )
        
        conn.commit()
        conn.close()
        logger.info(f"⏱️ User {user_id} subscription extended to {new_end}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to extend subscription for {user_id}: {e}")
        return False


def is_premium(user_id: str) -> bool:
    """Check if user is currently premium (subscription not expired)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT is_premium, subscription_end_date FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            return False
        
        is_prem, end_date_str = result
        if not is_prem:
            return False
        
        if not end_date_str:
            return True  # Premium without expiry (admin, developer)
        
        try:
            end_date = datetime.fromisoformat(end_date_str)
            return end_date >= datetime.now()
        except:
            return False
    except Exception as e:
        logger.error(f"❌ Failed to check premium status for {user_id}: {e}")
        return False


def get_subscription_end_date(user_id: str) -> Optional[str]:
    """Get formatted subscription end date for user."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT subscription_end_date FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if not result or not result[0]:
            return None
        
        try:
            dt = datetime.fromisoformat(result[0])
            return dt.strftime("%d/%m/%Y")
        except:
            return result[0]
    except Exception as e:
        logger.error(f"❌ Failed to get subscription end date for {user_id}: {e}")
        return None


def get_all_users_with_status() -> List[Dict]:
    """Get all users with their premium status and subscription info."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT user_id, is_premium, subscription_end_date, created_at, role
            FROM users
            ORDER BY user_id
        """)
        
        users = []
        for row in cursor.fetchall():
            user_id, is_prem, end_date, created, role = row
            
            # Determine current status
            if is_prem and end_date:
                try:
                    dt = datetime.fromisoformat(end_date)
                    status = "PREMIUM" if dt >= datetime.now() else "EXPIRED"
                    end_date_str = dt.strftime("%d/%m/%Y")
                except:
                    status = "PREMIUM" if is_prem else "FREE"
                    end_date_str = end_date
            elif is_prem:
                status = "PREMIUM"
                end_date_str = "Unlimited"
            else:
                status = "FREE"
                end_date_str = "-"
            
            users.append({
                "user_id": user_id,
                "is_premium": bool(is_prem),
                "status": status,
                "subscription_end": end_date_str,
                "created": created,
                "role": role
            })
        
        conn.close()
        return users
    except Exception as e:
        logger.error(f"❌ Failed to get all users: {e}")
        return []


def get_user_info(user_id: str) -> Optional[Dict]:
    """Get detailed info about a specific user."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT user_id, is_premium, subscription_end_date, created_at, role, notes
            FROM users WHERE user_id = ?
        """, (user_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            return None
        
        user_id, is_prem, end_date, created, role, notes = result
        
        # Format dates
        if created:
            try:
                created_dt = datetime.fromisoformat(created)
                created_str = created_dt.strftime("%d/%m/%Y %H:%M")
            except:
                created_str = created
        else:
            created_str = "Unknown"
        
        if is_prem and end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
                status = "PREMIUM" if end_dt >= datetime.now() else "EXPIRED"
                end_date_str = end_dt.strftime("%d/%m/%Y")
                days_left = (end_dt - datetime.now()).days
            except:
                status = "UNKNOWN"
                end_date_str = end_date
                days_left = -1
        elif is_prem:
            status = "PREMIUM"
            end_date_str = "Unlimited"
            days_left = -1
        else:
            status = "FREE"
            end_date_str = "-"
            days_left = 0
        
        return {
            "user_id": user_id,
            "is_premium": bool(is_prem),
            "status": status,
            "subscription_end": end_date_str,
            "days_left": days_left,
            "created": created_str,
            "role": role,
            "notes": notes or ""
        }
    except Exception as e:
        logger.error(f"❌ Failed to get user info for {user_id}: {e}")
        return None


def get_free_vs_premium_count() -> Tuple[int, int]:
    """Get count of free and premium users."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Count free users
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 0")
        free_count = cursor.fetchone()[0]
        
        # Count premium users (active subscriptions)
        cursor.execute("""
            SELECT COUNT(*) FROM users 
            WHERE is_premium = 1 
            AND (subscription_end_date IS NULL 
                 OR datetime(subscription_end_date) >= datetime('now'))
        """)
        premium_count = cursor.fetchone()[0]
        
        conn.close()
        return free_count, premium_count
    except Exception as e:
        logger.error(f"❌ Failed to count users: {e}")
        return 0, 0


def get_expired_premium_users() -> List[str]:
    """Get list of users with expired premium subscriptions."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT user_id FROM users 
            WHERE is_premium = 1 
            AND subscription_end_date IS NOT NULL
            AND datetime(subscription_end_date) < datetime('now')
        """)
        
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        return users
    except Exception as e:
        logger.error(f"❌ Failed to get expired users: {e}")
        return []


def reset_expired_subscriptions() -> int:
    """Reset expired premium users back to free status."""
    try:
        expired = get_expired_premium_users()
        for user_id in expired:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET is_premium = 0, role = 'free' WHERE user_id = ?
            """, (user_id,))
            conn.commit()
            conn.close()
        
        if expired:
            logger.info(f"♻️ Reset {len(expired)} expired users back to free")
        return len(expired)
    except Exception as e:
        logger.error(f"❌ Failed to reset expired subscriptions: {e}")
        return 0


# Initialize database on module load
try:
    init_user_db()
except Exception as e:
    logger.error(f"Failed to initialize user database: {e}")
