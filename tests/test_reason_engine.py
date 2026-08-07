from services.reason_engine import (
    _US_CITIES,
    _AMOUNTS,
    _article,
    facts_to_block,
    generate_facts,
)


def test_generate_facts_returns_locked_fields():
    facts = generate_facts("bank", seed=42)
    assert facts["scenario"] == "bank"
    assert facts["city"]
    assert facts["state"]
    assert facts["device"]
    assert facts["browser_os"]
    assert facts["timeframe"]
    assert facts["city_state"] == f"{facts['city']}, {facts['state']}"


def test_generate_facts_deterministic_with_seed():
    a = generate_facts("bank", seed=7)
    b = generate_facts("bank", seed=7)
    assert a["city_state"] == b["city_state"]
    assert a["device"] == b["device"]
    assert a["timeframe"] == b["timeframe"]


def test_generate_facts_unknown_scenario_falls_back_to_other():
    facts = generate_facts("totally-missing", seed=1)
    assert facts["scenario"] == "other"


def test_crypto_has_amount():
    facts = generate_facts("crypto", seed=3)
    assert facts["amount"]
    assert facts["amount"] in _AMOUNTS
    assert "$" in facts["amount"]


def test_bank_has_no_amount():
    facts = generate_facts("bank", seed=3)
    assert facts["amount"] == ""


def test_region_bias_prefers_state():
    import random
    random.seed(0)
    matches = [generate_facts("bank", region="Texas", seed=i)["city_state"] for i in range(20)]
    tx = [c for c in matches if "Texas" in c]
    assert len(tx) > 0


def test_locations_are_us_cities():
    facts = generate_facts("bank", seed=11)
    assert (facts["city"], facts["state"]) in _US_CITIES


def test_confirm_question_uses_correct_article():
    facts = generate_facts("bank", seed=2)
    q = facts["confirm_question"]
    if facts["device"].lower()[0] in "aeiou" and not facts["device"].lower().startswith(("eu", "uni")):
        assert f"an {facts['device']}" in q
    else:
        assert f"a {facts['device']}" in q


def test_facts_to_block_interpolates_company():
    facts = generate_facts("bank", seed=5)
    block = facts_to_block(facts, "Chase")
    assert "Chase" in block
    assert facts["city_state"] in block
    assert facts["timeframe"] in block


def test_facts_to_block_interpolates_amount():
    facts = generate_facts("crypto", seed=9)
    block = facts_to_block(facts, "Coinbase")
    assert facts["amount"] in block


def test_article_helper():
    assert _article("iPhone").strip() == "an"
    assert _article("MacBook").strip() == "a"
    assert _article("Android phone").strip() == "an"
