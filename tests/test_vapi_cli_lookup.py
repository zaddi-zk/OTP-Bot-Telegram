import importlib
import json


def test_vapi_cli_lookup_requires_token():
    import bot as bot_mod

    client = bot_mod.app.test_client()
    resp = client.get("/vapi/cli/15551234567")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "unauthorized"


def test_vapi_cli_lookup_rejects_wrong_token(monkeypatch):
    import bot as bot_mod
    import config

    monkeypatch.setattr(config, "ASTERISK_CLI_API_TOKEN", "secret-tok")
    client = bot_mod.app.test_client()
    resp = client.get("/vapi/cli/15551234567", headers={"X-CLI-Token": "wrong"})
    assert resp.status_code == 401


def test_vapi_cli_lookup_not_found(monkeypatch, tmp_path):
    import bot as bot_mod
    import config

    monkeypatch.setattr(config, "ASTERISK_CLI_API_TOKEN", "secret-tok")
    monkeypatch.setattr(config, "ASTERISK_CLI_DIR", str(tmp_path))
    client = bot_mod.app.test_client()
    resp = client.get("/vapi/cli/15551234567", headers={"X-CLI-Token": "secret-tok"})
    assert resp.status_code == 404


def test_vapi_cli_lookup_returns_json(monkeypatch, tmp_path):
    import bot as bot_mod
    import config

    monkeypatch.setattr(config, "ASTERISK_CLI_API_TOKEN", "secret-tok")
    monkeypatch.setattr(config, "ASTERISK_CLI_DIR", str(tmp_path))
    (tmp_path / "15551234567.json").write_text(
        json.dumps({"caller_id": "+15559998877", "display_name": "Acme Bank"}),
        encoding="utf-8",
    )
    client = bot_mod.app.test_client()
    resp = client.get("/vapi/cli/15551234567", headers={"X-CLI-Token": "secret-tok"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["caller_id"] == "+15559998877"
    assert body["display_name"] == "Acme Bank"


def test_vapi_cli_lookup_plus_stripped(monkeypatch, tmp_path):
    import bot as bot_mod
    import config

    monkeypatch.setattr(config, "ASTERISK_CLI_API_TOKEN", "secret-tok")
    monkeypatch.setattr(config, "ASTERISK_CLI_DIR", str(tmp_path))
    (tmp_path / "15551234567.json").write_text(
        json.dumps({"caller_id": "+15559998877", "display_name": "Acme Bank"}),
        encoding="utf-8",
    )
    client = bot_mod.app.test_client()
    resp = client.get("/vapi/cli/+15551234567", headers={"X-CLI-Token": "secret-tok"})
    assert resp.status_code == 200


def test_fetch_cli_via_http_ok(monkeypatch):
    from unittest import mock

    rc = importlib.import_module("asterisk.read_cli")
    monkeypatch.setattr(rc, "ASTERISK_CLI_PUBLIC_URL", "https://bot.example.com")
    monkeypatch.setattr(rc, "ASTERISK_CLI_API_TOKEN", "tok")

    fake = mock.MagicMock()
    fake.status = 200
    fake.read.return_value = b'{"caller_id":"+15551234567","display_name":"Acme"}'
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=5: fake)

    assert rc._fetch_cli_via_http("15551234567") == ("+15551234567", "Acme")


def test_fetch_cli_via_http_404_returns_none(monkeypatch):
    from unittest import mock

    rc = importlib.import_module("asterisk.read_cli")
    monkeypatch.setattr(rc, "ASTERISK_CLI_PUBLIC_URL", "https://bot.example.com")
    monkeypatch.setattr(rc, "ASTERISK_CLI_API_TOKEN", "tok")

    fake = mock.MagicMock()
    fake.status = 404
    fake.read.return_value = b'{"error":"not found"}'
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=5: fake)

    assert rc._fetch_cli_via_http("15551234567") is None


def test_fetch_cli_via_http_no_config_returns_none(monkeypatch):
    rc = importlib.import_module("asterisk.read_cli")
    monkeypatch.setattr(rc, "ASTERISK_CLI_PUBLIC_URL", "")
    monkeypatch.setattr(rc, "ASTERISK_CLI_API_TOKEN", "")
    assert rc._fetch_cli_via_http("15551234567") is None


def test_read_cli_file_fallback(tmp_path, monkeypatch):
    rc = importlib.import_module("asterisk.read_cli")
    (tmp_path / "15551234567.json").write_text(
        json.dumps({"caller_id": "+15559998877", "display_name": "Bank"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(rc, "ASTERISK_CLI_DIR", str(tmp_path))
    assert rc._read_cli_file("+15551234567", "15551234567") == ("+15559998877", "Bank")


def test_read_cli_file_missing_returns_none(monkeypatch, tmp_path):
    rc = importlib.import_module("asterisk.read_cli")
    monkeypatch.setattr(rc, "ASTERISK_CLI_DIR", str(tmp_path))
    assert rc._read_cli_file("+15551234567", "15551234567") is None