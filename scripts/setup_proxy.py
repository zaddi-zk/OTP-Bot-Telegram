"""
scripts/setup_proxy.py — one-time Twilio Proxy Service bootstrap.

Idempotent: safe to re-run any number of times.

  * Finds (or creates) a Proxy Service named "TelegramBot-Proxy".
  * Adds the 7 purchased numbers to it (skipping ones already registered).
  * Prints the PROXY_SERVICE_SID to put in your .env.

Usage:
    python scripts/setup_proxy.py

Env required:
    TWILIO_ACCOUNT_SID   (or ACCOUNT_SID)
    TWILIO_AUTH_TOKEN    (or AUTH_TOKEN)
Optional:
    PROXY_CALLBACK_URL   (used only at service creation)
"""

import os
import sys

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

SERVICE_NAME = "TelegramBot-Proxy"
DEFAULT_TTL = 3600

# The 7 numbers owned on this Twilio account (verified active / in-use).
POOL = [
    "+19852848980",   # 1
    "+17623566007",   # 2
    "+14247881997",   # 3
    "+12405698072",   # 4
    "+19897877518",   # 5
    "+13073572084",   # 6  (new)
    "+19129147157",   # 7  (new)
]


def _env(name, alt=None):
    value = os.environ.get(name) or os.environ.get(alt or "")
    return (value or "").strip()


def main():
    account_sid = _env("TWILIO_ACCOUNT_SID", "ACCOUNT_SID")
    auth_token = _env("TWILIO_AUTH_TOKEN", "AUTH_TOKEN")
    if not account_sid or not auth_token or "YOUR_" in account_sid or "YOUR_" in auth_token:
        print("❌ TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN must be set.")
        sys.exit(1)

    client = Client(account_sid, auth_token)

    # 1) Find or create the Proxy Service (idempotent).
    service = None
    for existing in client.proxy.services.list():
        if existing.unique_name == SERVICE_NAME:
            service = existing
            break
    if service is None:
        callback_url = _env("PROXY_CALLBACK_URL", "PROXY_CALLBACK_URL")
        service = client.proxy.services.create(
            unique_name=SERVICE_NAME,
            default_ttl=DEFAULT_TTL,
            callback_url=callback_url,
        )
        print(f"✅ Created Proxy Service: {SERVICE_NAME} ({service.sid})")
    else:
        print(f"✅ Found existing Proxy Service: {SERVICE_NAME} ({service.sid})")

    service_sid = service.sid

    # 2) Register the numbers that are not already attached.
    existing = {
        str(pn.phone_number) for pn in client.proxy.services(service_sid).phone_numbers.list()
    }
    for num in POOL:
        if num in existing:
            print(f"  • already present : {num}")
            continue
        try:
            client.proxy.services(service_sid).phone_numbers.create(
                phone_number=num,
                is_reserved=False,
            )
            print(f"  • added           : {num}")
        except TwilioRestException as exc:
            # A number already claimed by another service/app still works as a
            # caller id via client.calls.create; it just can't be reserved here.
            print(f"  ⚠ skip {num} (Proxy add failed): {exc}")

    print("\nAdd this to your .env:")
    print(f"PROXY_SERVICE_SID={service_sid}")
    print(
        "PROXY_POOL_NUMBERS="
        + ",".join(POOL)
        + "\nPROXY_POOL_ENABLED=true"
    )


if __name__ == "__main__":
    main()