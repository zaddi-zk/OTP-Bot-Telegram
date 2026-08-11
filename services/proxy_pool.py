"""
services/proxy_pool.py — Twilio Proxy number-pool manager for the OTP bot.

Why a Proxy Service and not Proxy "interactions"?
--------------------------------------------------
Twilio Proxy dials *between two phone participants* and does NOT support
injecting custom TwiML (``<Connect><Stream>`` -> Vapi). This bot needs Twilio
to dial the target and stream the call audio to Vapi for STT/LLM/TTS. So the
Proxy Service is used as the authoritative *number pool + reservation ledger*:

  * all purchased numbers are registered on a single Proxy Service,
  * each concurrent call acquires a free number, opens a short-lived
    "voice-only" Proxy session (lifecycle/audit) and marks the number reserved,
  * the existing ``client.calls.create(..., twiml=...)`` still dials, using the
    pooled number as the outbound caller id,
  * when the call ends the Proxy session is closed, the number is un-reserved
    and released back to the pool for the next user.

Thread safety
-------------
All mutable state is guarded by an ``RLock``. ``acquire`` picks the first number
that is not currently leased; ``release`` / ``release_by_sid`` are idempotent; a
background sweeper force-releases leases older than the configured TTL so a stuck
call (missing status webhook) can never permanently leak a number.
"""

import logging
import threading
import time
import uuid
from typing import Callable, Optional

from config import (
    PROXY_SERVICE_SID,
    PROXY_POOL,
    PROXY_POOL_ENABLED,
    PROXY_LEASE_TTL_SECONDS,
    PROXY_QUEUE_TTL_SECONDS,
)

logger = logging.getLogger("OTP-Bot.number-pool")

_QUEUE_WAIT_SECONDS = 1.0
_SWEEP_INTERVAL_SECONDS = 30.0


class AllLinesBusyError(Exception):
    """Raised when every number in the pool is currently in use."""

    def __init__(self, pool_size: int, in_use: int):
        self.pool_size = pool_size
        self.in_use = in_use
        super().__init__(f"All {pool_size} lines busy ({in_use}/{pool_size} in use)")


def _client():
    """Lazily fetch the shared Twilio client (avoids an import cycle)."""
    from services.twilio_service import get_twilio_client

    return get_twilio_client()


def should_use_pool(from_number: Optional[str]) -> bool:
    """True when ``from_number`` is the platform default (not a custom caller id).

    A user-provided custom Caller ID overrides the pool; only the default number
    is replaced with a pooled number when the proxy pool is enabled.
    """
    if not PROXY_POOL_ENABLED:
        return False
    if from_number in (None, ""):
        return True
    from config import TWILIO_PHONE_NUMBER, OUTBOUND_CALLER_ID

    return from_number in (TWILIO_PHONE_NUMBER, OUTBOUND_CALLER_ID)


class _Pending:
    """A queued call intent awaiting a free number."""

    __slots__ = ("key", "fn", "expires_at")

    def __init__(self, key, fn, expires_at):
        self.key = key
        self.fn = fn
        self.expires_at = expires_at


