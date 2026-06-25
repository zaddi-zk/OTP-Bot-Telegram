# core/rate_limiter_redis.py
"""
Redis-based rate limiter for OTP-Bot-Telegram.
Replaces in-memory token bucket with distributed Redis storage.
Supports per-user and per-IP tracking with dynamic ban escalation.
Requires Redis server (redis://localhost:6379 by default).
"""
import time
import hashlib
import logging
from typing import Tuple, Optional, Dict, Any

import redis

from config import REDIS_URL, RATE_LIMIT_CAPACITY, RATE_LIMIT_REFILL_RATE

logger = logging.getLogger("OTP-Bot.rate_limiter_redis")

# ======================================================================
# Redis rate limiter
# ======================================================================
class RedisRateLimiter:
    """
    Distributed rate limiter using Redis.
    Implements token bucket algorithm with Lua scripting for atomic operations.
    Supports per-user and per-IP tracking with ban escalation.
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        prefix: str = "rate:",
        default_capacity: int = 10,
        default_refill_rate: float = 1.0,
        max_violations_before_ban: int = 5,
        base_ban_duration: float = 300.0,
        max_ban_duration: float = 86400.0,
        ban_escalation_factor: float = 2.0,
    ):
        self.redis_url = redis_url
        self.prefix = prefix
        self.default_capacity = default_capacity
        self.default_refill_rate = default_refill_rate
        self.max_violations_before_ban = max_violations_before_ban
        self.base_ban_duration = base_ban_duration
        self.max_ban_duration = max_ban_duration
        self.ban_escalation_factor = ban_escalation_factor
        
        # Connect to Redis
        try:
            self.redis = redis.from_url(redis_url, decode_responses=True)
            self.redis.ping()
            logger.info(f"Connected to Redis at {redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def _key(self, identifier: str) -> str:
        """Generate Redis key for a given identifier."""
        return f"{self.prefix}{identifier}"

    def _ban_key(self, identifier: str) -> str:
        """Generate Redis key for ban history."""
        return f"{self.prefix}{identifier}:ban"

    def _get_identifier(self, user_id: str, ip_address: str) -> str:
        """Generate a unique identifier combining user_id and IP address."""
        raw = f"{user_id}:{ip_address}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _escalate_ban_duration(self, identifier: str) -> float:
        """
        Calculate ban duration based on past ban history.
        Each subsequent ban doubles the duration, capped at maximum.
        """
        ban_key = self._ban_key(identifier)
        now = time.time()
        # Clean history older than 7 days
        self.redis.zremrangebyscore(ban_key, 0, now - 604800)
        ban_count = self.redis.zcard(ban_key)
        if ban_count == 0:
            return self.base_ban_duration
        duration = min(
            self.base_ban_duration * (self.ban_escalation_factor ** ban_count),
            self.max_ban_duration
        )
        return duration

    def check_and_consume(
        self,
        user_id: str,
        ip_address: str,
        tokens: int = 1,
    ) -> Tuple[bool, Optional[float]]:
        """
        Check if request is allowed and consume tokens.
        
        Returns:
            (allowed, ban_remaining): ban_remaining is None if not banned,
            otherwise seconds remaining.
        """
        identifier = self._get_identifier(user_id, ip_address)
        key = self._key(identifier)
        ban_key = self._ban_key(identifier)
        now = time.time()
        
        # Lua script for atomic token bucket with ban check
        script = """
        -- Check if banned
        local ban_until = redis.call('get', KEYS[2])
        if ban_until and tonumber(ban_until) > tonumber(ARGV[4]) then
            return {-1, tonumber(ban_until) - tonumber(ARGV[4])}
        end
        
        -- Get token bucket state
        local tokens = redis.call('get', KEYS[1])
        local last_refill = redis.call('get', KEYS[1]..':last')
        local capacity = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local now = tonumber(ARGV[4])
        local consume = tonumber(ARGV[3])
        
        if not tokens then
            tokens = capacity
        else
            tokens = tonumber(tokens)
        end
        if not last_refill then
            last_refill = now
        else
            last_refill = tonumber(last_refill)
        end
        
        -- Refill tokens
        local elapsed = now - last_refill
        tokens = math.min(capacity, tokens + elapsed * refill_rate)
        
        if tokens >= consume then
            tokens = tokens - consume
            redis.call('set', KEYS[1], tokens)
            redis.call('set', KEYS[1]..':last', now)
            redis.call('expire', KEYS[1], 3600)
            return {1, 0}
        else
            -- Violation: increment counter
            local violations = redis.call('incr', KEYS[1]..':violations')
            redis.call('expire', KEYS[1]..':violations', 3600)
            return {0, violations}
        end
        """
        
        try:
            result = self.redis.eval(
                script,
                2,
                key,
                ban_key,
                self.default_capacity,
                self.default_refill_rate,
                tokens,
                now
            )
        except redis.RedisError as e:
            logger.error(f"Redis Lua script error: {e}")
            return False, None
        
        if result[0] == 1:
            # Allowed
            return True, None
        elif result[0] == -1:
            # Banned
            return False, result[1]
        else:
            # Violation
            violations = result[1]
            if violations >= self.max_violations_before_ban:
                # Apply ban
                duration = self._escalate_ban_duration(identifier)
                ban_until = now + duration
                self.redis.set(ban_key, ban_until)
                self.redis.expire(ban_key, int(duration) + 1)
                # Record ban in history
                self.redis.zadd(self._ban_key(identifier), {now: now})
                self.redis.expire(self._ban_key(identifier), 604800)  # 7 days
                logger.warning(
                    f"Rate limit ban applied to {identifier} for {duration:.0f}s "
                    f"(violations={violations})"
                )
                return False, duration
            return False, None

    def get_bucket_info(self, user_id: str, ip_address: str) -> dict:
        """
        Get diagnostic information for a given identifier.
        """
        identifier = self._get_identifier(user_id, ip_address)
        key = self._key(identifier)
        ban_key = self._ban_key(identifier)
        ban_until = self.redis.get(ban_key)
        tokens = self.redis.get(key)
        violations = self.redis.get(f"{key}:violations") or "0"
        last_refill = self.redis.get(f"{key}:last") or "0"
        
        return {
            "tokens": float(tokens) if tokens else self.default_capacity,
            "capacity": self.default_capacity,
            "refill_rate": self.default_refill_rate,
            "violations": int(violations),
            "banned_until": float(ban_until) if ban_until else 0,
            "is_banned": ban_until is not None and float(ban_until) > time.time(),
            "last_refill": float(last_refill),
        }

    def reset(self, user_id: str, ip_address: str) -> None:
        """
        Reset rate limiter state for a given identifier.
        """
        identifier = self._get_identifier(user_id, ip_address)
        key = self._key(identifier)
        ban_key = self._ban_key(identifier)
        self.redis.delete(key, f"{key}:last", f"{key}:violations", ban_key)
        logger.info(f"Rate limiter reset for {identifier}")

    def cleanup_expired(self) -> None:
        """
        Cleanup expired keys (Redis handles TTL automatically, this is a no-op).
        """
        pass

# ======================================================================
# Redis session store for call state
# ======================================================================
class RedisSessionStore:
    """
    Distributed session store using Redis.
    Stores call state, user data, and temporary metadata.
    All entries have TTL for automatic cleanup.
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        prefix: str = "session:",
        default_ttl: int = 86400,  # 24 hours
    ):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.prefix = prefix
        self.default_ttl = default_ttl

    def _key(self, session_id: str) -> str:
        return f"{self.prefix}{session_id}"

    def set(self, session_id: str, data: Dict[str, Any], ttl: int = None) -> None:
        """
        Store session data.
        
        Args:
            session_id: Unique session identifier
            data: Dictionary of data to store
            ttl: Time-to-live in seconds (default: 24 hours)
        """
        key = self._key(session_id)
        import json
        self.redis.setex(key, ttl or self.default_ttl, json.dumps(data))

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve session data.
        
        Args:
            session_id: Unique session identifier
        
        Returns:
            Dictionary of stored data, or None if not found
        """
        key = self._key(session_id)
        data = self.redis.get(key)
        if not data:
            return None
        import json
        return json.loads(data)

    def delete(self, session_id: str) -> None:
        """
        Delete session data.
        
        Args:
            session_id: Unique session identifier
        """
        key = self._key(session_id)
        self.redis.delete(key)

    def update(self, session_id: str, data: Dict[str, Any], ttl: int = None) -> None:
        """
        Update session data (merge with existing).
        
        Args:
            session_id: Unique session identifier
            data: Dictionary of data to merge
            ttl: Time-to-live in seconds (default: 24 hours)
        """
        existing = self.get(session_id) or {}
        existing.update(data)
        self.set(session_id, existing, ttl)

    def set_call_sid(self, user_id: str, call_sid: str) -> None:
        """
        Store call SID for a user.
        
        Args:
            user_id: User ID
            call_sid: Twilio call SID
        """
        self.set(f"call:{user_id}", {"sid": call_sid}, ttl=7200)  # 2 hours

    def get_call_sid(self, user_id: str) -> Optional[str]:
        """
        Get call SID for a user.
        
        Args:
            user_id: User ID
        
        Returns:
            Call SID or None if not found
        """
        data = self.get(f"call:{user_id}")
        return data.get("sid") if data else None

    def set_user_state(self, user_id: str, state: str) -> None:
        """
        Store user state (replaces file-based state).
        
        Args:
            user_id: User ID
            state: State string
        """
        self.set(f"state:{user_id}", {"state": state}, ttl=3600)  # 1 hour

    def get_user_state(self, user_id: str) -> Optional[str]:
        """
        Get user state.
        
        Args:
            user_id: User ID
        
        Returns:
            State string or None if not found
        """
        data = self.get(f"state:{user_id}")
        return data.get("state") if data else None

    def clear_user_state(self, user_id: str) -> None:
        """
        Clear user state.
        
        Args:
            user_id: User ID
        """
        self.delete(f"state:{user_id}")

# ======================================================================
# Singleton instances
# ======================================================================
_redis_limiter = None
_redis_session = None

def get_redis_rate_limiter() -> RedisRateLimiter:
    """Get or create the Redis rate limiter singleton."""
    global _redis_limiter
    if _redis_limiter is None:
        from config import REDIS_URL, RATE_LIMIT_CAPACITY, RATE_LIMIT_REFILL_RATE
        _redis_limiter = RedisRateLimiter(
            redis_url=REDIS_URL,
            default_capacity=RATE_LIMIT_CAPACITY,
            default_refill_rate=RATE_LIMIT_REFILL_RATE,
            max_violations_before_ban=RATE_LIMIT_MAX_VIOLATIONS,
            base_ban_duration=RATE_LIMIT_BASE_BAN_DURATION,
            max_ban_duration=RATE_LIMIT_MAX_BAN_DURATION,
            ban_escalation_factor=RATE_LIMIT_BAN_ESCALATION_FACTOR,
        )
    return _redis_limiter

def get_redis_session() -> RedisSessionStore:
    """Get or create the Redis session store singleton."""
    global _redis_session
    if _redis_session is None:
        from config import REDIS_URL
        _redis_session = RedisSessionStore(redis_url=REDIS_URL)
    return _redis_session

# ======================================================================
# Compatibility layer (to work with existing code)
# ======================================================================
class CompatRateLimiter:
    """
    Compatibility wrapper for existing code that expects the old RateLimiter API.
    """
    def __init__(self):
        self._redis = get_redis_rate_limiter()

    def check_and_consume(self, user_id: str, ip_address: str, tokens: int = 1):
        return self._redis.check_and_consume(user_id, ip_address, tokens)

    def get_bucket_info(self, user_id: str, ip_address: str):
        return self._redis.get_bucket_info(user_id, ip_address)

    def reset(self, user_id: str, ip_address: str):
        self._redis.reset(user_id, ip_address)

    def cleanup_expired(self):
        self._redis.cleanup_expired()

# ======================================================================
# Example usage (comment out when importing)
# ======================================================================
if __name__ == "__main__":
    # Test rate limiter
    limiter = get_redis_rate_limiter()
    for i in range(15):
        allowed, banned = limiter.check_and_consume("test_user", "127.0.0.1")
        print(f"Request {i+1}: allowed={allowed}, banned={banned}")
        if not allowed:
            print(f"Ban remaining: {banned}")
            break
    
    # Test session store
    session = get_redis_session()
    session.set_call_sid("test_user", "CA123456789")
    sid = session.get_call_sid("test_user")
    print(f"Retrieved SID: {sid}")