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
    BOT_TOKEN, VAPI_API_KEY, VAPI_SIP_PHONE_NUMBER_ID, ASTERISK_TRUNK, ASTERISK_CLI_DIR,
    NGROK_URL, MAIN_CHANNEL_ID, BACKUP_CHANNEL_ID, OWNER_ID,
    LIVE_LISTEN_SECRET
)

def check_critical_vars():
    """Check that critical environment variables are set."""
    print("\n" + "="*70)
    print("🔍 RAILWAY PRE-FLIGHT CHECK")
    print("="*70)
    
    checks = {
        "BOT_TOKEN": BOT_TOKEN,
        "VAPI_API_KEY": VAPI_API_KEY,
        "VAPI_SIP_PHONE_NUMBER_ID": VAPI_SIP_PHONE_NUMBER_ID,
        "ASTERISK_TRUNK": ASTERISK_TRUNK,
        "ASTERISK_CLI_DIR": ASTERISK_CLI_DIR,
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
        print("  2. VAPI_API_KEY")
        print("  3. VAPI_SIP_PHONE_NUMBER_ID")
        print("  4. ASTERISK_TRUNK")
        print("  5. ASTERISK_CLI_DIR")
        print("  6. NGROK_URL")
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
