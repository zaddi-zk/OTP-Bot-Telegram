#!/usr/bin/env python3
"""
Quick diagnostic: Test if webhook setup is working correctly
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment
from dotenv import load_dotenv
load_dotenv()

from config import BOT_TOKEN, NGROK_URL
from bot import (
    get_telegram_webhook_url, set_telegram_webhook, 
    get_runtime_mode, bot, USE_WEBHOOK
)

print("\n" + "="*70)
print("🔍 WEBHOOK SETUP DIAGNOSTIC")
print("="*70)

print(f"\n1️⃣  BOT TOKEN: {'✅ SET' if BOT_TOKEN and 'YOUR_' not in BOT_TOKEN else '❌ NOT SET'}")
print(f"2️⃣  NGROK_URL: {NGROK_URL}")
print(f"3️⃣  USE_WEBHOOK: {BOT_USE_WEBHOOK}")
print(f"4️⃣  Runtime Mode: {get_runtime_mode(bot)}")

print(f"\n5️⃣  Telegram Webhook URL: {get_telegram_webhook_url()}")

if bot is None:
    print("\n❌ BOT IS NONE - Cannot set webhook")
    sys.exit(1)

print("\n6️⃣  Attempting to set webhook...")
result = set_telegram_webhook()
print(f"     Result: {'✅ SUCCESS' if result else '❌ FAILED'}")

print("\n" + "="*70 + "\n")
