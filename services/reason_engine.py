"""services/reason_engine.py

Seeds a concrete, consistent "reason profile" for a call, derived from the
operator's chosen scenario. Facts are generated ONCE per call (at prompt-build
time) and hard-locked into the system prompt so the AI can restate the exact
same what / device / location / time every time and never contradicts itself.

Design points
-------------
* Server-seeded, not AI-invented: the model can't hallucinate a second city or
  a clashing device because it only has these facts to reference.
* Time is hour-agnostic (no PM/AM, no evening/morning/afternoon) so the reason
  is defensible at 3 AM or 3 PM.
* US-centric location pool, biased toward the target region when the operator
  set one (region value is matched case-insensitively against city/state names).
* crypto / payment scenarios include a random monetary amount for believability.
"""

from __future__ import annotations

import random
import re
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Per-scenario fact templates. Each entry maps scenario key -> fact spec.
# `what` is the fixed verb phrase; `confirm_question` template interpolates
# the seeded device / location / time so the AI asks a concrete question.
# ---------------------------------------------------------------------------

_DEVICES = [
    "Windows laptop",
    "iPhone",
    "Android phone",
    "MacBook",
    "Samsung Galaxy phone",
]

_BROWSERS = [
    "Chrome browser",
    "Safari browser",
    "Edge browser",
    "Firefox browser",
]

_TIMEFRAMES = [
    "just now",
    "about 5 minutes ago",
    "about 10 minutes ago",
    "about 15 minutes ago",
    "about 20 minutes ago",
    "about 30 minutes ago",
    "right before the alert came through",
]

# (city, state)
_US_CITIES = [
    ("Austin", "Texas"),
    ("Dallas", "Texas"),
    ("Houston", "Texas"),
    ("Miami", "Florida"),
    ("Orlando", "Florida"),
    ("Tampa", "Florida"),
    ("Atlanta", "Georgia"),
    ("Charlotte", "North Carolina"),
    ("Raleigh", "North Carolina"),
    ("Nashville", "Tennessee"),
    ("Memphis", "Tennessee"),
    ("Chicago", "Illinois"),
    ("Indianapolis", "Indiana"),
    ("Detroit", "Michigan"),
    ("Columbus", "Ohio"),
    ("Cleveland", "Ohio"),
    ("Phoenix", "Arizona"),
    ("Tucson", "Arizona"),
    ("Denver", "Colorado"),
    ("Salt Lake City", "Utah"),
    ("Las Vegas", "Nevada"),
    ("Portland", "Oregon"),
    ("Seattle", "Washington"),
    ("San Francisco", "California"),
    ("Los Angeles", "California"),
    ("San Diego", "California"),
    ("Sacramento", "California"),
    ("Minneapolis", "Minnesota"),
    ("Kansas City", "Missouri"),
    ("St. Louis", "Missouri"),
    ("New Orleans", "Louisiana"),
    ("Oklahoma City", "Oklahoma"),
    ("Pittsburgh", "Pennsylvania"),
    ("Philadelphia", "Pennsylvania"),
    ("Baltimore", "Maryland"),
    ("Washington", "D.C."),
    ("Richmond", "Virginia"),
    ("Boston", "Massachusetts"),
    ("New York", "New York"),
    ("Newark", "New Jersey"),
]

_SCENARIO_SPECS: Dict[str, Dict[str, str]] = {
    "bank": {
        "what": "an unrecognized device signing in to your {company} online account",
        "confirm_question": "Did you just sign in from {device_article} in {city}, {state} using {browser}?",
        "detail_hint": "it was a sign-in from {device_article} using {browser} at {city}, {state}",
    },
    "crypto": {
        "what": "a {amount} withdrawal requested from your {company} account",
        "confirm_question": "Did you just request a withdrawal of {amount}?",
        "detail_hint": "the withdrawal shows {amount} going out from {city}, {state}",
        "amount": True,
    },
    "ecommerce": {
        "what": "an order of {amount} placed on your {company} account",
        "confirm_question": "Did you just place an order for {amount}?",
        "detail_hint": "the order shows {amount} charged from {city}, {state}",
        "amount": True,
    },
    "email": {
        "what": "a sign-in to your {company} email from an unfamiliar device",
        "confirm_question": "Did you just open your {company} email from {device_article} in {city}, {state} using {browser}?",
        "detail_hint": "it showed {device_article} using {browser} in {city}, {state}",
    },
    "payment": {
        "what": "a {amount} payment sent from your {company} account",
        "confirm_question": "Did you just authorize a {amount} payment from your {company} account?",
        "detail_hint": "the payment shows {amount} sent out from {city}, {state}",
        "amount": True,
    },
    "social": {
        "what": "a login to your {company} profile from an unrecognized device",
        "confirm_question": "Did you just log in to your {company} account from {device_article} in {city}, {state}?",
        "detail_hint": "the login showed {device_article} from {city}, {state}",
    },
    "corporate": {
        "what": "unusual access to your {company} work account",
        "confirm_question": "Did you just access your {company} work account from {city}, {state}?",
        "detail_hint": "the access shows {city}, {state}",
    },
    "other": {
        "what": "unusual activity on your {company} account",
        "confirm_question": "Did you just use your {company} account from {city}, {state}?",
        "detail_hint": "the activity shows {city}, {state}",
    },
}

