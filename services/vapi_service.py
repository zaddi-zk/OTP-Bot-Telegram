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


def create_call(
    customer_number: str,
    customer_name: str,
    assistant_overrides: Optional[dict] = None,
    metadata: Optional[dict] = None,
    webhook_url: Optional[str] = None,
) -> Optional[str]:
    """Create an outbound call via Vapi.

    Args:
        customer_number: Phone number in E.164 format.
        customer_name: Display name for the customer.
        assistant_overrides: Inline overrides for the assistant config.
        metadata: Custom metadata forwarded to webhooks.
        webhook_url: URL for Vapi to send call events.

    Returns:
        Call ID (Vapi call id) on success, None on failure.
    """
    base_url = build_public_base_url()
    webhook_url = webhook_url or f"{base_url.rstrip('/')}/vapi/webhook" if base_url else None

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
        payload["assistantOverrides"] = assistant_overrides

    if metadata:
        payload["metadata"] = metadata

    if webhook_url:
        payload["webhookUrl"] = webhook_url

    try:
        logger.info("VAPI OVERRIDES: %s", json.dumps(payload.get("assistantOverrides", {}), indent=2))
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
