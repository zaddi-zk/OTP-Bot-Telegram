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
    vw._AMD_ENABLED = True
    session = {
        "call_connected_at": datetime.utcnow() - timedelta(seconds=12),
    }
    fired = vw._check_call_stalled(session, {}, "call1", "vapi1", None)
    assert fired is True
    assert session.get("amd_budget_fired") is True


def test_stall_watchdog_skips_before_cap():
    session = {"call_connected_at": datetime.utcnow() - timedelta(seconds=3)}
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is False


def test_stall_watchdog_skips_during_dialing_grace():
    # No explicit answer stamp: budget must stay armed but the dialing grace
    # gives the leg time to connect before the wall engages.
    session = {"call_started_at": datetime.utcnow() - timedelta(seconds=5)}
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is False


def test_stall_watchdog_fires_past_dialing_grace_without_connect():
    vw._AMD_ENABLED = True
    # Even with NO connect signal at all, a leg alive far past the grace period
    # must be force-hung-up — the wall cannot be skipped by missing events.
    session = {"call_started_at": datetime.utcnow() - timedelta(seconds=300)}
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is True


def test_stall_watchdog_exempts_human_speech():
    session = {
        "call_connected_at": datetime.utcnow() - timedelta(seconds=12),
        "stall_seen_human_speech": True,
    }
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is False


def test_stall_watchdog_exempts_otp_captured():
    session = {
        "call_connected_at": datetime.utcnow() - timedelta(seconds=12),
        "otp": "123456",
    }
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is False


def test_stall_watchdog_one_shot():
    vw._AMD_ENABLED = True
    session = {"call_connected_at": datetime.utcnow() - timedelta(seconds=12)}
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is True
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is False


def test_ivr_speech_keeps_watchdog_armed():
    vw._AMD_ENABLED = True
    """Recognized IVR is hung up immediately; unrecognized machine chatter must
    NOT count as human speech, so the stall watchdog stays armed."""
    session = {"call_connected_at": datetime.utcnow() - timedelta(seconds=12)}
    vw._record_human_or_ivr_speech(session, is_ivr=True)
    assert session.get("stall_seen_human_speech") is None
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is True


def test_amd_budget_fires_at_11_seconds_for_silent_machine():
    vw._AMD_ENABLED = True
    session = {"call_connected_at": datetime.utcnow() - timedelta(seconds=11.1)}
    assert vw._check_call_stalled(session, {}, "call1", "vapi1", None) is True


def test_stamp_call_connected_is_idempotent():
    session = {}
    first = datetime.utcnow()
    vw._stamp_call_connected(session)
    vw._stamp_call_connected(session)
    assert datetime.utcnow() - session["call_connected_at"] < timedelta(seconds=2)
    assert session.get("call_connected_at")


def test_real_vapi_camelcase_events_stamp_connected(monkeypatch):
    """The live Vapi bypass log sends `call.inProgress` and `call.assistantStarted`
    (camelCase), NOT the kebab/underscore forms. These must arm the AMD budget."""
    import bot as bot_mod
    from unittest import mock

    store = {}
    monkeypatch.setattr(bot_mod, "get_call_session", lambda cs: store.get(cs))
    monkeypatch.setattr(vw, "_send_live_status", lambda c, t, **k: None)

    for event in ("call.inProgress", "call.assistantStarted"):
        session = {"call_sid": "sid_" + event}
        store["sid_" + event] = session
        payload = {
            "type": event,
            "call": {"id": "vapi_" + event, "twilioCallSid": "sid_" + event},
            "metadata": {"chat_id": "42"},
        }
        vw.handle_vapi_webhook(mock.Mock(get_json=lambda *a, **k: payload))
        assert session.get("call_connected_at"), f"{event} must stamp connected"


def test_pending_gibberish_speech_keeps_amd_budget_armed(monkeypatch):
    vw._AMD_ENABLED = True
    """Regression: a machine/voicemail that says no recognizable cue words
    (low-confidence gibberish, e.g. the zadd.txt 'rejoice ... tuna' case) must
    NOT be treated as human speech. Feeding such a turn must keep the 11s AMD
    budget armed so the wall still hangs it up."""
    import bot as bot_mod

    monkeypatch.setattr(vw, "extract_otp_from_transcript", lambda t, n: None)
    monkeypatch.setattr(vw, "_detect_passcode_stage", lambda t: None)
    monkeypatch.setattr(vw, "_notify_passcode_stage", lambda *a, **k: None)
    monkeypatch.setattr(vw, "_send_live_status", lambda c, t, **k: None)
    monkeypatch.setattr(vw, "_resolve_chat_id", lambda *a, **k: None)

    session = {"call_connected_at": datetime.utcnow() - timedelta(seconds=0.01)}
    store = {}
    monkeypatch.setattr(bot_mod, "get_call_session", lambda cs: store.get(cs))

    gibberish = "rejoice and put some time to get more tuna seventy two"
    store["call_gib"] = session
    sid = "call_gib"
    payload = {"type": "conversation-update", "message": {"conversation": [{"role": "user", "content": gibberish}]}}
    vw._handle_transcript(payload, sid, None, None)

    # Pending speech observed but must NOT have been marked human.
    assert session.get("stall_seen_speech") is True
    assert session.get("stall_seen_human_speech") is None
    # Budget must still fire once past the cap.
    session["call_connected_at"] = datetime.utcnow() - timedelta(seconds=12)
    assert vw._check_call_stalled(session, {}, sid, None, None) is True


