"""
tests/test_proxy_pool.py — network-free tests for the Twilio Proxy number pool.

The pool is exercised with an injected fake Twilio client (via
``services.proxy_pool._client``) so no real Twilio traffic happens in CI.
"""

import time

import pytest

import services.proxy_pool as pool_module
from services.proxy_pool import AllLinesBusyError, NumberPool, should_use_pool

POOL = [
    "+19852848980",
    "+17623566007",
    "+14247881997",
    "+12405698072",
    "+19897877518",
    "+13073572084",
    "+19129147157",
]


class FakePhoneNumber:
    def __init__(self, sid, phone_number, is_reserved=False):
        self.sid = sid
        self.phone_number = phone_number
        self.is_reserved = is_reserved


class FakePhoneNumbers:
    def __init__(self, numbers):
        self._numbers = list(numbers)

    def list(self):
        return self._numbers

    def create(self, phone_number=None, sid=None, is_reserved=False):
        num = phone_number if phone_number is not None else sid
        pn = FakePhoneNumber(f"PN{100 + len(self._numbers) + 1}", num, is_reserved)
        self._numbers.append(pn)
        return pn

    def __call__(self, sid):
        for pn in self._numbers:
            if pn.sid == sid:
                return FakePhoneNumberContext(sid, self)
        raise KeyError(sid)


class FakePhoneNumberContext:
    def __init__(self, sid, parent):
        self.sid = sid
        self._parent = parent

    def update(self, is_reserved=None):
        for pn in self._parent._numbers:
            if pn.sid == self.sid:
                pn.is_reserved = is_reserved
        return self


class FakeSession:
    def __init__(self, sid, status="open"):
        self.sid = sid
        self.status = status


class FakeSessions:
    def __init__(self):
        self.sessions = []

    def create(self, **kwargs):
        sess = FakeSession(f"KS{len(self.sessions) + 1}")
        sess.unique_name = kwargs.get("unique_name")
        self.sessions.append(sess)
        return sess

    def __call__(self, sid):
        for s in self.sessions:
            if s.sid == sid:
                return FakeSessionContext(sid, self)
        raise KeyError(sid)


class FakeSessionContext:
    def __init__(self, sid, parent):
        self.sid = sid
        self._parent = parent

    def update(self, status=None):
        for s in self._parent.sessions:
            if s.sid == self.sid:
                s.status = status
        return self


class FakeProxy:
    def __init__(self, numbers):
        self.phone_numbers = FakePhoneNumbers(numbers)
        self.sessions = FakeSessions()

    def services(self, sid):
        return FakeServiceContext(sid, self)


class FakeServiceContext:
    def __init__(self, sid, proxy):
        self.sid = sid
        self.proxy = proxy

    @property
    def phone_numbers(self):
        return self.proxy.phone_numbers

    @property
    def sessions(self):
        return self.proxy.sessions


class FakeClient:
    def __init__(self, numbers):
        self.proxy = FakeProxy(numbers)


def make_pool(service_sid="KSxxxx", numbers=None, ttl=None):
    pool = NumberPool(
        pool_numbers=numbers or list(POOL),
        service_sid=service_sid,
        ttl=ttl,
        start_sweeper=False,
    )
    return pool


@pytest.fixture(autouse=True)
def _fake_client(monkeypatch):
    client = FakeClient(
        [FakePhoneNumber(f"PN{i + 1}", num, is_reserved=False) for i, num in enumerate(POOL)]
    )
    monkeypatch.setattr(pool_module, "_client", lambda: client)
    return client


# --------------------------------------------------------------------------- basic pool


def test_acquire_returns_a_pool_number():
    pool = make_pool()
    num = pool.acquire("u1", 111)
    assert num in POOL
    assert pool.active_count() == 1
    assert pool.available_count() == len(POOL) - 1


def test_acquire_uses_distinct_numbers_until_full():
    pool = make_pool()
    acquired = {pool.acquire(f"u{i}", 1000 + i) for i in range(len(POOL))}
    assert len(acquired) == len(POOL)


def test_busy_after_last_number_taken():
    pool = make_pool()
    for i in range(len(POOL)):
        pool.acquire(f"u{i}", 1000 + i)
    with pytest.raises(AllLinesBusyError) as exc_info:
        pool.acquire("u-extra", 9999)
    assert exc_info.value.pool_size == len(POOL)