_AMOUNTS = [
    "$84.50",
    "$127.99",
    "$239.00",
    "$64.75",
    "$310.25",
    "$142.80",
    "$95.60",
    "$187.40",
]


def _article(word: str) -> str:
    """Return 'an ' or 'a ' appropriate for a word's leading sound."""
    vowels = "aeiou"
    # Handle the "eu"/"uni" pseudo-consonant cases simply for our device pool.
    first = (word or "").strip().lower()
    if not first:
        return "a "
    if first[0] in vowels and not first.startswith(("eu", "uni")):
        return "an "
    return "a "


def _normalize_region(region: Optional[str]) -> Optional[str]:
    if not region:
        return None
    value = str(region).strip().lower()
    return value or None


def _pick_location(region: Optional[str], rng: random.Random):
    """Pick a (city, state), preferring cities in the target region."""
    norm = _normalize_region(region)
    if norm:
        matches = [loc for loc in _US_CITIES if norm in loc[0].lower() or norm in loc[1].lower()]
        if matches:
            return rng.choice(matches)
    return rng.choice(_US_CITIES)


def generate_facts(
    scenario: Optional[str],
    region: Optional[str] = None,
    language: Optional[str] = None,
    seed: Optional[int] = None,
    company: str = "",
) -> dict:
    """Generate a deterministic-ish fact profile for one call.

    Args:
        scenario:  one of the 8 scenario keys (bank/crypto/ecommerce/email/
                   payment/social/corporate/other). Unknown -> "other".
        region:    optional target region; biases the city pool.
        language:  reserved (fact language stays English for now).
        company:   used to fill {company} in confirm_question / detail_hint.
        seed:      optional RNG seed for reproducible tests.

    Returns a dict with keys: scenario, what, device, browser_os, city, state,
    city_state, timeframe, amount ("" when N/A), confirm_question, detail_hint.
    """
    rng = random.Random(seed)
    spec = _SCENARIO_SPECS.get(scenario or "", _SCENARIO_SPECS["other"])
    scenario_key = scenario if scenario in _SCENARIO_SPECS else "other"

    device = rng.choice(_DEVICES)
    browser = rng.choice(_BROWSERS)
    timeframe = rng.choice(_TIMEFRAMES)
    city, state = _pick_location(region, rng)
    amount = ""
    if spec.get("amount"):
        amount = rng.choice(_AMOUNTS)

    fmt = {
        "company": company or "your account",
        "device": device,
        "device_article": _article(device) + device,
        "browser": browser,
        "browser_os": f"{browser}",
        "city": city,
        "state": state,
        "timeframe": timeframe,
        "amount": amount,
    }

    confirm_question = spec["confirm_question"].format(**fmt)
    detail_hint = spec["detail_hint"].format(**fmt)

    # `what` may reference {company} and {amount}; the prompt builder fills
    # {company} later. Store with a placeholder-free form for now.
    what = spec["what"]

    return {
        "scenario": scenario_key,
        "what": what,
        "device": device,
        "browser_os": fmt["browser_os"],
        "city": city,
        "state": state,
        "city_state": f"{city}, {state}",
        "timeframe": timeframe,
        "amount": amount,
        "confirm_question": confirm_question,
        "detail_hint": detail_hint,
    }


def facts_to_block(facts: dict, company: str) -> str:
    """Render the REASON SUPPORT FACTS block for the system prompt.

    All facts are locked verbatim; the AI must restate them identically every
    time. ``company`` is interpolated into the ``what`` sentence.
    """
    what = facts["what"].replace("{company}", company or "your account")
    what = what.replace("{amount}", facts.get("amount", ""))
    lines = [
        f"- What: {what}",
        f"- Device: {facts.get('device', '')} ({facts.get('browser_os', '')})" if facts.get("device") else f"- Device: {facts.get('browser_os', '')}",
        f"- Location: {facts.get('city_state', '')}",
        f"- Time: {facts.get('timeframe', '')}",
    ]
    if facts.get("amount"):
        lines.insert(2, f"- Amount: {facts['amount']}")
    return "\n".join(lines)