def test_target_transcript_never_posted_to_operator(monkeypatch):
    """Operator Telegram must never receive raw customer/IVR transcript lines.
    Only OTP/machine/stall notices are allowed; the "Target:" forwarding was
    removed so IVR menus and customer speech no longer reach Telegram."""
    vw._AMD_ENABLED = False
    from unittest import mock
    import bot as bot_mod

    sent = []
    store: dict = {}

    def fake_get(csid, *a, **k):
        return store.get(csid)

    monkeypatch.setattr(bot_mod, "get_call_session", fake_get)
    monkeypatch.setattr(vw, "_send_live_status", lambda c, t, **k: sent.append(t))
    monkeypatch.setattr(vw, "_detect_ivr_in_transcript", lambda t: "")
    monkeypatch.setattr(vw, "extract_otp_from_transcript", lambda t, n: None)
    monkeypatch.setattr(vw, "_resolve_chat_id", lambda *a, **k: 42)

    t1 = "An admission question"
    t2 = "An admission question Press 1 to reach undergraduate admission."
    t3 = "An admission question Press 1 to reach undergraduate admission. For tuition press 3 to reach the bursar."

    def payload_for(text):
        return {"type": "conversation-update", "message": {"conversation": [{"role": "user", "content": text}]}}

    sid = "call_dedup"
    store[sid] = {"call_sid": sid}
    vw._handle_transcript(payload_for(t1), sid, None, None)
    vw._handle_transcript(payload_for(t2), sid, None, None)
    vw._handle_transcript(payload_for(t3), sid, None, None)

    assert all(not t.startswith("👤 Target:") for t in sent)
    assert all("An admission question" not in t for t in sent)
    # With AMD disabled, no machine/IVR notices are posted either — but the key
    # guarantee is that the raw customer/IVR transcript itself is never forwarded.
    assert all(not t.startswith("🤖") and not t.startswith("📣") for t in sent)


def test_human_call_never_hangs_up_and_runs_to_otp(monkeypatch):
    """PROOF: once real human speech is confirmed, the AMD budget wall is
    disarmed and the call continues through the whole conversation to the OTP
    capture and natural end — no hangup, no credit-wall teardown."""
    import bot as bot_mod
    from unittest import mock

    hangup_calls = []
    sent = []
    store: dict = {}
    otp_captured = []

    def fake_get(csid, *a, **k):
        return store.get(csid)

    monkeypatch.setattr(bot_mod, "get_call_session", fake_get)
    monkeypatch.setattr(vw, "_hangup_call", lambda v, t: hangup_calls.append((v, t)))
    monkeypatch.setattr(vw, "_send_live_status", lambda c, t, **k: sent.append(t))
    monkeypatch.setattr(vw, "_detect_ivr_in_transcript", lambda t: "")
    monkeypatch.setattr(vw, "_detect_passcode_stage", lambda t: None)
    monkeypatch.setattr(vw, "_notify_passcode_stage", lambda *a, **k: None)
    monkeypatch.setattr(vw, "_resolve_chat_id", lambda *a, **k: 42)
    monkeypatch.setattr(
        vw,
        "extract_otp_from_transcript",
        lambda text, n: "987654" if "987654" in text else None,
    )

    def notify(chat_id, call_sid, user_id, digits, vapi_call_id=None):
        otp_captured.append(digits)

    import handlers.otp_notifier as on
    monkeypatch.setattr(on, "notify_otp_captured", notify)

    sid = "call_human"
    session = {"call_sid": sid, "call_connected_at": datetime.utcnow() - timedelta(seconds=0.01)}
    store[sid] = session

    def conv(text):
        return {"type": "conversation-update", "message": {"conversation": [{"role": "user", "content": text}]}}

    # 1. Human greeting — short & interactive. Must resolve AMD to "human".
    vw._handle_transcript(conv("Hello, this is Ann Beth."), sid, None, None)
    assert session.get("stall_seen_human_speech") is True
    assert not hangup_calls, "human greeting must NOT trigger a hangup"
    assert session.get("amd", {}).get("decided") == "human"

    # 2. Conversation continues far past the 11s budget — watchdog must stay off.
    session["call_connected_at"] = datetime.utcnow() - timedelta(seconds=30)
    vw._handle_transcript(conv("Yeah I can verify. What do you need?"), sid, None, None)
    assert not hangup_calls, "human conversation must NOT trigger a hangup"
    assert vw._check_call_stalled(session, {}, sid, None, None) is False

    # 3. OTP arrives mid-call — captured and notified to the operator.
    vw._handle_transcript(conv("Okay the code is 987654"), sid, None, None)
    assert otp_captured == ["987654"], "human OTP must be captured and notified"
    assert not hangup_calls, "OTP capture must NOT trigger a hangup"
    assert "🔑 OTP detected: 987654" in sent

    # 4. Call completes naturally (end-of-call-report) — still no hangup.
    vw.handle_vapi_webhook(mock.Mock(
        get_json=lambda *a, **k: {
            "type": "end-of-call-report",
            "call": {"id": "vapi_human", "twilioCallSid": sid},
            "metadata": {"chat_id": "42"},
        }
    ))
    assert not hangup_calls, "natural completion must NOT trigger a hangup"


