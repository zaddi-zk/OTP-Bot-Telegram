import json
import logging
import time
import xml.etree.ElementTree as ET
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
        "startAtSeconds": 2.0,
        "frequencySeconds": 2.5,
        "maxRetries": 12,
    },
    "beepMaxAwaitSeconds": 0,
}


def _apply_forced_assistant_overrides(assistant_overrides: Optional[dict]) -> Optional[dict]:
    """Force pro defaults onto every call via assistantOverrides.

    1. serverUrl            -> guaranteed to be the live public URL, so Vapi's
       webhooks (conversation-update/transcript/call.ended) always reach the bot
       even after ngrok rotates (the dashboard value goes stale).
    2. voicemailDetection   -> Vapi Answering Machine Detection runs in parallel
       with the AI's first message: no "wait-then-listen" silence for humans,
       and if a machine/voicemail is found Vapi interrupts and handles it fast.
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

    if (overrides.get("voicemailDetection") or {}).get("provider") not in ("vapi", "google", "openai"):
        overrides["voicemailDetection"] = _FORCED_VOICEMAIL_DETECTION

    if not overrides.get("voicemailMessage"):
        overrides["voicemailMessage"] = "Goodbye."

    if not overrides.get("endCallMessage"):
        overrides["endCallMessage"] = "Thank you for your time. Have a great day. Goodbye."

    if not overrides.get("firstMessageMode"):
        # Speak the opener immediately and detect voicemail in parallel, so a
        # human caller is never left waiting on silence.
        overrides["firstMessageMode"] = "assistant-speaks-first"

    return overrides


def create_call(
    customer_number: str,
    customer_name: str,
    assistant_overrides: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> Optional[str]:
    payload = {
        "customer": {
            "number": customer_number,
            "name": customer_name,
        },
    }

    if VAPI_PHONE_NUMBER_ID:
        payload["phoneNumberId"] = VAPI_PHONE_NUMBER_ID

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


def inject_live_listen_stream(twiml: str) -> str:
    """Inject a unidirectional `<Start><Stream>` into the Vapi bridge TwiML.

    Twilio allows exactly ONE bidirectional `<Connect><Stream>` per call (the
    one Vapi returns). To also get call audio for Live Listen we prepend a
    unidirectional `<Start><Stream>` that forks the audio to the bot's
    `/twilio/media` WebSocket. `<Start>` is non-blocking so the `<Connect>`
    stream that Vapi needs is unaffected.

    Returns the modified TwiML (or the original if it cannot be parsed).
    """
    if not twiml or "<Start>" in twiml:
        return twiml
    try:
        stream_url = build_public_base_url() or ""
        if not stream_url:
            logger.warning("[LIVE_LISTEN_INJECT] no public base URL; skipping stream fork")
            return twiml
        ws_url = stream_url.replace("http://", "wss://").replace("https://", "wss://")
        ws_url = ws_url.rstrip("/") + "/twilio/media"
        stream = ET.fromstring(twiml)
        start = ET.Element("Start")
        start_stream = ET.SubElement(start, "Stream")
        start_stream.set("url", ws_url)
        start_stream.set("track", "both_tracks")
        stream.insert(0, start)
        new_twiml = ET.tostring(stream, encoding="unicode", xml_declaration=True)
        logger.info("[LIVE_LISTEN_INJECT] forked media stream to %s", ws_url)
        return new_twiml
    except Exception as e:
        logger.warning("[LIVE_LISTEN_INJECT] failed to inject stream: %s", e)
        return twiml


def create_call_bypass(
    customer_number: str,
    customer_name: str,
    assistant_overrides: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> Optional[dict]:
    """Create a Vapi call in bypass mode so Vapi does NOT dial.

    Vapi only handles STT/LLM/TTS. The actual outbound call is placed by Twilio
    using the TwiML returned in ``phoneCallProviderDetails.twiml``.

    Returns ``{"vapi_call_id": str, "twiml": str}`` or None on failure.
    """
    payload = {
        "customer": {
            "number": customer_number,
            "name": customer_name,
        },
        "phoneCallProviderBypassEnabled": True,
    }

    if VAPI_PHONE_NUMBER_ID:
        payload["phoneNumberId"] = VAPI_PHONE_NUMBER_ID

    if VAPI_ASSISTANT_ID:
        payload["assistantId"] = VAPI_ASSISTANT_ID

    if assistant_overrides:
        payload["assistantOverrides"] = _apply_forced_assistant_overrides(assistant_overrides)

    if metadata:
        payload["metadata"] = metadata

    try:
        logger.info("[VAPI_BYPASS_PAYLOAD] %s", json.dumps({k: v for k, v in payload.items() if k != "assistantOverrides"}, indent=2))
        if payload.get("assistantOverrides"):
            logger.info("[VAPI_BYPASS_OVERRIDES] %s", json.dumps(payload["assistantOverrides"], indent=2))
        resp = requests.post(
            f"{VAPI_BASE_URL}/call",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        if resp.status_code == 201:
            result = resp.json()
            call_id = result.get("id")
            twiml = (
                (result.get("phoneCallProviderDetails") or {}).get("twiml")
                or ""
            )
            if not call_id or not twiml:
                logger.error(
                    "[VAPI_BYPASS_MISSING_TWIML] id=%s body=%s",
                    call_id,
                    resp.text[:500],
                )
                return None
            twiml = inject_live_listen_stream(twiml)
            logger.info("[VAPI_BYPASS_CALL_CREATED] id=%s number=%s", call_id, customer_number)
            return {"vapi_call_id": call_id, "twiml": twiml}
        else:
            logger.error(
                "[VAPI_BYPASS_CALL_ERROR] status=%s body=%s",
                resp.status_code,
                resp.text[:500],
            )
            return None
    except requests.exceptions.Timeout:
        logger.error("[VAPI_BYPASS_CALL_TIMEOUT] Request to Vapi timed out")
        return None
    except requests.exceptions.RequestException as e:
        logger.error("[VAPI_BYPASS_CALL_FAILED] %s", e)
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
    try:
        resp = requests.post(
            f"{VAPI_BASE_URL}/call/{call_id}/end",
            headers=_headers(),
            timeout=10,
        )
        return resp.status_code in (200, 201, 204)
    except Exception as e:
        logger.warning("[VAPI_END_CALL_ERROR] id=%s error=%s", call_id, e)
        return False


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    import hmac
    expected = hmac.new(secret.encode(), payload, "sha256").hexdigest()
    return hmac.compare_digest(expected, signature)