class NumberPool:
    """Thread-safe pool of Twilio numbers with acquire/release semantics."""

    def __init__(
        self,
        pool_numbers: Optional[list] = None,
        service_sid: Optional[str] = None,
        ttl: Optional[int] = None,
        start_sweeper: bool = False,
    ):
        self._service_sid = service_sid if service_sid is not None else PROXY_SERVICE_SID
        self._ttl = int(ttl if ttl is not None else PROXY_LEASE_TTL_SECONDS)
        self._fallback_numbers = [
            n for n in (pool_numbers if pool_numbers is not None else PROXY_POOL)
        ]
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._numbers: list = []
        self._proxy_phone_sid: dict = {}  # E.164 -> Proxy PhoneNumber sid
        self._leases: dict = {}  # number -> lease dict
        self._by_sid: dict = {}  # Twilio call sid -> number
        self._loaded = False
        self._queue: list = []
        self._queue_started = False
        self._sweeper_started = False
        if start_sweeper:
            self._ensure_sweeper()

    # ------------------------------------------------------------------ loading
    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        numbers: list = []
        pn_map: dict = {}
        if self._service_sid:
            try:
                client = _client()
                if client:
                    for pn in client.proxy.services(self._service_sid).phone_numbers.list():
                        if pn.phone_number:
                            numbers.append(str(pn.phone_number))
                            pn_map[str(pn.phone_number)] = str(pn.sid)
            except Exception as exc:
                logger.warning(
                    "[NUMBER_POOL] could not load numbers from Proxy Service: %s", exc
                )
        for num in self._fallback_numbers:
            if num and num not in numbers:
                numbers.append(num)
        self._numbers = numbers
        self._proxy_phone_sid = pn_map
        if not numbers:
            logger.warning(
                "[NUMBER_POOL] pool is empty (Proxy Service unreachable and no PROXY_POOL_NUMBERS)"
            )

    # -------------------------------------------------------------- lifecycle
    def acquire(self, user_id, chat_id=None) -> str:
        """Reserve a free number for a new call.

        Returns the E.164 number, or raises :class:`AllLinesBusyError` when the
        entire pool is in use.
        """
        self._load()
        with self._lock:
            self._prune_locked()
            for number in self._numbers:
                if number in self._leases:
                    continue
                lease = {
                    "number": number,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "sid": None,
                    "proxy_session_sid": None,
                    "acquired_at": time.time(),
                    "expires_at": time.time() + self._ttl,
                }
                self._leases[number] = lease
                self._open_proxy_session_locked(number, lease)
                logger.info(
                    "[NUMBER_POOL] acquired %s for user=%s chat=%s",
                    number, user_id, chat_id,
                )
                return number
        raise AllLinesBusyError(len(self._numbers), len(self._leases))

    def bind_sid(self, number: str, call_sid: str) -> None:
        """Associate a Twilio call SID with a leased number so it can be freed by SID."""
        with self._lock:
            if number in self._leases:
                self._leases[number]["sid"] = call_sid
                if call_sid:
                    self._by_sid[call_sid] = number

    def release(self, number: Optional[str] = None, sid: Optional[str] = None) -> bool:
        """Free a number and close its Proxy session. Idempotent."""
        if number is None and sid:
            with self._lock:
                number = self._by_sid.pop(sid, None)
        if not number:
            return False
        with self._lock:
            lease = self._leases.pop(number, None)
            if not lease:
                return False
            if sid:
                self._by_sid.pop(sid, None)
            else:
                call_sid = lease.get("sid")
                if call_sid and call_sid in self._by_sid:
                    self._by_sid.pop(call_sid, None)
            held = int(time.time() - lease["acquired_at"])
            self._close_proxy_session_locked(lease)
            logger.info("[NUMBER_POOL] released %s (held %ds)", number, held)
            self._condition.notify_all()
            return True

    def release_by_sid(self, call_sid: str) -> bool:
        """Free the number leased to a given Twilio call SID."""
        return self.release(sid=call_sid)

    def available_count(self) -> int:
        with self._lock:
            return len(self._numbers) - len(self._leases)

    def active_count(self) -> int:
        with self._lock:
            return len(self._leases)

    # --------------------------------------------------------- proxy bookkeeping
    def _open_proxy_session_locked(self, number, lease) -> None:
        if not self._service_sid:
            return
        try:
            client = _client()
            if not client:
                return
            session = client.proxy.services(self._service_sid).sessions.create(
                unique_name=f"call-{uuid.uuid4().hex[:12]}",
                ttl=int(self._ttl),
                mode="voice-only",
            )
            lease["proxy_session_sid"] = session.sid
        except Exception as exc:
            logger.warning("[NUMBER_POOL] proxy session create failed for %s: %s", number, exc)
        try:
            pn_sid = self._proxy_phone_sid.get(number)
            if pn_sid:
                _client().proxy.services(self._service_sid).phone_numbers(pn_sid).update(
                    is_reserved=True
                )
        except Exception as exc:
            logger.warning("[NUMBER_POOL] reserve failed for %s: %s", number, exc)

    def _close_proxy_session_locked(self, lease) -> None:
        if not self._service_sid:
            return
        try:
            client = _client()
            if not client:
                return
            psid = lease.get("proxy_session_sid")
            if psid:
                client.proxy.services(self._service_sid).sessions(psid).update(status="closed")
            pn_sid = self._proxy_phone_sid.get(lease.get("number"))
            if pn_sid:
                client.proxy.services(self._service_sid).phone_numbers(pn_sid).update(
                    is_reserved=False
                )
        except Exception as exc:
            logger.warning("[NUMBER_POOL] proxy close/cleanup failed: %s", exc)

    # ------------------------------------------------------------------ pruning
    def _prune_locked(self) -> None:
        now = time.time()
        for number, lease in list(self._leases.items()):
            if lease["expires_at"] <= now:
                self._leases.pop(number, None)
                call_sid = lease.get("sid")
                if call_sid and call_sid in self._by_sid:
                    self._by_sid.pop(call_sid, None)
                self._close_proxy_session_locked(lease)
                logger.info("[NUMBER_POOL] pruned %s reason=ttl-expired", number)
                self._condition.notify_all()

    def _ensure_sweeper(self) -> None:
        started = False
        with self._lock:
            if not self._sweeper_started:
                self._sweeper_started = True
                started = True
        if started:
            threading.Thread(
                target=self._sweep_loop, daemon=True, name="number-pool-sweeper"
            ).start()

    def _sweep_loop(self) -> None:
        while True:
            time.sleep(_SWEEP_INTERVAL_SECONDS)
            try:
                with self._lock:
                    self._prune_locked()
            except Exception:
                logger.exception("[NUMBER_POOL] sweep failed")

    # ------------------------------------------------------------------ queueing
    def submit(
        self,
        fn: Callable[[], None],
        key: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> bool:
        """Queue ``fn`` for automatic retry once a line frees up.

        ``fn`` should attempt to acquire/dial again; if the pool is still
        exhausted it may re-raise :class:`AllLinesBusyError` and the entry stays
        queued until its TTL. Returns True when the request was queued.
        """
        ttl = int(ttl if ttl is not None else PROXY_QUEUE_TTL_SECONDS)
        with self._condition:
            if key is not None:
                self._queue = [p for p in self._queue if p.key != key]
            elif self._queue:
                return False
            self._queue.append(_Pending(key, fn, time.time() + ttl))
            self._ensure_queue_worker_locked()
            self._condition.notify_all()
            return True

    def _ensure_queue_worker_locked(self) -> None:
        if self._queue_started:
            return
        self._queue_started = True
        threading.Thread(
            target=self._queue_loop, daemon=True, name="number-pool-queue"
        ).start()

    def _queue_loop(self) -> None:
        while True:
            item = None
            while True:
                with self._condition:
                    now = time.time()
                    self._queue = [p for p in self._queue if p.expires_at > now]
                    if not self._queue:
                        break
                    if self.available_count() >= 1:
                        item = self._queue.pop(0)
                        break
                    self._condition.wait(timeout=_QUEUE_WAIT_SECONDS)
                    now = time.time()
                    self._queue = [p for p in self._queue if p.expires_at > now]
                    if not self._queue:
                        break
                # give a released slot a beat before retrying
                time.sleep(0.2)
            if item is None:
                time.sleep(_QUEUE_WAIT_SECONDS)
                continue
            try:
                item.fn()
            except AllLinesBusyError:
                with self._condition:
                    if item.expires_at > time.time():
                        self._queue.insert(0, item)
                        self._condition.notify_all()
            except Exception:
                logger.exception("[NUMBER_POOL] queued call intent failed")


# Module-level singleton wired to config. Lazily contacts Twilio, never blocks import.
proxy_pool = NumberPool(start_sweeper=True)