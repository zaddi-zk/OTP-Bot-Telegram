from models.call_metadata import AIBehavior, CallMetadata, CompanyInfo, OTPConfig, TargetInfo
from services.prompt_builder import PromptBuilder


def _metadata(scenario: str = "bank", **kw) -> CallMetadata:
    md = CallMetadata(
        target=TargetInfo(
            name="John Doe",
            phone="+15551234567",
            region=kw.get("region"),
        ),
        company=CompanyInfo(
            name="Chase",
            department="Security",
            representative_name="Sarah",
        ),
        reason=scenario,
        otp=OTPConfig(length=6, delivery_method="sms"),
        ai=AIBehavior(),
    )
    md.internal = {"scenario": scenario}
    return md


def test_build_contains_identity_and_opener():
    prompt = PromptBuilder().build(_metadata("bank"))
    assert "Sarah" in prompt
    assert "Chase Security" in prompt
    assert "Am I speaking with John Doe?" in prompt


def test_build_locks_reason_facts():
    prompt = PromptBuilder().build(_metadata("bank"))
    assert "YOUR REASON FACTS" in prompt
    assert "Confirm question" in prompt


def test_build_stage_gating_present():
    prompt = PromptBuilder().build(_metadata("bank"))
    for stage in ("STAGE 1", "STAGE 2", "STAGE 3", "STAGE 4"):
        assert stage in prompt


def test_build_off_topic_3_step():
    prompt = PromptBuilder().build(_metadata("bank"))
    assert "OFF-TOPIC ESCALATION" in prompt
    assert "out of the call" in prompt
    assert "Goodbye" in prompt


def test_build_wrong_number_firm_push_then_close():
    prompt = PromptBuilder().build(_metadata("bank"))
    assert "WRONG NUMBER" in prompt
    assert "disregard this call" in prompt


def test_build_identity_denial_tight():
    prompt = PromptBuilder().build(_metadata("bank"))
    assert "IDENTITY DENIAL" in prompt
    assert "re-anchor" in prompt.lower() or "ONCE" in prompt


def test_build_never_says_scam_is_ai():
    prompt = PromptBuilder().build(_metadata("bank"))
    assert "as an AI" in prompt
    assert "NEVER OFFER ALTERNATIVES" in prompt


def test_build_crypto_scenario_has_amount_in_facts():
    prompt = PromptBuilder().build(_metadata("crypto"))
    assert "Amount:" in prompt


def test_build_uses_region_from_target():
    prompt = PromptBuilder().build(_metadata("bank", region="Florida"))
    assert "Florida" in prompt


def test_build_messages_returns_system_role():
    msgs = PromptBuilder().build_messages(_metadata("bank"))
    assert msgs[0]["role"] == "system"
    assert "Sarah" in msgs[0]["content"]


def test_language_file_fallback_both_cases():
    """_load_master_config reads language.txt OR Language.txt (case variance)."""
    builder = PromptBuilder()
    md = _metadata("bank")
    md.internal = {"user_id": "99999"}
    # No user dir exists; must not raise and must return empty mapping safely.
    cfg = builder._load_master_config(md)
    assert isinstance(cfg, dict)
    assert "language" in cfg
