"""AMD state machine tests: voicemail / IVR / monologue / human verdicts,
including the beep-race (machine resolved before a beep is ever heard)."""

from services.amd import AmdStateMachine


def _machine() -> AmdStateMachine:
    return AmdStateMachine({})


def test_voicemail_greeting_resolves_immediately():
    m = _machine()
    r = m.feed("customer", "the person you are trying to reach is unavailable, please leave a message after the tone", ts=1.0)
    assert r.decision == "voicemail"
    assert r.is_terminal_machine()
    assert "leave a message" in r.reason


def test_voicemail_you_have_reached():
    m = _machine()
    r = m.feed("customer", "you have reached the voicemail box for 555-0100", ts=1.0)
    assert r.decision == "voicemail"
    assert r.is_terminal_machine()


def test_single_ivr_turn_resolves_machine():
    m = _machine()
    r = m.feed(
        "customer",
        "thank you for calling, press 1 for english, press 2 for spanish, this call is monitored and recorded for quality assurance",
        ts=1.0,
    )
    assert r.decision == "machine"
    assert r.kind == "ivr"
    assert r.is_terminal_machine()


def test_short_ivr_without_len_does_not_trigger_single_signal():
    m = _machine()
    r = m.feed("customer", "press 1", ts=1.0)
    assert r.decision == "pending"


def test_cadence_monologue_resolves_machine_without_assistant_interleave():
    m = _machine()
    m.feed("assistant", "Hello, this is security.", ts=1.0)
    assert m.feed("customer", "we are experiencing high call volumes, please remain on the line", ts=2.0).decision == "pending"
    assert m.feed("customer", "your call will be answered in the order it was received, thank you for waiting", ts=4.0).decision == "pending"
    r = m.feed("customer", "we apologize for the delay and appreciate your patience during this busy period", ts=6.0)
    assert r.decision == "machine"
    assert r.kind == "monologue"


def test_cadence_not_triggered_with_assistant_interleave():
    m = _machine()
    m.feed("assistant", "Hello", ts=1.0)
    m.feed("customer", "oh hi, i was just about to ask about that charge", ts=2.0)
    m.feed("assistant", "of course, go ahead", ts=3.0)
    r = m.feed("customer", "yes can you help me with that, thanks", ts=4.0)
    assert r.decision != "machine"


def test_human_greeting_resolves_human():
    m = _machine()
    r = m.feed("customer", "hello, who is this?", ts=1.0)
    assert r.decision == "human"
    assert r.is_terminal_human()


def test_human_short_answer_resolves_human():
    m = _machine()
    r = m.feed("customer", "yes this is me", ts=1.0)
    assert r.decision == "human"


def test_decided_is_idempotent():
    m = _machine()
    m.feed("customer", "the person you are trying to reach is unavailable, please leave a message after the tone", ts=1.0)
    r2 = m.feed("customer", "any other text later in the call", ts=5.0)
    assert r2.decision == "voicemail"


def test_empty_and_noncustomer_roles_stay_pending():
    m = _machine()
    assert m.feed("assistant", "Hello").decision == "pending"
    assert m.feed("system", "You are an agent").decision == "pending"
    assert m.feed("customer", "").decision == "pending"
    assert m.feed("customer", "   ").decision == "pending"


def test_state_persists_in_session_dict():
    session = {}
    m1 = AmdStateMachine(session)
    m1.feed("customer", "leave a message after the tone", ts=1.0)
    m2 = AmdStateMachine(session)  # new instance, same session -> same state
    assert m2.decided == "voicemail"


def test_beep_race_resolves_machine_from_greeting_only():
    """Even if the audio beep payload arrives late/out of order, the machine is
    already resolved from the greeting text — no wait for a beep is required."""
    session = {}
    m = AmdStateMachine(session)
    greeting = m.feed("customer", "the person you have reached is not available, please leave a message after the beep", ts=1.0)
    assert greeting.is_terminal_machine()
    # A late 'beep' audio artifact (speech-update with no transcript) arrives:
    assert m.feed("customer", "", ts=3.0).decision == "voicemail"
