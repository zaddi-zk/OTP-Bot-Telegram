# core/rate_limiter.py
"""
Advanced rate limiting for OTP-Bot-Telegram.
Implements token bucket with per‑user and per‑IP tracking,
dynamic cooling‑off periods, and temporary isolation bans.
"""
import time
import threading
import hashlib
from typing import Dict, Tuple, Optional, List, Union
from dataclasses import dataclass, field
from collections import defaultdict, deque
import logging

logger = logging.getLogger("HOTTBOIIHITZZ.rate_limiter")


@dataclass
class TokenBucket:
    """Token bucket for a single entity (user or IP)."""
    capacity: int = 10          # Maximum tokens
    refill_rate: float = 1.0    # Tokens per second
    tokens: float = 10.0        # Current tokens
    last_refill: float = field(default_factory=time.time)
    violations: int = 0         # Consecutive violations
    banned_until: float = 0.0   # 0 = not banned
    ban_start_time: float = 0.0

    def refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        """Consume `tokens` from the bucket. Returns True if allowed."""
        self.refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            # Reset violation count on success
            self.violations = 0
            return True
        else:
            self.violations += 1
            return False

    def is_banned(self) -> bool:
        """Check if this entity is currently banned."""
        if self.banned_until == 0:
            return False
        if time.time() < self.banned_until:
            return True
        # Ban expired
        self.banned_until = 0
        self.violations = 0
        return False

    def apply_ban(self, duration: float = 1800.0) -> None:
        """Apply a temporary ban for `duration` seconds (default 30 min)."""
        self.banned_until = time.time() + duration
        self.ban_start_time = time.time()
        self.tokens = 0


class RateLimiter:
    """
    Thread‑safe rate limiter using token bucket per identifier (user_id or IP).
    Supports dynamic ban durations based on violation frequency.
    """
    def __init__(
        self,
        default_capacity: int = 10,
        default_refill_rate: float = 1.0,
        max_violations_before_ban: int = 5,
        base_ban_duration: float = 300.0,          # 5 minutes
        max_ban_duration: float = 86400.0,         # 24 hours
        ban_escalation_factor: float = 2.0,
    ):
        self.default_capacity = default_capacity
        self.default_refill_rate = default_refill_rate
        self.max_violations_before_ban = max_violations_before_ban
        self.base_ban_duration = base_ban_duration
        self.max_ban_duration = max_ban_duration
        self.ban_escalation_factor = ban_escalation_factor

        # Storage: identifier -> TokenBucket
        self._buckets: Dict[str, TokenBucket] = defaultdict(lambda: TokenBucket(
            capacity=default_capacity,
            refill_rate=default_refill_rate,
        ))
        self._lock = threading.RLock()

        # Ban history for escalation (identifier -> list of ban timestamps)
        self._ban_history: Dict[str, List[float]] = defaultdict(list)

    def _get_identifier(self, user_id: Union[str, int], ip_address: str) -> str:
        """
        Generate a unique identifier combining user_id and IP.
        Uses SHA‑256 to avoid collisions.
        """
        raw = f"{user_id}:{ip_address}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _escalate_ban_duration(self, identifier: str) -> float:
        """
        Calculate ban duration based on past bans.
        Each subsequent ban doubles the duration (capped at max).
        """
        now = time.time()
        # Clean old history (older than 7 days)
        self._ban_history[identifier] = [
            ts for ts in self._ban_history[identifier] if now - ts < 604800
        ]
        ban_count = len(self._ban_history[identifier])
        if ban_count == 0:
            duration = self.base_ban_duration
        else:
            duration = min(
                self.base_ban_duration * (self.ban_escalation_factor ** ban_count),
                self.max_ban_duration
            )
        return duration

    def check_and_consume(
        self,
        user_id: Union[str, int],
        ip_address: str,
        tokens: int = 1,
    ) -> Tuple[bool, Optional[float]]:
        """
        Check if the request is allowed.
        Returns (allowed, ban_duration_remaining). If banned, ban_duration_remaining > 0.
        """
        identifier = self._get_identifier(user_id, ip_address)
        with self._lock:
            bucket = self._buckets[identifier]

            # Check ban status
            if bucket.is_banned():
                remaining = max(0.0, bucket.banned_until - time.time())
                return False, remaining

            # Consume tokens
            allowed = bucket.consume(tokens)

            if not allowed:
                # Violation: increment and check if ban threshold reached
                bucket.violations += 1
                if bucket.violations >= self.max_violations_before_ban:
                    # Apply escalating ban
                    duration = self._escalate_ban_duration(identifier)
                    bucket.apply_ban(duration)
                    self._ban_history[identifier].append(time.time())
                    logger.warning(
                        f"Rate limit ban applied to {identifier} for {duration:.0f}s "
                        f"(violations={bucket.violations})"
                    )
                    return False, duration
                # Not yet banned, but request denied
                return False, None
            else:
                # Success – reset violation counter (already reset in consume)
                return True, None

    def get_bucket_info(self, user_id: Union[str, int], ip_address: str) -> dict:
        """
        Return diagnostic info for a given identifier.
        Useful for status endpoints or admin panels.
        """
        identifier = self._get_identifier(user_id, ip_address)
        with self._lock:
            bucket = self._buckets[identifier]
            bucket.refill()  # Ensure tokens are up‑to‑date
            return {
                "tokens": bucket.tokens,
                "capacity": bucket.capacity,
                "refill_rate": bucket.refill_rate,
                "violations": bucket.violations,
                "banned_until": bucket.banned_until,
                "is_banned": bucket.is_banned(),
            }

    def reset(self, user_id: Union[str, int], ip_address: str) -> None:
        """Reset the bucket for a given identifier (e.g., after successful payment)."""
        identifier = self._get_identifier(user_id, ip_address)
        with self._lock:
            if identifier in self._buckets:
                del self._buckets[identifier]
            # Also clear ban history (optional)
            if identifier in self._ban_history:
                del self._ban_history[identifier]
            logger.info(f"Rate limiter reset for {identifier}")

    def cleanup_expired(self) -> None:
        """
        Periodically remove buckets that haven't been used in a while.
        This prevents memory bloat. Call from a background thread every hour.
        """
        now = time.time()
        with self._lock:
            to_delete = []
            for identifier, bucket in self._buckets.items():
                # Delete if last refill > 1 hour ago and no violations
                if now - bucket.last_refill > 3600 and bucket.violations == 0:
                    to_delete.append(identifier)
            for identifier in to_delete:
                del self._buckets[identifier]
                # Also clean ban history
                if identifier in self._ban_history:
                    del self._ban_history[identifier]
            if to_delete:
                logger.debug(f"Cleaned up {len(to_delete)} idle rate limiter buckets")


