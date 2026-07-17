#!/usr/bin/env python3
"""
Railway Deployment Pre-Flight Check
Verifies all critical configuration before starting the bot.
"""
import sys
import os
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    BOT_TOKEN, ACCOUNT_SID, AUTH_TOKEN, TWILIO_PHONE_NUMBER,
    NGROK_URL, MAIN_CHANNEL_ID, BACKUP_CHANNEL_ID, OWNER_ID,
    ELEVENLABS_API_KEY, LIVE_LISTEN_SECRET
)

TWILIO_ACCOUNT_SID = ACCOUNT_SID

def check_critical_vars():
    """Check that critical environment variables are set."""
    print("\n" + "="*70)
    print("🔍 RAILWAY PRE-FLIGHT CHECK")
    print("="*70)
    
    checks = {
        "BOT_TOKEN": BOT_TOKEN,
        "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
        "TWILIO_AUTH_TOKEN": AUTH_TOKEN,
        "TWILIO_PHONE_NUMBER": TWILIO_PHONE_NUMBER,
        "NGROK_URL": NGROK_URL,
    }
    
    all_ok = True
    
    for name, value in checks.items():
        if not value or "YOUR_" in str(value):
            print(f"❌ {name:30s} MISSING (placeholder)")
            all_ok = False
        else:
            # Show first 10 chars only for secrets
            if "TOKEN" in name or "KEY" in name:
                display = str(value)[:10] + "***"
            else:
                display = str(value)
            print(f"✅ {name:30s} {display}")
    
    # Optional checks
    print("\n" + "-"*70)
    print("📋 Optional Configuration:")
    print("-"*70)
    
    optional = {
        "MAIN_CHANNEL_ID": MAIN_CHANNEL_ID,
        "BACKUP_CHANNEL_ID": BACKUP_CHANNEL_ID,
        "OWNER_ID": OWNER_ID,
        "ELEVENLABS_API_KEY": ELEVENLABS_API_KEY,
        "LIVE_LISTEN_SECRET": LIVE_LISTEN_SECRET,
    }
    
    for name, value in optional.items():
        if value:
            if "KEY" in name:
                display = str(value)[:10] + "***"
            else:
                display = str(value)
            print(f"✅ {name:30s} {display}")
        else:
            print(f"⚠️  {name:30s} NOT SET (optional)")
    
    print("\n" + "="*70)
    
    if all_ok:
        print("✅ ALL CRITICAL VARIABLES SET - BOT READY TO START")
        print("="*70 + "\n")
        return True
    else:
        print("❌ CRITICAL VARIABLES MISSING - BOT CANNOT START (strict mode)")
        print("="*70)
        print("\n⚠️  Set these in Railway → Settings → Variables:")
        print("  1. BOT_TOKEN")
        print("  2. TWILIO_ACCOUNT_SID")
        print("  3. TWILIO_AUTH_TOKEN")
        print("  4. TWILIO_PHONE_NUMBER")
        print("  5. NGROK_URL")
        print("\n")
        # Allow deployments to continue unless explicit strict mode is enabled
        strict = os.getenv("RAILWAY_STRICT", "0") in ("1", "true", "yes")
        if strict:
            print("Exiting due to RAILWAY_STRICT=true")
            return False
        else:
            print("Continuing deployment (RAILWAY_STRICT not set). Set RAILWAY_STRICT=1 to enforce checks.")
            return True

if __name__ == "__main__":
    if check_critical_vars():
        sys.exit(0)
    else:
        sys.exit(1)
