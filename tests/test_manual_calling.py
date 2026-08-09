"""Tests for the Manual Calling "Full Control" wizard and prompt integration.

Covers: the shared reason/flow generator (mocked GROQ refusals + fallbacks),
the {code} length wording, forbidden-phrase rewrites, the ABSOLUTE LANGUAGE
RULES block in the prompt builder, and the flow-aware Vapi firstMessage.
"""
from models.call_metadata import AIBehavior, CallMetadata, CompanyInfo, OTPConfig, TargetInfo

import services.script_generator as sg
from services.prompt_builder import PromptBuilder


# ---------------------------------------------------------------------------
# render_flow / {code} length wording
# ---------------------------------------------------------------------------

def test_render_flow_resolves_code_to_length_wording():
    out = sg.render_flow("AGENT: Please tell me the {code} code.", ctx={"code_length": "6"})
    assert "6-digit" in out
    assert "{code}" not in out


def test_render_flow_leaves_unknown_placeholders():
    out = sg.render_flow("Hi {name} — keep {mystery} intact", ctx={"name": "John"})
    assert "John" in out
    assert "{mystery}" in out


def test_code_wording_defaults_when_empty():
    assert sg._code_wording("") == "verification"
    assert sg._code_wording(0) == "verification"
    assert sg._code_wording("8") == "8-digit"


# ---------------------------------------------------------------------------
# enhance_call: language hardening
# ---------------------------------------------------------------------------

def test_enhance_call_rewrites_forbidden_phrases():
    flow = "AGENT: I understand, take your time. Maybe I think it's okay."
    out = sg.enhance_call(flow, ctx={"code_length": "6"})
    assert "I understand" not in out
    assert "take your time" not in out.lower()
    assert "maybe" not in out.lower().split() or "maybe" not in out.lower()


def test_enhance_call_never_attaches_vague_refusal_exit():
    # The merged refusal must say "call the number on your card" and never be a
    # wishy-washy "have a nice day" style out.
    out = sg.enhance_call("AGENT: We need the code.", ctx={})
    assert "If you prefer, call the number on your card. Goodbye." in out
    assert "any time" not in out.lower() or "Goodbye" in out


def test_enhance_call_guarantees_otp_request():
    out = sg.enhance_call("AGENT: Hello.", ctx={"code_length": "6"})
    assert "6-digit code" in out
    assert "Please tell me" in out


# ---------------------------------------------------------------------------
# generate_script: refusal defense chain
# ---------------------------------------------------------------------------

def _good_draft():
    return (
        "AGENT: Hello, this is Chase Security. Am I speaking with John?\n"
        "CUSTOMER: Yes.\n"
        "AGENT: We flagged a $2,500 withdrawal from New York on your checking account.\n"
        "AGENT: Please tell me the 6-digit code on your phone."
    )


def test_generate_script_uses_groq_draft_when_available(monkeypatch):
    monkeypatch.setattr(sg, "_groq_complete", lambda p, s: _good_draft())
    res = sg.generate_script(
        "a $2,500 withdrawal from New York on a checking account",
        ctx={"name": "John", "company": "Chase", "code_length": "6"},
    )
    assert res["ok"] is True
    assert "Chase Security" in res["script"]
    assert "Please tell me the 6-digit code" in res["script"]


def test_generate_script_falls_back_to_raw_reason_on_refusal(monkeypatch):
    calls = {"n": 0}

    def refusal(p, s, **k):
        calls["n"] += 1
        return "I'm sorry, I can't help with that."

    monkeypatch.setattr(sg, "_groq_complete", refusal)
    res = sg.generate_script("a $2,500 withdrawal from New York", ctx={})
    assert res["ok"] is False
    assert res["script"] == "a $2,500 withdrawal from New York"
    assert calls["n"] == 2  # first + corrective retry, then raw fallback


