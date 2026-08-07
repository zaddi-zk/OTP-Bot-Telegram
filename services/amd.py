"""Answering Machine Detection (AMD) — real-time, cadence-aware state machine.

Detects human vs. machine (IVR / voicemail / automated system) during the
initial greeting phase (Stage 1) by feeding Vapi customer transcript turns as
they arrive on the webhook.

Design points
-------------
* No fixed "hangup after N seconds" timers. Classification is driven by
  real-time speech patterns *plus* cadence (consecutive machine-looking turns
  / pauses), so a machine that says nothing machine-like in its first
  utterance still gets caught by a monologue of consecutive machine turns.
  Voicemail is caught from the greeting as soon as it is transcribed — never
  by waiting for a beep.
* Machine / voicemail resolves to an immediate graceful exit BEFORE the
  recording beep (the caller of this module triggers the hangup).
* Human resolves to "let the call proceed to Stage 2".
* Robust to async races: per-call state is kept in the session dict and the
  machine is fed raw turns as they arrive; the first high-confidence signal
  wins even if later payloads arrive out of order.
"""

from __future__ import annotations

import re
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Pattern tables
# ---------------------------------------------------------------------------

IVR_PATTERNS = [
    re.compile(
        r"(press|dial|hit|enter)[^\w]{0,16}(1|2|3|4|5|6|7|8|9|0|#|\*|one|two|three|four|five|six|seven|eight|nine|zero)",
        re.I,
    ),
    re.compile(r"\b(thank you for calling|thanks for calling|welcome to)\b", re.I),
    re.compile(
        r"\b(account number|your account|your pin|your password|your zip|your ssn|your social security)\b",
        re.I,
    ),
    re.compile(r"\benter (your |the )?(pin|password|account|code|number|zip)\b", re.I),
    re.compile(r"\b(call may be|call is being|this call is|this call may)[^\w]{0,4}(monitored|recorded)\b", re.I),
    re.compile(r"\b(main menu|automated (assistant|system|service)|virtual assistant)\b", re.I),
    re.compile(r"\b(to continue|for more options|stay on the line)\b", re.I),
    re.compile(r"\b(all our representatives|representative is (unavailable|busy|not available))\b", re.I),
    re.compile(r"\b(to be (assisted|helped|routed)|say or press|press or say)\b", re.I),
]

VOICEMAIL_CUES = [
    re.compile(r"\b(leave (a |your )?message|record your message|after the (tone|beep)|at the tone)\b", re.I),
    re.compile(r"\b(the (person|party) you are (trying to )?(call|reach))\b", re.I),
    re.compile(r"\b(you have reached|you have reached the)\b", re.I),
    re.compile(r"\b(voicemail|voice mail|mailbox|answering machine)\b", re.I),
    re.compile(r"\b(no one is (available|in the office))\b", re.I),
]

HUMAN_CUES = [
    re.compile(r"\b(yes|hi|hello|hey)\b", re.I),
    re.compile(r"\b(this is|speaking|who (is|'s) this)\b", re.I),
]

# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

# A machine greeting is usually a single long utterance; a human first answer
# is short and interactive.
_MACHINE_MIN_CHARS = 45
_HUMAN_MAX_CHARS = 28

# Consecutive machine-looking customer turns (within the cadence window) that
# resolve a "monologue" as machine when no single high-precision signal fired.
CADENCE_TURNS_FOR_MACHINE = 3
CADENCE_WINDOW_SECONDS = 8.0

_MACHINE_SINGLE_CONFIDENCE = 1.0
_MACHINE_CADENCE_CONFIDENCE = 0.9
_HUMAN_SINGLE_CONFIDENCE = 0.9
_HUMAN_NORMAL_CONFIDENCE = 0.8


def _match_any(patterns, text: str) -> Optional[str]:
    for pattern in patterns:
        m = pattern.search(text)
        if m and m.group(0):
            return m.group(0)
    return None


class AmdResult:
    """Immutable verdict for a call at a point in time."""

    __slots__ = ("decision", "kind", "reason", "confidence")

    def __init__(self, decision: str, kind: str, reason: str, confidence: float):
        # decision: "voicemail" | "machine" | "human" | "pending"
        self.decision = decision
        self.kind = kind
        self.reason = reason
        self.confidence = confidence

    def is_terminal_machine(self) -> bool:
        return self.decision in ("voicemail", "machine")

    def is_terminal_human(self) -> bool:
        return self.decision == "human"


