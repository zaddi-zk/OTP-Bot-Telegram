import json
from datetime import datetime, timedelta

import premium
import core.user_manager as user_manager
import core.auth as auth
import core.entitlements as entitlements


def _fake_key(**overrides):
    key = {
        "token": "TESTKEY123",
        "days": 7,
        "free_calls": None,
        "created_by": "tester",
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "key_type": "premium",
        "used": False,
        "used_by": None,
        "used_at": None,
        "claimed_by": None,
    }
    key.update(overrides)
    return key


def test_redeem_applies_subscription_and_marks_key_used(monkeypatch):
    calls = {}

    def fake_redeem(user_id, token):
        calls["claimed"] = (user_id, token)
        return True, _fake_key(days=7)

    def fake_set_end(user_id, end_dt, role="premium"):
        calls["user_id"] = user_id
        calls["end_dt"] = end_dt
        calls["role"] = role
        return True

    monkeypatch.setattr(user_manager, "redeem_premium_key_db", fake_redeem)
    monkeypatch.setattr(user_manager, "set_user_subscription_end_date", fake_set_end)
    monkeypatch.setattr(user_manager, "get_subscription_end_datetime", lambda uid: None)
    monkeypatch.setattr(user_manager, "get_purchase_count_db", lambda uid: 0)
    monkeypatch.setattr(user_manager, "reset_purchase_count_db", lambda uid: True)
    monkeypatch.setattr(user_manager, "increment_purchase_count_db", lambda uid, amount=1: 0)

    success, expiry_str = premium.redeem_premium_key("99999", "TESTKEY123")

    assert success is True
    assert calls.get("claimed") == ("99999", "TESTKEY123")
    assert calls.get("role") == "premium_key"
    # Expiry computed as now + 7 days
    parsed = datetime.strptime(expiry_str, "%d/%m/%Y")
    assert (parsed - datetime.now()).days >= 6


def test_redeem_rejects_used_key(monkeypatch):
    monkeypatch.setattr(
        user_manager,
        "redeem_premium_key_db",
        lambda uid, token: (False, "This premium key has already been used."),
    )
    ok, msg = premium.redeem_premium_key("55555", "ALREADYUSED")
    assert ok is False
    assert "already been used" in msg


def test_redeem_free_calls_key_grants_balance(monkeypatch):
    calls = {}

    def fake_redeem(user_id, token):
        return True, _fake_key(days=0, free_calls=25, key_type="FREE_CALLS")

    monkeypatch.setattr(user_manager, "redeem_premium_key_db", fake_redeem)
    monkeypatch.setattr(user_manager, "get_free_calls_db", lambda uid: 3)
    monkeypatch.setattr(user_manager, "set_free_calls_db", lambda uid, count: calls.update(count=count) or True)

    ok, msg = premium.redeem_premium_key("88888", "FREECALLS1")
    assert ok is True
    assert calls.get("count") == 28


def test_check_subscription_prefers_db(monkeypatch):
    # DB reports premium active.
    monkeypatch.setattr(user_manager, "is_premium", lambda u: True)
    monkeypatch.setattr(user_manager, "get_subscription_end_date", lambda u: "01/01/2050")

    status = auth.check_subscription("77777")
    assert status == "ACTIVE"

    # DB reports no premium -> EXPIRED (no file fallback grants).
    monkeypatch.setattr(user_manager, "is_premium", lambda u: False)
    status = auth.check_subscription("77777")
    assert status == "EXPIRED"


def test_entitlements_decrement_never_grants_free_calls_from_files(monkeypatch):
    # Even if a legacy free_calls.txt / master file existed, get_free_calls
    # must come from the DB only.
    monkeypatch.setattr(user_manager, "get_free_calls_db", lambda uid: None)
    assert entitlements.get_free_calls("12345") == 0