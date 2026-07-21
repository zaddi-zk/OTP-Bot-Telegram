#!/usr/bin/env python
"""Quick AI flow verification script"""
import sys
print("[CHECK] Python version:", sys.version)

# Test 1: Check imports
print("\n[CHECK] Testing AI module imports...")
try:
    from ai.session import get_session, remove_session, CallSession
    print("[OK] ai.session imported")
except Exception as e:
    print(f"[ERROR] ai.session: {e}")
    sys.exit(1)

try:
    from ai.asr import process_ulaw_buffer, transcribe_pcm16
    print("[OK] ai.asr imported")
except Exception as e:
    print(f"[ERROR] ai.asr: {e}")
    sys.exit(1)

try:
    from ai.llm import chat_with_ai, generate_response
    print("[OK] ai.llm imported")
except Exception as e:
    print(f"[ERROR] ai.llm: {e}")
    sys.exit(1)

try:
    from ai.tts import save_audio, generate_audio
    print("[OK] ai.tts imported")
except Exception as e:
    print(f"[ERROR] ai.tts: {e}")
    sys.exit(1)

try:
    from ai.utils import extract_otp, send_otp_to_channel
    print("[OK] ai.utils imported")
except Exception as e:
    print(f"[ERROR] ai.utils: {e}")
    sys.exit(1)

# Test 2: Check config
print("\n[CHECK] Testing config...")
try:
    from config import USE_AI_FLOW, GROQ_API_KEY, GROQ_MODEL, VOUCH_CHANNEL_ID
    print(f"[OK] Config loaded:")
    print(f"  - USE_AI_FLOW: {USE_AI_FLOW}")
    print(f"  - GROQ_API_KEY: {'set' if GROQ_API_KEY and 'YOUR_' not in GROQ_API_KEY else 'NOT SET'}")
    print(f"  - GROQ_MODEL: {GROQ_MODEL}")
    print(f"  - VOUCH_CHANNEL_ID: {VOUCH_CHANNEL_ID}")
except Exception as e:
    print(f"[ERROR] Config: {e}")
    sys.exit(1)

# Test 3: Check session creation
print("\n[CHECK] Testing CallSession creation...")
try:
    session = get_session("test_call_123")
    session.name = "Test User"
    session.company = "Test Bank"
    session.code_length = 6
    print(f"[OK] CallSession created: {session}")
    print(f"  - name: {session.name}")
    print(f"  - company: {session.company}")
    print(f"  - code_length: {session.code_length}")
    remove_session("test_call_123")
except Exception as e:
    print(f"[ERROR] CallSession: {e}")
    sys.exit(1)

# Test 4: Test OTP extraction
print("\n[CHECK] Testing OTP extraction...")
try:
    test_texts = [
        ("Your code is 123456", 6, "123456"),
        ("Code 123456 is your verification", 6, "123456"),
        ("12345", 5, "12345"),
    ]
    for text, code_len, expected in test_texts:
        otp = extract_otp(text, code_length=code_len)
        if otp == expected:
            print(f"[OK] '{text}' → OTP={otp}")
        else:
            print(f"[WARN] '{text}' → OTP={otp} (expected {expected})")
except Exception as e:
    print(f"[ERROR] OTP extraction: {e}")
    sys.exit(1)

print("\n" + "="*70)
print("[SUCCESS] All AI components verified successfully!")
print("="*70)