class AmdStateMachine:
    """Per-call AMD state machine.

    State is stored in ``session["amd"]`` (a dict) so it survives the
    stateless webhook boundary. ``feed()`` is called for every live customer /
    assistant turn; it returns the current verdict without mutating anything
    outside the persisted state.
    """

    _TERMINAL = ("voicemail", "machine", "human")

    def __init__(self, session: Optional[dict] = None):
        if session is not None:
            # Bind to the session's dict so state persists across webhooks.
            self._state = session.setdefault("amd", {})
        else:
            self._state = {}

    @property
    def decided(self) -> Optional[str]:
        return self._state.get("decided")

    def feed(self, role: str, text: str, ts: Optional[float] = None) -> AmdResult:
        """Feed one transcript turn; return the current verdict.

        Args:
            role:  "customer"/"user"/"human" for the callee, "assistant"/"bot"
                   for the AI.
            text:  the transcribed utterance.
            ts:    optional timestamp (epoch seconds); defaults to now.
        """
        ts = ts if ts is not None else time.time()
        result = self._verdict()
        if result.decision != "pending":
            return result

        norm_role = str(role or "").lower()
        stripped = (text or "").strip()

        # Assistant turn: an interleave breaks a customer monologue; it also
        # never decides anything by itself.
        if norm_role in ("assistant", "bot"):
            self._state["last_assistant_ts"] = ts
            return self._verdict()

        if norm_role not in ("customer", "user", "human"):
            return self._verdict()

        if not stripped:
            return self._verdict()

        self._state["customer_turns"] = self._state.get("customer_turns", [])
        self._state["customer_turns"].append((ts, stripped))

        # 1. High-precision voicemail / IVR single-turn signal.
        single = self._single_turn_verdict(stripped)
        if single.decision != "pending":
            self._state["decided"] = single.decision
            self._state["kind"] = single.kind
            self._state["reason"] = single.reason
            return single

        # 2. Human short-turn signal (greeting).
        if self._human_signal(stripped):
            verdict = AmdResult(
                "human", "human_greeting",
                f"Short interactive greeting: {stripped[:24]!r}",
                _HUMAN_SINGLE_CONFIDENCE,
            )
            self._state["decided"] = "human"
            self._state["kind"] = verdict.kind
            self._state["reason"] = verdict.reason
            return verdict

        # 3. Cadence / monologue detection: consecutive machine-looking turns
        #    with no assistant interleave => machine.
        if self._monologue_resolved(ts):
            verdict = AmdResult(
                "machine", "monologue",
                "No assistant interleave across consecutive machine turns",
                _MACHINE_CADENCE_CONFIDENCE,
            )
            self._state["decided"] = "machine"
            self._state["kind"] = verdict.kind
            self._state["reason"] = verdict.reason
            return verdict

        return self._verdict()

    # -- internals ----------------------------------------------------------

    def _verdict(self) -> AmdResult:
        decided = self._state.get("decided")
        if decided in self._TERMINAL:
            return AmdResult(decided, self._state.get("kind", ""), self._state.get("reason", ""), self._state.get("confidence", 1.0))
        return AmdResult("pending", "pending", "", 0.0)

    def _single_turn_verdict(self, stripped: str) -> AmdResult:
        vm = _match_any(VOICEMAIL_CUES, stripped)
        if vm:
            return AmdResult("voicemail", "voicemail", f"Voicemail cue: {vm!r}", _MACHINE_SINGLE_CONFIDENCE)
        ivr = _match_any(IVR_PATTERNS, stripped)
        if ivr and len(stripped) >= _MACHINE_MIN_CHARS:
            return AmdResult("machine", "ivr", f"IVR cue: {ivr!r}", _MACHINE_SINGLE_CONFIDENCE)
        return AmdResult("pending", "", "", 0.0)

    def _human_signal(self, stripped: str) -> bool:
        if len(stripped) > _HUMAN_MAX_CHARS:
            return False
        return _match_any(HUMAN_CUES, stripped) is not None

    def _monologue_resolved(self, ts: float) -> bool:
        """Count consecutive customer turns with no assistant interleave.

        Only machine-looking turns count toward the monologue (a long run of
        short human questions would otherwise be miscounted).
        """
        last_assistant = self._state.get("last_assistant_ts")
        turns = self._state.get("customer_turns", [])
        run = 0
        for turn_ts, text in turns:
            if last_assistant is not None and turn_ts < last_assistant:
                run = 0
                continue
            if ts - turn_ts > CADENCE_WINDOW_SECONDS:
                continue
            if self._single_turn_verdict(text).decision == "pending" and len(text) < _MACHINE_MIN_CHARS:
                run = 0
                continue
            run += 1
        return run >= CADENCE_TURNS_FOR_MACHINE
