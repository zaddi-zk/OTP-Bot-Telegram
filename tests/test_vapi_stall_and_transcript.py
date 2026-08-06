from datetime import datetime, timedelta

from handlers import vapi_webhooks as vw


def test_extract_transcript_turn_from_message_wrapper():
    """Vapi nests the live transcript under top-level 'message' (payload_keys=['message'])."""
    payload = {
        "type": "speech-update",
        "message": {
            "speech": {"role": "customer", "transcript": "my code is 123456"},
        },
    }
    text, role = vw._extract_transcript_turn(payload, payload.get("message", payload), "speech-update")
    assert text == "my code is 123456"
    assert role == "customer"


def test_extract_transcript_turn_real_conversation_update():
    """Real captured Vapi conversation-update: customer speech lives in
    message.conversation as {role, content}."""
    payload = {
        "type": "conversation-update",
        "message": {
            "conversation": [
                {"role": "system", "content": "You are Luke..."},
                {"role": "assistant", "content": "Hello. This is Luke from Chime Bank."},
                {"role": "user", "content": "Is being recorded."},
            ],
        },
    }
    text, role = vw._extract_transcript_turn(payload, payload["message"], "conversation-update")
    assert text == "Is being recorded."
    assert role == "customer"


def test_extract_transcript_turn_real_artifact_messages():
    """Speech-update carries the utterance in message.artifact.messages as
    {role, message}."""
    payload = {
        "type": "speech-update",
        "message": {
            "role": "user",
            "status": "started",
            "artifact": {
                "messages": [
                    {"role": "bot", "message": "Hello"},
                    {"role": "user", "message": "the code is 654321"},
                ]
            },
        },
    }
    text, role = vw._extract_transcript_turn(payload, payload["message"], "speech-update")
    assert text == "the code is 654321"
    assert role == "customer"


def test_extract_turn_text_never_returns_the_wrapper_dict():
    """Regression: _extract_turn_text(payload) must NOT return payload['message']
    (the whole wrapper dict) via a 'message' key. That dict then blew up the
    .strip() calls downstream in production."""
    payload = {"message": {"type": "speech-update", "speech": {"role": "assistant", "transcript": "hi"}}}
    text = vw._extract_turn_text(payload)
    assert text == ""
    assert isinstance(text, str)


