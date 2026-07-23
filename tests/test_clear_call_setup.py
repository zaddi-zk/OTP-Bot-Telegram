import shutil
from pathlib import Path

import pytest


def write_setup_files(base: Path):
    base.mkdir(parents=True, exist_ok=True)
    files = [
        "Name.txt",
        "Company Name.txt",
        "From Name.txt",
        "phonenum.txt",
        "Caller ID.txt",
        "Language.txt",
        "Delivery.txt",
        "Digits.txt",
        "CodeLength.txt",
        "Voice.txt",
        "VoiceName.txt",
        "emotion.txt",
        "call_mode_label.txt",
    ]
    for f in files:
        (base / f).write_text("test")


def test_clear_on_initiate_and_cleanup(monkeypatch, tmp_path):
    # Arrange
    repo_root = Path(".")
    conf = repo_root / "conf"
    test_user = "test_clear_user"
    user_dir = conf / test_user
    # ensure clean slate
    if user_dir.exists():
        shutil.rmtree(user_dir)
    write_setup_files(user_dir)

    # Import bot module after creating the conf dir
    import bot
    # Monkeypatch the async executor and twilio call to be synchronous and deterministic

    monkeypatch.setattr(bot, "run_callback_async", lambda f, *a, **k: f(*a, **k))

    # Ensure premium check and telegram sends do not block the test
    monkeypatch.setattr(bot, "is_premium_user", lambda uid: True)
    class DummyBot:
        def send_message(self, *a, **k):
            class M:
                message_id = None
            return M()
        def answer_callback_query(self, *a, **k):
            return None
        def edit_message_text(self, *a, **k):
            return None
    monkeypatch.setattr(bot, "bot", DummyBot())

    # Replace make_call_and_store_async to return a concrete SID string
    import services.twilio_service as ts

    class DummyFuture:
        def result(self, timeout=None):
            return "FAKE-SID-123"
        def add_done_callback(self, cb):
            try:
                cb(self)
            except Exception:
                pass

    monkeypatch.setattr(ts, "make_call_and_store_async", lambda **kw: DummyFuture())

    # Directly test the helper to ensure it clears the files
    bot.clear_user_call_setup(test_user)
    for fn in [
        "Name.txt",
        "phonenum.txt",
        "Caller ID.txt",
        "call_mode_label.txt",
    ]:
        assert not (user_dir / fn).exists(), f"{fn} should be removed by clear_user_call_setup"

    # Recreate files and test cleanup_call_session path
    write_setup_files(user_dir)
    # Register a session and then cleanup
    bot.register_call_session("SID-XYZ", test_user, chat_id=12345, endpoint="/test", mode_label="Normal Call")
    bot.cleanup_call_session("SID-XYZ")
    for fn in ["Name.txt", "phonenum.txt", "Caller ID.txt"]:
        assert not (user_dir / fn).exists(), f"{fn} should be removed after cleanup_call_session"

    # Teardown
    if user_dir.exists():
        shutil.rmtree(user_dir)
