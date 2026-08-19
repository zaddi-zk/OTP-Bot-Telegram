import json
import logging
import time
from typing import Optional

import requests

from config import (
    VAPI_API_KEY,
    VAPI_ASSISTANT_ID,
    VAPI_PHONE_NUMBER_ID,
    build_public_base_url,
)

logger = logging.getLogger(__name__)

VAPI_BASE_URL = "https://api.vapi.ai"


class VapiError(Exception):
    pass


def _headers() -> dict:
    if not VAPI_API_KEY or VAPI_API_KEY == "YOUR_VAPI_API_KEY_HERE":
        raise VapiError("VAPI_API_KEY not configured")
    return {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json",
    }


_FORCED_VOICEMAIL_DETECTION = {
    "provider": "vapi",
    "type": "audio",
    "backoffPlan": {
        "startAtSeconds": 1.5,
        "frequencySeconds": 2.5,
        "maxRetries": 8,
    },
    "beepMaxAwaitSeconds": 6,
}


def _apply_forced_assistant_overrides(assistant_overrides: Optional[dict]) -> Optional[dict]:
    """Force pro defaults onto every call via assistantOverrides.

    1. serverUrl            -> guaranteed to be the live public URL, so Vapi's
       webhooks (conversation-update/transcript/call.ended) always reach the bot
       even after ngrok rotates (the dashboard value goes stale).

    NOTE: Vapi Answering Machine Detection / voicemailDetection is intentionally
    NOT forced (AMD is disabled globally) so calls are never auto-terminated on
    an automated answerer.
    """
    base = build_public_base_url()
    overrides = dict(assistant_overrides) if assistant_overrides else {}

    if base:
        server_url = f"{base}/vapi/webhook"
        if overrides.get("serverUrl") != server_url:
            logger.info("[VAPI_SERVER_URL] setting serverUrl=%s", server_url)
        overrides["serverUrl"] = server_url
    else:
        logger.warning("[VAPI_SERVER_URL] no public base URL — Vapi webhooks will not reach the bot")

    # AMD (voicemail detection) is disabled by default so calls are never
    # auto-terminated on an automated answerer. Leave any explicit override the
    # caller already configured untouched; do not force Vapi's own AMD on.
    if not overrides.get("voicemailMessage"):
        overrides["voicemailMessage"] = "Goodbye."

    if not overrides.get("endCallMessage"):
        overrides["endCallMessage"] = "Thank you for your time. Have a great day. Goodbye."

    if not overrides.get("firstMessageMode"):
        # Speak the opener immediately and detect voicemail in parallel, so a
        # human caller is never left waiting on silence.
        overrides["firstMessageMode"] = "assistant-speaks-first"

    _apply_noise_tuning(overrides)

    return overrides


def _apply_noise_tuning(overrides: dict) -> None:
    """Pro noise defaults for human-feeling calls.

    NOTE: Vapi's call endpoint rejects endTurnOnSilence / interruptionSettings
    in assistantOverrides (400 Bad Request) — the transcriber override alone is
    accepted. Only safe fields are applied here.

    transcriber -> Deepgram Nova-2 with English default; lowers hallucinated
    filler transcripts that trigger off-topic/stall chatter.
    """
    transcriber = overrides.get("transcriber") or {}
    if not transcriber.get("provider"):
        overrides["transcriber"] = {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en",
        }
    elif transcriber.get("provider") == "deepgram" and not transcriber.get("model"):
        transcriber["model"] = "nova-2"
        overrides["transcriber"] = transcriber