def test_handle_transcript_real_nested_speech_payload_does_not_crash(monkeypatch):
    """A payload shaped exactly like the Render logs (only {'message': {...}} at
    top-level) must extract the customer transcript and not call .strip() on a dict."""
    sent = []
    monkeypatch.setattr(vw, "_send_live_status", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(vw, "_detect_ivr_in_transcript", lambda t: "")

    payload = {
        "type": "speech-update",
        "message": {
            "speech": {"role": "customer", "transcript": "my code is 555777"},
        },
    }
    resp = vw._handle_transcript(payload, "call1", "vapi1", None)
    assert resp.status_code == 200


def test_handle_transcript_real_nested_conversation_update_does_not_crash(monkeypatch):
    sent = []
    monkeypatch.setattr(vw, "_send_live_status", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(vw, "_detect_ivr_in_transcript", lambda t: "")

    payload = {
        "type": "conversation-update",
        "message": {
            "conversation": [
                {"role": "system", "content": "You are Luke..."},
                {"role": "assistant", "content": "Hello from Chime Bank."},
                {"role": "user", "content": "the code is 888222"},
            ]
        },
    }
    resp = vw._handle_transcript(payload, "call1", "vapi1", None)
    assert resp.status_code == 200


def test_extract_transcript_turn_top_level_fallback():
    payload = {
        "type": "speech-update",
        "speech": {"role": "assistant", "text": "hello"},
    }
    text, role = vw._extract_transcript_turn(payload, payload.get("message", payload), "speech-update")
    assert text == "hello"
    assert role == "assistant"


def test_extract_transcript_turn_conversation_update():
    payload = {
        "type": "conversation-update",
        "message": {
            "messages": [
                {"role": "assistant", "content": "Please say the code"},
                {"role": "user", "content": "the code is 654321"},
            ]
        },
    }
    text, role = vw._extract_transcript_turn(payload, payload.get("message", payload), "conversation-update")
    assert text == "the code is 654321"
    assert role == "customer"


def test_assistant_turn_extraction():
    payload = {
        "type": "conversation-update",
        "message": {
            "messages": [
                {"role": "assistant", "content": "Your one-time code is 111222"},
            ]
        },
    }
    turn = vw._extract_assistant_turn(payload, payload.get("message", payload), "conversation-update")
    assert turn == "Your one-time code is 111222"


def test_stall_watchdog_fires_on_silent_leg():
    session = {
        "call_started_at": datetime.utcnow() - timedelta(seconds=200),
    }
    fired = vw._check_call_stalled(session, {}, "call1", "vapi1", None)
    assert fired is True
    assert session.get("stall_hangup_fired") is True


def test_stall_watchdog_skips_before_cap():
    session = {"call_started_at": datetime.utcnow() - timedelta(seconds=30)}
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is False


def test_stall_watchdog_exempts_human_speech():
    session = {
        "call_started_at": datetime.utcnow() - timedelta(seconds=300),
        "stall_seen_human_speech": True,
    }
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is False


def test_stall_watchdog_exempts_otp_captured():
    session = {
        "call_started_at": datetime.utcnow() - timedelta(seconds=300),
        "otp": "123456",
    }
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is False


def test_stall_watchdog_one_shot():
    session = {"call_started_at": datetime.utcnow() - timedelta(seconds=300)}
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is True
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is False


def test_ivr_speech_keeps_watchdog_armed():
    """Recognized IVR is hung up immediately; unrecognized machine chatter must
    NOT count as human speech, so the stall watchdog stays armed."""
    session = {"call_started_at": datetime.utcnow() - timedelta(seconds=300)}
    vw._record_human_or_ivr_speech(session, is_ivr=True)
    assert session.get("stall_seen_human_speech") is None
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is True


def test_target_dedup_suppresses_ivr_accumulation(monkeypatch):
    """conversation-update streams the ACCUMULATED transcript; the operator must
    see only genuinely new lines, not each growing extension (an IVR menu used
    to spam ~40 identical-looking messages)."""
    from unittest import mock
    import bot as bot_mod

    sent = []
    store: dict = {}

    def fake_get(csid, *a, **k):
        return store.get(csid)

    def fake_ntfy(chat_id, call_sid, user_id, digits, vapi_call_id=None):
        return None

    monkeypatch.setattr(bot_mod, "get_call_session", fake_get)
    monkeypatch.setattr(vw, "_send_live_status", lambda c, t, **k: sent.append(t))
    monkeypatch.setattr(vw, "_detect_ivr_in_transcript", lambda t: "")
    monkeypatch.setattr(vw, "extract_otp_from_transcript", lambda t, n: None)
    monkeypatch.setattr(vw, "_resolve_chat_id", lambda *a, **k: 42)

    t1 = "An admission question"
    t2 = "An admission question Press 1 to reach undergraduate admission."
    t3 = "An admission question Press 1 to reach undergraduate admission. For tuition press 3 to reach the bursar."
    t4 = "Call is being recorded for quality and training purposes."

    def payload_for(text):
        return {"type": "conversation-update", "message": {"conversation": [{"role": "user", "content": text}]}}

    sid = "call_dedup"
    store[sid] = {"call_sid": sid}
    vw._handle_transcript(payload_for(t1), sid, None, None)
    vw._handle_transcript(payload_for(t2), sid, None, None)
    vw._handle_transcript(payload_for(t3), sid, None, None)
    vw._handle_transcript(payload_for(t4), sid, None, None)

    assert sent == [f"👤 Target: {t1}", f"👤 Target: {t4}"]
