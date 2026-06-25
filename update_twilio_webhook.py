# scripts/update_twilio_webhook.py
"""
Update Twilio incoming phone number webhook.
Sets the voice webhook URL to point to your bot's /voice endpoint.
Supports updating a specific number or all numbers.
"""
import sys
import logging
from typing import Optional

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from config import ACCOUNT_SID, AUTH_TOKEN, TWILIO_PHONE_NUMBER, NGROK_URL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def update_incoming_number_webhook(
    phone_number: Optional[str] = None,
    voice_url: Optional[str] = None,
    fallback_url: Optional[str] = None,
    update_all: bool = False,
) -> int:
    """
    Update the voice webhook URL for Twilio incoming phone numbers.
    
    Args:
        phone_number: Specific phone number to update (E.164 format)
        voice_url: New voice webhook URL (defaults to NGROK_URL/voice)
        fallback_url: Optional fallback URL for Twilio to use on failure
        update_all: If True, update all incoming numbers (ignores phone_number)
    
    Returns:
        0 on success, 1 on no matching numbers, 2 on error
    """
    if not ACCOUNT_SID or "YOUR_" in ACCOUNT_SID:
        logger.error("Invalid Twilio Account SID. Check your config.")
        return 2
    
    if not AUTH_TOKEN or "YOUR_" in AUTH_TOKEN:
        logger.error("Invalid Twilio Auth Token. Check your config.")
        return 2
    
    if not NGROK_URL or "your-ngrok-url" in NGROK_URL:
        logger.error("Invalid NGROK_URL. Check your config.")
        return 2
    
    # Create Twilio client
    try:
        client = Client(ACCOUNT_SID, AUTH_TOKEN)
        client.api.accounts(ACCOUNT_SID).fetch()  # Test connection
    except TwilioRestException as e:
        logger.error(f"Failed to connect to Twilio: {e}")
        return 2
    
    # Build webhook URL
    if voice_url is None:
        voice_url = f"{NGROK_URL}/voice"
    
    # Fetch numbers to update
    if update_all:
        numbers = client.incoming_phone_numbers.list()
        logger.info(f"Found {len(numbers)} incoming numbers to update")
    else:
        target = phone_number or TWILIO_PHONE_NUMBER
        numbers = client.incoming_phone_numbers.list(phone_number=target)
        if not numbers:
            logger.error(f"No incoming phone number matching '{target}'")
            return 1
        logger.info(f"Found {len(numbers)} number(s) matching '{target}'")
    
    success_count = 0
    fail_count = 0
    
    for num in numbers:
        try:
            update_params = {
                'voice_url': voice_url,
                'voice_method': 'POST'
            }
            if fallback_url:
                update_params['voice_fallback_url'] = fallback_url
                update_params['voice_fallback_method'] = 'POST'
            
            updated = client.incoming_phone_numbers(num.sid).update(**update_params)
            logger.info(f"✅ Updated webhook for {updated.phone_number} -> {voice_url}")
            success_count += 1
        except TwilioRestException as e:
            logger.error(f"❌ Failed to update {num.phone_number} (SID: {num.sid}): {e}")
            fail_count += 1
        except Exception as e:
            logger.error(f"❌ Unexpected error updating {num.phone_number}: {e}")
            fail_count += 1
    
    logger.info(f"Summary: {success_count} updated, {fail_count} failed")
    return 0 if fail_count == 0 else 2


def main():
    """Command-line entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Update Twilio incoming number webhook')
    parser.add_argument('--phone', help='Specific phone number to update (E.164 format)')
    parser.add_argument('--url', help='Custom voice webhook URL (default: NGROK_URL/voice)')
    parser.add_argument('--fallback', help='Optional fallback URL for Twilio')
    parser.add_argument('--all', action='store_true', help='Update all incoming numbers')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without making changes')
    
    args = parser.parse_args()
    
    if args.dry_run:
        logger.info("🧪 Dry run mode - no changes will be made")
        logger.info(f"Would update numbers with webhook: {args.url or f'{NGROK_URL}/voice'}")
        if args.all:
            logger.info("Would update ALL incoming numbers")
        else:
            logger.info(f"Would update numbers matching: {args.phone or TWILIO_PHONE_NUMBER}")
        return 0
    
    return update_incoming_number_webhook(
        phone_number=args.phone,
        voice_url=args.url,
        fallback_url=args.fallback,
        update_all=args.all,
    )


if __name__ == '__main__':
    sys.exit(main())