def test_release_restores_availability():
    pool = make_pool()
    num = pool.acquire("u1", 111)
    assert pool.available_count() == len(POOL) - 1
    assert pool.release(number=num) is True
    assert pool.available_count() == len(POOL)
    assert pool.active_count() == 0


def test_release_by_sid_after_bind():
    pool = make_pool()
    num = pool.acquire("u1", 111)
    pool.bind_sid(num, "CA1234567890")
    assert pool.release_by_sid("CA1234567890") is True
    assert pool.available_count() == len(POOL)


def test_bind_then_release_by_sid_only_frees_the_bound_number():
    pool = make_pool()
    a = pool.acquire("u1", 111)
    b = pool.acquire("u2", 222)
    pool.bind_sid(a, "CA-AAA")
    pool.bind_sid(b, "CA-BBB")
    pool.release_by_sid("CA-AAA")
    assert pool.active_count() == 1
    # the freed number (a) is available again; b is still busy
    assert pool.available_count() == len(POOL) - 1
    pool.release_by_sid("CA-BBB")
    assert pool.available_count() == len(POOL)


def test_double_release_is_idempotent():
    pool = make_pool()
    num = pool.acquire("u1", 111)
    pool.bind_sid(num, "CA-123")
    assert pool.release(number=num) is True
    assert pool.release(number=num) is False
    assert pool.release_by_sid("CA-123") is False
    assert pool.available_count() == len(POOL)


def test_ttl_prune_expired_leases():
    pool = make_pool(ttl=1)
    num = pool.acquire("u1", 111)
    with pool._lock:
        pool._leases[num]["expires_at"] = time.time() - 10
    # a new acquire forces a prune and can reuse the expired number
    num2 = pool.acquire("u2", 222)
    assert num2 in POOL
    assert pool.active_count() == 1


def test_pool_load_merges_service_numbers_and_fallback():
    pool = NumberPool(
        pool_numbers=["+15551112222"], service_sid="KSxxxx", ttl=3600, start_sweeper=False
    )
    pool._numbers = []
    pool._loaded = False
    pool._load()
    # service numbers (FakeClient) + fallback that is not duplicated
    assert "+15551112222" in pool._numbers
    assert "+19852848980" in pool._numbers


# -------------------------------------------------------------------- queuing


def test_submit_queues_a_job_and_runs_it_when_a_line_frees():
    pool = make_pool()
    # fill the pool
    for i in range(len(POOL)):
        pool.acquire(f"u{i}", 1000 + i)
    calls = {"ran": 0}

    def job():
        calls["ran"] += 1
        # simulate the caller freeing up a line then dialing
        pool.release(_free_a_number(pool))

    assert pool.submit(job, key="job-1", ttl=30) is True
    # free one line -> worker should pick up the job promptly
    free_up(pool)
    deadline = time.time() + 5
    while calls["ran"] == 0 and time.time() < deadline:
        time.sleep(0.05)
    assert calls["ran"] >= 1


def _free_a_number(pool):
    with pool._lock:
        for number, lease in pool._leases.items():
            return number
    return None


def free_up(pool):
    with pool._lock:
        number = next(iter(pool._leases), None)
    if number:
        pool.release(number=number)


# ----------------------------------------------------------------- should_use_pool


def test_should_use_pool_disabled_master_switch(monkeypatch):
    monkeypatch.setattr(pool_module, "PROXY_POOL_ENABLED", False)
    assert should_use_pool(None) is False
    assert should_use_pool("+15550001111") is False


def test_should_use_pool_true_for_none_or_empty(monkeypatch):
    monkeypatch.setattr(pool_module, "PROXY_POOL_ENABLED", True)
    assert should_use_pool(None) is True
    assert should_use_pool("") is True


def test_should_use_pool_false_for_custom_caller_id(monkeypatch):
    monkeypatch.setattr(pool_module, "PROXY_POOL_ENABLED", True)
    assert should_use_pool("+15550001111") is False


def test_should_use_pool_true_for_platform_defaults(monkeypatch):
    monkeypatch.setattr(pool_module, "PROXY_POOL_ENABLED", True)
    monkeypatch.setattr("config.TWILIO_PHONE_NUMBER", "+19001112233")
    monkeypatch.setattr("config.OUTBOUND_CALLER_ID", "+19001112233")
    assert should_use_pool("+19001112233") is True