def create_call(
    customer_number: str,
    customer_name: str,
    assistant_overrides: Optional[dict] = None,
    metadata: Optional[dict] = None,
    phone_number_id: Optional[str] = None,
    sip_uri: Optional[str] = None,
) -> Optional[str]:
    """Create a Vapi call that Vapi itself dials via the SIP phone number.

    Vapi places the call using the SIP phone number resource
    (``VAPI_SIP_PHONE_NUMBER_ID``): it INVITEs Asterisk with the E.164 customer
    number in the request URI and Asterisk dials the target out through the
    SpoofGlobal trunk. Returns the Vapi call UUID — the only identifier used for
    tracking, status, and termination.
    """
    payload = {
        "customer": {
            "number": customer_number,
            "name": customer_name,
        },
    }

    if phone_number_id or VAPI_PHONE_NUMBER_ID:
        payload["phoneNumberId"] = phone_number_id or VAPI_PHONE_NUMBER_ID

    if sip_uri:
        payload["sipUri"] = sip_uri

    if VAPI_ASSISTANT_ID:
        payload["assistantId"] = VAPI_ASSISTANT_ID

    if assistant_overrides:
        payload["assistantOverrides"] = _apply_forced_assistant_overrides(assistant_overrides)

    if metadata:
        payload["metadata"] = metadata

    try:
        logger.info("[VAPI_PAYLOAD] %s", json.dumps({k: v for k, v in payload.items() if k != "assistantOverrides"}, indent=2))
        if payload.get("assistantOverrides"):
            logger.info("[VAPI_OVERRIDES] %s", json.dumps(payload["assistantOverrides"], indent=2))
        resp = requests.post(
            f"{VAPI_BASE_URL}/call",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        if resp.status_code == 201:
            result = resp.json()
            call_id = result.get("id")
            logger.info("[VAPI_CALL_CREATED] id=%s number=%s", call_id, customer_number)
            return call_id
        else:
            logger.error(
                "[VAPI_CALL_ERROR] status=%s body=%s",
                resp.status_code,
                resp.text[:500],
            )
            return None
    except requests.exceptions.Timeout:
        logger.error("[VAPI_CALL_TIMEOUT] Request to Vapi timed out")
        return None
    except requests.exceptions.RequestException as e:
        logger.error("[VAPI_CALL_FAILED] %s", e)
        return None


def get_call(call_id: str) -> Optional[dict]:
    try:
        resp = requests.get(
            f"{VAPI_BASE_URL}/call/{call_id}",
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        logger.warning("[VAPI_GET_CALL] status=%s id=%s", resp.status_code, call_id)
        return None
    except Exception as e:
        logger.warning("[VAPI_GET_CALL_ERROR] id=%s error=%s", call_id, e)
        return None


def say_to_assistant(call_id: str, message: str) -> bool:
    try:
        resp = requests.post(
            f"{VAPI_BASE_URL}/call/{call_id}/say",
            headers=_headers(),
            json={"message": message},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("[VAPI_SAY] id=%s message=%s", call_id, message[:80])
            return True
        logger.warning("[VAPI_SAY] status=%s id=%s body=%s", resp.status_code, call_id, resp.text[:200])
        return False
    except Exception as e:
        logger.warning("[VAPI_SAY_ERROR] id=%s error=%s", call_id, e)
        return False


def end_call(call_id: str) -> bool:
    """End a Vapi call session. Returns True if Vapi accepted the end request.

    The HTTP 2xx only means Vapi accepted the request — it does NOT prove the
    underlying phone leg dropped. Vapi sends BYE to Asterisk, which drops the
    SpoofGlobal outbound leg.
    """
    for attempt in range(1, 3):
        try:
            resp = requests.post(
                f"{VAPI_BASE_URL}/call/{call_id}/end",
                headers=_headers(),
                timeout=10,
            )
            if resp.status_code in (200, 201, 204):
                logger.info("[VAPI_END_CALL] id=%s ok attempt=%s", call_id, attempt)
                return True
            logger.warning(
                "[VAPI_END_CALL] status=%s id=%s attempt=%s body=%s",
                resp.status_code, call_id, attempt, resp.text[:200],
            )
        except Exception as e:
            logger.warning("[VAPI_END_CALL_ERROR] id=%s attempt=%s error=%s", call_id, attempt, e)
        time.sleep(1)
    return False


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    import hmac
    expected = hmac.new(secret.encode(), payload, "sha256").hexdigest()
    return hmac.compare_digest(expected, signature)