# Singleton instance
_global_limiter = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance (singleton)."""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = RateLimiter()
    return _global_limiter


# Decorator for Flask endpoints
def rate_limit(tokens: int = 1):
    """
    Decorator to apply rate limiting to Flask routes.
    Usage: @rate_limit(tokens=2)
    The decorated function must accept `user_id` and `ip_address` as arguments
    or have them available in `request`.
    """
    from functools import wraps
    from flask import request, jsonify

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Extract user_id from request (default to 0 if not authenticated)
            user_id = request.values.get("user_id") or request.args.get("user_id") or "0"
            # Fallback to Telegram ID if available
            if hasattr(request, "telegram_user_id"):
                user_id = request.telegram_user_id
            # Get real IP (respecting proxies)
            ip_address = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
            limiter = get_rate_limiter()
            allowed, ban_remaining = limiter.check_and_consume(user_id, ip_address, tokens)
            if not allowed:
                if ban_remaining:
                    return jsonify({
                        "error": "Rate limit exceeded. You are temporarily banned.",
                        "ban_remaining_seconds": int(ban_remaining)
                    }), 429
                else:
                    return jsonify({
                        "error": "Rate limit exceeded. Please slow down."
                    }), 429
            return f(*args, **kwargs)
        return wrapper
    return decorator


# Background cleanup thread (call from main)
def start_rate_limiter_cleanup(interval: int = 3600):
    """
    Start a background thread that periodically cleans up expired buckets.
    Should be called once at application startup.
    """
    def _cleanup_loop():
        limiter = get_rate_limiter()
        while True:
            time.sleep(interval)
            limiter.cleanup_expired()

    thread = threading.Thread(target=_cleanup_loop, daemon=True)
    thread.start()
    logger.info("Rate limiter cleanup thread started (interval %ds)", interval)