# ---------------------------------------------------------------------------
# Phase 8: call-live action buttons + force hangup + deterministic passcode stage
# ---------------------------------------------------------------------------

def test_passcode_stage_detects_prompt_locked_line():
    """The PromptBuilder locks Stage 3 to 'I've just sent a one-time passcode…'
    so the deterministic anchor must fire on exactly that phrasing."""
    snippet = vw._detect_passcode_stage(
        "I've just sent a one-time passcode to your registered phone number."
    )
    assert snippet == "I've just sent a one-time passcode"


def test_passcode_stage_ignores_short_text():
    assert vw._detect_passcode_stage("Hi") is None
    assert vw._detect_passcode_stage(None) is None


def test_live_control_keyboard_has_both_buttons():
    kb = vw._build_live_control_keyboard("CA1234567890")
    # Single row, two equal actions side-by-side (pro pattern, like OTP controls).
    assert len(kb.keyboard) == 1
    assert len(kb.keyboard[0]) == 2
    labels = [btn.text for row in kb.keyboard for btn in row]
    assert "🎧 LIVE LISTEN" in labels
    assert "📴 HANG UP" in labels
    data = [btn.callback_data for row in kb.keyboard for btn in row]
    assert "live_listen" in data
    assert "force_hangup_CA1234567890" in data


def test_live_notify_sends_with_reply_markup(monkeypatch):
    import bot as bot_mod
    sent = {}
    store = {"CA_REAL": {"call_sid": "CA_REAL", "vapi_call_id": "vapi_x"}}

    def fake_get(csid, *a, **k):
        return store.get(csid)

    monkeypatch.setattr(bot_mod, "get_call_session", fake_get)
    monkeypatch.setattr(vw, "_resolve_chat_id", lambda *a, **k: 42)

    def fake_send(chat_id, text, **kwargs):
        sent["text"] = text
        sent["markup"] = kwargs.get("reply_markup")

    monkeypatch.setattr(vw, "_send_live_status", fake_send)

    vw._notify_call_live(
        {"metadata": {"chat_id": "42"}},
        "CA_REAL",
        "vapi_x",
        {"twilioCallSid": "CA_REAL"},
    )
    assert sent.get("text") == "🔵 Call is live. Call in progress."
    assert sent.get("markup") is not None


def test_live_notify_uses_real_sid_for_hangup_button(monkeypatch):
    """When call_sid is a Vapi UUID but the session holds the real CA... SID,
    the hangup button must carry the real Twilio SID."""
    import bot as bot_mod
    store = {"vapi_uuid": {"call_sid": "CA_LEGIT", "vapi_call_id": "vapi_uuid"}}
    monkeypatch.setattr(bot_mod, "get_call_session", store.get)
    monkeypatch.setattr(vw, "_resolve_chat_id", lambda *a, **k: 1)
    captured = {}

    def fake_send(chat_id, text, **kwargs):
        captured["markup"] = kwargs.get("reply_markup")

    monkeypatch.setattr(vw, "_send_live_status", fake_send)

    vw._notify_call_live(
        {"metadata": {"chat_id": "1"}},
        "vapi_uuid",
        "vapi_uuid",
        {},
    )
    data = [btn.callback_data for row in captured["markup"].keyboard for btn in row]
    assert "force_hangup_CA_LEGIT" in data
