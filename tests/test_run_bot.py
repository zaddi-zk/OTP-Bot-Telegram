import run_bot
import bot


def test_should_start_polling_only_when_webhook_mode_is_disabled(monkeypatch):
    monkeypatch.setattr(bot, "USE_WEBHOOK", False)
    monkeypatch.setattr(bot, "_webhook_mode_active", False)
    assert bot.should_start_polling() is True

    monkeypatch.setattr(bot, "USE_WEBHOOK", True)
    monkeypatch.setattr(bot, "_webhook_mode_active", False)
    assert bot.should_start_polling() is False

    monkeypatch.setattr(bot, "USE_WEBHOOK", False)
    monkeypatch.setattr(bot, "_webhook_mode_active", True)
    assert bot.should_start_polling() is False


def test_ensure_env_key_uses_atomic_replace(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=1\n", encoding="utf-8")

    replaced = {}

    def fake_replace(src, dst):
        replaced["src"] = src
        replaced["dst"] = dst
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(run_bot.os, "replace", fake_replace)
    monkeypatch.setattr(run_bot, "ENV_PATH", env_path)

    run_bot.ensure_env_key("BAR", "2")

    assert replaced["dst"] == env_path
    assert env_path.read_text(encoding="utf-8") == "FOO=1\nBAR=2\n"
