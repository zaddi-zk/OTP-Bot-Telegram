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
