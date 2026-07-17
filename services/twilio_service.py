"""
services/twilio_service.py

Twilio service with async AMD support.
"""

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from config import ACCOUNT_SID, AUTH_TOKEN, TWILIO_PHONE_NUMBER, NGROK_URL
from core.files import ensure_user_path, user_conf_path, write_user_file

logger = logging.getLogger(__name__)

_twilio_client = None
_call_executor = ThreadPoolExecutor(
    max_workers=max(4, min(16, (os.cpu_count() or 1) * 2)),
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
              **kwargs) -> Optional[str]:
    """
    Place a Twilio call with optional async AMD.
    Returns the Call SID on success, otherwise None.
    """
    client = get_twilio_client()
    if not client:
        return None

    from_number = from_number or TWILIO_PHONE_NUMBER
    webhook_url = webhook_url or f"{NGROK_URL}/voice?user_id={user_id}"
    if async_amd_status_callback is None:
        async_amd_status_callback = f"{NGROK_URL}/amd_callback"

    # Always include the minimal required params. Recording is enforced by callers
    # via `record=True` (default). AMD parameters are only added if explicitly
    # enabled so production behavior can avoid hanging up on machines by default.
    call_params = {
        "to": to,
        "from_": from_number,
        "url": webhook_url,
        "method": "POST",
    }
    # Ensure we receive call lifecycle events and recording notifications
    call_params["status_callback"] = f"{NGROK_URL.rstrip('/')}/twilio/status?user_id={user_id}"
    call_params["status_callback_method"] = "POST"
    call_params["recording_status_callback"] = f"{NGROK_URL.rstrip('/')}/twilio/recording?user_id={user_id}"
    call_params["recording_status_callback_method"] = "POST"
    # If a custom from_number was provided, ensure it's owned by this Twilio account.
    try:
        if from_number and from_number != TWILIO_PHONE_NUMBER:
            try:
                owned = client.incoming_phone_numbers.list(phone_number=from_number)
                if not owned:
                    logger.warning("Provided from_number %s not owned by this Twilio account. Falling back to %s", from_number, TWILIO_PHONE_NUMBER)
                    from_number = TWILIO_PHONE_NUMBER
                    call_params["from_"] = from_number
                else:
                    call_params["from_"] = from_number
            except Exception:
                # If the ownership check fails for any reason, fallback to configured number
                logger.debug("Could not verify ownership of from_number %s; using configured TWILIO_PHONE_NUMBER", from_number)
                from_number = TWILIO_PHONE_NUMBER
                call_params["from_"] = from_number
        else:
            call_params["from_"] = from_number
    except Exception:
        call_params["from_"] = from_number
    # AMD/Answering-Machine-Detection has been disabled; ignore caller requests
    # to include async AMD or machine_detection parameters so calls never
    # include machine/human detection settings.
    if record:
        call_params["record"] = True
        call_params["recording_channels"] = "mono"
        call_params["recording_status_callback_event"] = ["completed"]
    if caller_id and caller_id != from_number:
        logger.warning(
            "Ignoring unsupported Twilio call create parameter 'caller_id'; using from_=%s",
            from_number,
        )

    try:
        # Offload Twilio API call creation to a background thread worker so
        # no heavy blocking network I/O happens in the main request handler.
        call = asyncio.run(asyncio.to_thread(client.calls.create, **call_params))
        logger.info(f"Call created: {call.sid} -> {to}")
        return call.sid
    except TwilioRestException as e:
        logger.error(f"Twilio error: {e}")
        return None
    except Exception as e:
        logger.error(f"Call creation error: {e}")
        return None


async def start_call(to_number, from_number, webhook_url):
    """Initiates an outbound call with non-blocking thread isolation and mandatory recording configuration."""
    client = get_twilio_client()
    if not client:
        logger.error("Twilio client not available for start_call")
        return None

    try:
        call = await asyncio.to_thread(
            client.calls.create,
            to=to_number,
            from_=from_number,
            url=f"{webhook_url}/twilio/voice",
            record=True,
            recording_channels="mono",
            recording_status_callback=f"{webhook_url}/twilio/recording",
            recording_status_callback_event=["completed"],
            method="POST",
        )

        logging.info(f"✅ Outbound call initiated successfully: SID={call.sid}. forced full-call recording: ON.")
        return call.sid

    except Exception as e:
        logging.error(f"❌ Failed to start call via Twilio: {str(e)}")
        return None


def make_call_async(
    to: str,
    from_number: str = None,
    caller_id: str = None,
    webhook_url: str = None,
    user_id: str = "",
    record: bool = True,
    machine_detection: Optional[str] = None,
    async_amd: bool = False,
    async_amd_status_callback: str = None,
    **kwargs,
):
    """Offload Twilio call creation to a background worker so the bot stays responsive."""
    try:
        return _call_executor.submit(
            make_call,
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
    except Exception as exc:
        logger.error("Twilio call dispatch failed: %s", exc, exc_info=True)
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
