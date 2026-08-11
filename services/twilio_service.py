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

from config import ACCOUNT_SID, AUTH_TOKEN, TWILIO_PHONE_NUMBER, OUTBOUND_CALLER_ID, NGROK_URL, PROXY_POOL, build_public_base_url
from core.files import ensure_user_path, user_conf_path, write_user_file
from services.proxy_pool import AllLinesBusyError, proxy_pool, should_use_pool

logger = logging.getLogger(__name__)


class QueuedMarker:
    """Returned when a call could not start because every line was busy and the
    request was parked in the auto-queue for a retry once a number frees up."""

    def __repr__(self):  # noqa: D401
        return "CALL_QUEUED"


CALL_QUEUED = QueuedMarker()


class SelfDialError(Exception):
    """Raised when the requested destination is one of the account's own
    Twilio numbers that cannot receive calls (a pool caller-ID line, or an
    owned number with no working inbound handler). Dialing such a number makes
    Twilio decline with a confusing SIP 603/busy unless caught before dialing."""


_owned_numbers_cache = None
_owned_numbers_loaded_at = 0.0
_OWNED_NUMBERS_TTL = 300.0  # re-query Twilio every 5 minutes


def _owned_numbers():
    """E.164 -> inbound voice handler for every number owned by this account
    (cached 5 min). A number with an empty/missing handler cannot receive calls.
    """
    global _owned_numbers_cache, _owned_numbers_loaded_at
    import time as _time
    now = _time.time()
    if _owned_numbers_cache is not None and (now - _owned_numbers_loaded_at) < _OWNED_NUMBERS_TTL:
        return _owned_numbers_cache
    numbers = {}
    client = get_twilio_client()
    try:
        if client:
            for pn in client.incoming_phone_numbers.list(limit=100):
                num = (getattr(pn, "phone_number", "") or "").strip()
                if not num:
                    continue
                handler = (getattr(pn, "voice_url", "") or "").strip() or getattr(pn, "voice_application_sid", "") or ""
                numbers[num] = handler
    except Exception as exc:
        logger.warning("[OWNED_NUMBERS] could not load from Twilio: %s", exc)
    for num in PROXY_POOL:
        numbers.setdefault(num, "")
    _owned_numbers_cache = numbers
    _owned_numbers_loaded_at = now
    return numbers


def owned_twilio_numbers() -> set:
    """All E.164 numbers owned by this Twilio account (cached 5 min)."""
    return set(_owned_numbers())


def ensure_external_destination(to: Optional[str]) -> None:
    """Raise :class:`SelfDialError` if ``to`` cannot receive an inbound call.

    Blocks pool caller-ID lines (they only dial out) and any owned number with
    no inbound handler (Twilio declines with a misleading SIP 603 'busy').
    Owned numbers with a working inbound handler (e.g. a Zoiper-routed line such
    as +15074012012 -> /zoiper) are allowed as legitimate call targets.
    """
    if not to:
        return
    number = str(to).strip()
    if number in PROXY_POOL:
        raise SelfDialError(
            f"Destination {number} is a pool caller-ID line. Pool numbers only "
            "dial out; pick an external phone number to call."
        )
    handler = _owned_numbers().get(number)
    if handler is not None and not handler:
        raise SelfDialError(
            f"Destination {number} is owned by this Twilio account but has no "
            "inbound handler configured. Pick an external phone number to call."
        )


