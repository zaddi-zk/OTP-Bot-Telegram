import json
from datetime import datetime, timedelta

import premium
import core.user_manager as user_manager
import core.auth as auth
import core.files as files


def test_redeem_writes_file_and_db(monkeypatch, tmp_path):
    # Redirect premium keys store and user conf dir to temporary path
    monkeypatch.setattr(premium, "PREMIUM_KEYS_PATH", tmp_path / "premium_keys.json")
    monkeypatch.setattr(files, "CONF_DIR", tmp_path)

    # Capture DB write
    calls = {}

    def fake_set_user_subscription_end_date(user_id, end_dt, role="premium"):
        calls["user_id"] = user_id
        calls["end_dt"] = end_dt
        calls["role"] = role
        return True

    monkeypatch.setattr(user_manager, "set_user_subscription_end_date", fake_set_user_subscription_end_date)
    monkeypatch.setattr(premium, "set_user_subscription_end_date", fake_set_user_subscription_end_date)
    # Ensure legacy file check does not think user already active
    monkeypatch.setattr(auth, "check_subscription", lambda u: "EXPIRED")

    # Create a key and redeem it
    key = premium.generate_premium_key(7, "tester")
    success, expiry_str = premium.redeem_premium_key("99999", key["token"])

    assert success is True
    # File should be written with DD/MM/YYYY
    subs_file = tmp_path / "99999" / "subs.txt"
    assert subs_file.exists()
    assert subs_file.read_text().strip() == expiry_str

    # Key store should be updated
    data = json.loads((tmp_path / "premium_keys.json").read_text())
    rec = next((k for k in data if k.get("token") == key["token"]), None)
    assert rec is not None
    assert rec.get("used") is True
    assert rec.get("used_by") == "99999"
    assert rec.get("redemption_expiry") == expiry_str

    # DB helper called with exact expiry datetime and scoped role
    assert calls.get("user_id") == "99999"
    assert calls.get("role") == "premium_key"
    assert calls.get("end_dt").strftime("%d/%m/%Y") == expiry_str


def test_redeem_marks_key_used_even_if_db_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(premium, "PREMIUM_KEYS_PATH", tmp_path / "premium_keys.json")
    monkeypatch.setattr(files, "CONF_DIR", tmp_path)

    # DB update will fail
    monkeypatch.setattr(user_manager, "set_user_subscription_end_date", lambda *a, **k: False)
    monkeypatch.setattr(auth, "check_subscription", lambda u: "EXPIRED")

    key = premium.generate_premium_key(3, "tester")
    ok, msg = premium.redeem_premium_key("55555", key["token"])
    assert ok is True

    # subs.txt written
    assert (tmp_path / "55555" / "subs.txt").exists()

    # key still marked used despite DB failure
    data = json.loads((tmp_path / "premium_keys.json").read_text())
    rec = next((k for k in data if k.get("token") == key["token"]), None)
    assert rec is not None and rec.get("used") is True


def test_check_subscription_prefers_db_and_syncs_file(monkeypatch, tmp_path):
    # Ensure conf dir is temporary
    monkeypatch.setattr(files, "CONF_DIR", tmp_path)

    # Prepare a different date in DB
    db_date = "01/01/2050"

    # DB reports premium active and provides end date
    monkeypatch.setattr(user_manager, "is_premium", lambda u: True)
    monkeypatch.setattr(user_manager, "get_subscription_end_date", lambda u: db_date)

    # Create an out-of-sync file with a different expiry
    user_dir = tmp_path / "77777"
    user_dir.mkdir()
    (user_dir / "subs.txt").write_text("02/02/2023")

    status = auth.check_subscription("77777")
    assert status == "ACTIVE"

    # File should be synced to DB expiry
    assert (user_dir / "subs.txt").read_text().strip() == db_date