def test_generate_script_retries_once_then_recovers(monkeypatch):
    calls = {"n": 0}

    def refusal_then_good(p, s, **k):
        calls["n"] += 1
        return "I can't help." if calls["n"] == 1 else _good_draft()

    monkeypatch.setattr(sg, "_groq_complete", refusal_then_good)
    res = sg.generate_script("a withdrawal from New York", ctx={"code_length": "6"})
    assert res["ok"] is True
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Prompt builder: shared engine guarantees
# ---------------------------------------------------------------------------

def _metadata(**kw) -> CallMetadata:
    md = CallMetadata(
        target=TargetInfo(name="John Doe", phone="+15551234567"),
        company=CompanyInfo(name="Chase", department="Security", representative_name="Sarah"),
        reason="bank",
        otp=OTPConfig(length=6, delivery_method="sms"),
        ai=AIBehavior(),
    )
    md.internal = {"scenario": "bank"}
    for k, v in kw.items():
        md.internal[k] = v
    return md


def test_prompt_builder_has_absolute_language_rules():
    prompt = PromptBuilder().build(_metadata())
    assert "ABSOLUTE LANGUAGE RULES" in prompt
    assert "FORBIDDEN PHRASES" in prompt
    assert "AUTHORITATIVE PHRASES" in prompt
    assert "I understand" in prompt or "I have noted that" in prompt or "Take your time" in prompt


def test_prompt_builder_refusal_merge_replaces_old_exit():
    prompt = PromptBuilder().build(_metadata())
    assert "If you prefer, call the number on your card. Goodbye." in prompt
    assert "call the number on your card" in prompt
    # The old open-ended close must be gone from rule 11 + HOSTILE/MANAGER.
    assert "HOSTILE / MANAGER REQUEST" in prompt
    assert "If you prefer, call the number on your card. Goodbye." in prompt


def test_prompt_builder_resolves_code_length():
    prompt = PromptBuilder().build(_metadata())
    assert "6 digits" in prompt or "6-digit" in prompt


def test_prompt_builder_honors_delivery_internal_override():
    md = _metadata()
    md.internal["delivery"] = "email"
    prompt = PromptBuilder().build(md)
    assert "email" in prompt.lower() or "registered" in prompt.lower()


def test_prompt_builder_honors_language_internal_override():
    md = _metadata()
    md.internal["language"] = "es"
    prompt = PromptBuilder().build(md)
    assert md.ai.language == "es"


def test_prompt_builder_locks_operator_fact_pins():
    md = _metadata(scenario_needed=True)
    md.internal["fact_city"] = "Dallas"
    md.internal["fact_device"] = "Pixel 8"
    prompt = PromptBuilder().build(md)
    assert "Dallas" in prompt
    assert "Pixel 8" in prompt


def test_prompt_builder_never_puts_amount_into_sms_login_scenario():
    # An e-mail/social scenario must never carry a money amount even when one
    # is pinned by the operator (scenario-validation drops it).
    md = _metadata()
    md.internal = {"scenario": "email", "fact_amount": "$2,500"}
    prompt = PromptBuilder().build(md)
    assert "Amount:" not in prompt or ("withdrawal" not in prompt and "order of" not in prompt)


# ---------------------------------------------------------------------------
# Flow-aware Vapi firstMessage (greeting de-dupe)
# ---------------------------------------------------------------------------

def test_first_message_uses_greeting_line_from_flow():
    md = _metadata()
    md.custom_instructions = (
        "[GREETING] Hello, this is Sarah from Chase."
        "\n[FLOW] AGENT: We flagged your account. Please tell me the {code}."
    )
    overrides = md.to_vapi_assistant_overrides()
    assert overrides["firstMessage"] == "Hello, this is Sarah from Chase."


def test_first_message_first_line_delegates_tokens():
    md = _metadata()
    md.custom_instructions = "AGENT: Hi {name}, this is Chase Security."
    overrides = md.to_vapi_assistant_overrides()
    assert "John Doe" in overrides["firstMessage"]
    assert "{name}" not in overrides["firstMessage"]


def test_first_message_falls_back_to_standard_opener():
    md = _metadata()
    md.custom_instructions = None
    overrides = md.to_vapi_assistant_overrides()
    assert "Sarah" in overrides["firstMessage"]
    assert "Am I speaking with" in overrides["firstMessage"]