def _vapi_inline_number_ref(from_number: Optional[str]) -> Optional[dict]:
    """Inline Vapi phone-number reference used when VAPI_PHONE_NUMBER_ID is
    missing or stale (e.g. the Twilio number it was bound to was deleted).

    Uses the caller id actually dialed (pool number or platform default) so Vapi
    always has a real, owned Twilio number to bind the bypass TwiML to."""
    if not ACCOUNT_SID or not AUTH_TOKEN:
        return None
    number = (from_number or OUTBOUND_CALLER_ID or TWILIO_PHONE_NUMBER or "").strip()
    if not number:
        return None
    return {
        "twilioPhoneNumber": number,
        "twilioAccountSid": ACCOUNT_SID,
        "twilioAuthToken": AUTH_TOKEN,
    }

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
    queue_on_busy: bool = False,
    queue_key: Optional[str] = None,
    **session_kwargs,
):
    """Create a Vapi bypass session and place the call via Twilio.

    When the proxy number pool is enabled the default caller id is replaced with
    an automatically assigned free number (custom caller ids are respected and
    bypass the pool). The pooled number is released when the call ends (see the
    release hooks in the webhook handlers / sweeper).

    Returns the Twilio SID, or ``CALL_QUEUED`` when ``queue_on_busy`` was set and
    the request was parked in the auto-queue, or None on real failure. Raises
    :class:`AllLinesBusyError` when every line is busy and no queueing was used.
    """
    from services.vapi_service import create_call_bypass

    ensure_external_destination(to)

    pool_number = None
    acquired_default = False
    if should_use_pool(from_number):
        acquired_default = True
        try:
            pool_number = proxy_pool.acquire(user_id, chat_id)
            from_number = pool_number
            if caller_id in (None, "") or caller_id == from_number:
                caller_id = from_number
        except AllLinesBusyError as busy:
            logger.warning("[NUMBER_POOL] busy %s (user=%s queue=%s)", busy, user_id, queue_key)
            if queue_on_busy and queue_key:
                try:

                    def _retry():
                        place_ai_call(
                            to=to,
                            user_id=user_id,
                            chat_id=chat_id,
                            customer_name=customer_name,
                            assistant_overrides=assistant_overrides,
                            metadata=metadata,
                            from_number=from_number,
                            caller_id=caller_id,
                            record=record,
                            endpoint=endpoint,
                            mode_label=mode_label,
                            queue_on_busy=True,
                            queue_key=queue_key,
                            **session_kwargs,
                        )

                    queued = proxy_pool.submit(_retry, key=queue_key)
                except Exception:
                    queued = False
                logger.info("[NUMBER_POOL] queued call key=%s result=%s", queue_key, queued)
                return CALL_QUEUED if queued else None
            raise

    try:
        bridge = create_call_bypass(
            customer_number=to,
            customer_name=customer_name,
            assistant_overrides=assistant_overrides,
            metadata=metadata,
            phone_number_ref=_vapi_inline_number_ref(pool_number or OUTBOUND_CALLER_ID or from_number),
        )
        if not bridge:
            logger.error("[VAPI_BRIDGE] bypass call failed for %s (user=%s)", to, user_id)
            if pool_number:
                proxy_pool.release(pool_number)
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
            if pool_number:
                proxy_pool.release(pool_number)
            return None

        if pool_number:
            proxy_pool.bind_sid(pool_number, twilio_sid)

        logger.info("[VAPI_BRIDGE] Call placed by Twilio sid=%s vapi_call=%s target=%s (user=%s)",
                    twilio_sid, vapi_call_id, to, user_id)
        store_call_metadata(user_id, twilio_sid, target=to)
        call_session_kwargs = dict(session_kwargs)
        if acquired_default:
            call_session_kwargs["pool_number"] = pool_number
        try:
            from bot import register_call_session
            register_call_session(
                twilio_sid,
                user_id,
                chat_id=chat_id,
                endpoint=endpoint,
                mode_label=mode_label,
                vapi_call_id=vapi_call_id,
                **call_session_kwargs,
            )
        except Exception as exc:
            logger.debug("Failed to register bridge session: %s", exc)
        try:
            from bot import _notify_live_listen_start
            _notify_live_listen_start(twilio_sid, chat_id=chat_id, user_id=user_id)
        except Exception as exc:
            logger.debug("Failed to bootstrap live listen session: %s", exc)
        return twilio_sid
    except AllLinesBusyError:
        raise
    except Exception as exc:
        logger.error("[VAPI_BRIDGE] unexpected error for %s (user=%s): %s", to, user_id, exc)
        if pool_number:
            proxy_pool.release(pool_number)
        return None


def make_call(to: str, from_number: str = None, caller_id: str = None,
              webhook_url: str = None, user_id: str = "",
              record: bool = True,
              **kwargs) -> Optional[str]:
    ensure_external_destination(to)
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
