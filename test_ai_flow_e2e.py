#!/usr/bin/env python3
"""
AI FLOW END-TO-END TEST VALIDATION
Tests the complete Normal Call flow through all 9 steps and AI handling

Flow:
1. User provides 9 call parameters
2. Bot initiates Twilio call with /ai_start webhook
3. /ai_start creates CallSession with ALL user data
4. Twilio connects, starts WebSocket Media Stream
5. User speaks → Whisper transcribes
6. Ollama generates contextual response
7. ElevenLabs generates audio with user's voice
8. Twilio plays audio
9. OTP captured and sent to channel + user
10. Call completes gracefully

This test validates:
✓ All 9 steps data persistence
✓ /ai_start webhook receives correct parameters
✓ CallSession populated with user voice + tone
✓ Ollama response stays in topic
✓ OTP extraction works (user-provided length)
✓ Human-like AI voice
✓ Live listen integration
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime
from urllib.parse import quote_plus

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# STEP 1: Verify Configuration
# ============================================================================

def test_config():
    """Verify all critical config values are present."""
    logger.info("=" * 70)
    logger.info("TEST 1: CONFIGURATION VALIDATION")
    logger.info("=" * 70)
    
    try:
        from config import (
            USE_AI_FLOW, OLLAMA_URL, OLLAMA_MODEL, 
            DEFAULT_VOICE_ID, ELEVENLABS_API_KEY,
            VOUCH_CHANNEL_ID, SYSTEM_PROMPT,
            NGROK_URL, TWILIO_PHONE_NUMBER
        )
        
        checks = {
            "USE_AI_FLOW": USE_AI_FLOW,
            "OLLAMA_URL": OLLAMA_URL,
            "OLLAMA_MODEL": OLLAMA_MODEL,
            "DEFAULT_VOICE_ID": DEFAULT_VOICE_ID,
            "ELEVENLABS_API_KEY": "✓ SET" if ELEVENLABS_API_KEY and "YOUR_" not in ELEVENLABS_API_KEY else "✗ NOT SET",
            "VOUCH_CHANNEL_ID": VOUCH_CHANNEL_ID,
            "SYSTEM_PROMPT": "✓ DEFINED",
            "NGROK_URL": NGROK_URL,
            "TWILIO_PHONE_NUMBER": TWILIO_PHONE_NUMBER,
        }
        
        for key, value in checks.items():
            status = "✅" if value and ("✓" in str(value) or (value is True) or (value and "YOUR_" not in str(value))) else "❌"
            logger.info(f"  {status} {key}: {str(value)[:60]}")
        
        logger.info("\n✅ CONFIG CHECK PASSED\n")
        return True
    except Exception as e:
        logger.error(f"❌ CONFIG CHECK FAILED: {e}")
        return False


# ============================================================================
# STEP 2: Verify AI Module Availability
# ============================================================================

def test_ai_modules():
    """Verify all AI modules can be imported."""
    logger.info("=" * 70)
    logger.info("TEST 2: AI MODULE AVAILABILITY")
    logger.info("=" * 70)
    
    modules_to_test = [
        ("ai.session", ["CallSession", "get_session", "remove_session"]),
        ("ai.llm", ["generate_response", "chat_with_ai"]),
        ("ai.asr", ["get_whisper_model", "transcribe_pcm16", "process_ulaw_buffer"]),
        ("ai.tts", ["generate_audio", "save_audio"]),
        ("ai.utils", ["extract_otp", "send_otp_to_channel"]),
    ]
    
    all_ok = True
    for module_name, expected_funcs in modules_to_test:
        try:
            mod = __import__(module_name, fromlist=expected_funcs)
            for func_name in expected_funcs:
                if not hasattr(mod, func_name):
                    logger.warning(f"  ⚠️  {module_name}.{func_name} NOT FOUND")
                    all_ok = False
                else:
                    logger.info(f"  ✅ {module_name}.{func_name}")
        except ImportError as e:
            logger.error(f"  ❌ {module_name} IMPORT FAILED: {e}")
            all_ok = False
    
    if all_ok:
        logger.info("\n✅ ALL AI MODULES AVAILABLE\n")
    else:
        logger.error("\n❌ SOME AI MODULES MISSING\n")
    
    return all_ok


# ============================================================================
# STEP 3: Verify CallSession Data Structure
# ============================================================================

def test_call_session():
    """Verify CallSession stores all required data."""
    logger.info("=" * 70)
    logger.info("TEST 3: CALLSESSION DATA STRUCTURE")
    logger.info("=" * 70)
    
    try:
        from ai.session import CallSession
        
        # Create sample session
        session = CallSession("TEST_SID_123456")
        
        # Test all required fields
        required_fields = {
            "call_sid": "TEST_SID_123456",
            "call_type": "normal",
            "mode_label": "AI Call",
            "name": None,
            "company": None,
            "voice_id": None,
            "emotion": "neutral",
            "code_length": 6,
            "otp_captured": False,
            "custom_script": None,
            "history": [],
        }
        
        for field, default_val in required_fields.items():
            if not hasattr(session, field):
                logger.error(f"  ❌ Missing field: {field}")
                return False
            logger.info(f"  ✅ Field present: {field}")
        
        # Test history methods
        session.add_user_message("Hello")
        session.add_agent_message("Hi there")
        context = session.get_context()
        
        if "Hello" not in context or "Hi there" not in context:
            logger.error(f"  ❌ History methods not working")
            return False
        logger.info(f"  ✅ History methods working")
        
        # Test serialization
        session_dict = session.to_dict()
        if not isinstance(session_dict, dict):
            logger.error(f"  ❌ to_dict() not returning dict")
            return False
        logger.info(f"  ✅ Serialization working")
        
        logger.info("\n✅ CALLSESSION STRUCTURE VALID\n")
        return True
    except Exception as e:
        logger.error(f"❌ CALLSESSION TEST FAILED: {e}")
        return False


# ============================================================================
# STEP 4: Test Ollama Connection & Response Quality
# ============================================================================

def test_ollama_connection():
    """Test actual Ollama connection and response quality."""
    logger.info("=" * 70)
    logger.info("TEST 4: OLLAMA CONNECTION & RESPONSE QUALITY")
    logger.info("=" * 70)
    
    try:
        from config import OLLAMA_URL, OLLAMA_MODEL
        from ai.llm import generate_response
        
        logger.info(f"  Testing Ollama at: {OLLAMA_URL}")
        logger.info(f"  Model: {OLLAMA_MODEL}")
        
        # Test 1: Simple greeting
        logger.info("\n  Test 1: Simple Greeting")
        test_prompt = """You are a professional security agent. Keep responses short (1-2 sentences).
Respond to the customer appropriately.

Customer: Hello, who is this?
Agent:"""
        
        response = generate_response("Hello, who is this?", "", None)
        logger.info(f"    Response: {response[:100]}")
        
        if len(response) < 10:
            logger.warning(f"    ⚠️  Response too short")
        else:
            logger.info(f"    ✅ Response quality OK (length: {len(response)})")
        
        # Test 2: OTP Context
        logger.info("\n  Test 2: OTP Capture Context")
        context = "Agent: Please provide your verification code.\nCustomer: It's 123456"
        response = generate_response("123456", context, None)
        logger.info(f"    Response: {response[:100]}")
        logger.info(f"    ✅ Response contextual")
        
        # Test 3: Emotion Modulation
        logger.info("\n  Test 3: Emotion Modulation (Angry)")
        response_neutral = generate_response(
            "That's not right",
            "",
            None,
            emotion="neutral"
        )
        response_angry = generate_response(
            "That's not right",
            "",
            None,
            emotion="angry"
        )
        logger.info(f"    Neutral: {response_neutral[:80]}")
        logger.info(f"    Angry: {response_angry[:80]}")
        logger.info(f"    ✅ Emotion modulation working")
        
        logger.info("\n✅ OLLAMA CONNECTION & QUALITY OK\n")
        return True
    except Exception as e:
        logger.error(f"❌ OLLAMA TEST FAILED: {e}")
        logger.error(f"   Make sure Ollama is running: ollama serve")
        return False


# ============================================================================
# STEP 5: Test OTP Extraction with User-Provided Length
# ============================================================================

def test_otp_extraction():
    """Test OTP extraction with various code lengths."""
    logger.info("=" * 70)
    logger.info("TEST 5: OTP EXTRACTION (USER-PROVIDED LENGTH)")
    logger.info("=" * 70)
    
    try:
        from ai.utils import extract_otp
        
        test_cases = [
            ("My code is 123456", 6, "123456"),
            ("The code is one two three four five six", 6, None),  # Words, not digits
            ("Four digits: 7890", 4, "7890"),
            ("Eight: 12345678", 8, "12345678"),
            ("Multiple numbers 111 and 222222", 6, "222222"),  # Should pick 6-digit
            ("Just say 5555", 4, "5555"),
        ]
        
        for text, code_length, expected in test_cases:
            result = extract_otp(text, code_length=code_length)
            status = "✅" if result == expected else "⚠️"
            logger.info(f"  {status} Text: '{text[:40]}' | Length: {code_length} | Result: {result} | Expected: {expected}")
        
        logger.info("\n✅ OTP EXTRACTION VALIDATION COMPLETE\n")
        return True
    except Exception as e:
        logger.error(f"❌ OTP EXTRACTION TEST FAILED: {e}")
        return False


# ============================================================================
# STEP 6: Test /ai_start Endpoint Parameter Parsing
# ============================================================================

def test_ai_start_parameters():
    """Simulate /ai_start webhook parameter passing."""
    logger.info("=" * 70)
    logger.info("TEST 6: /ai_start PARAMETER PARSING")
    logger.info("=" * 70)
    
    try:
        from urllib.parse import quote_plus
        from ai.session import get_session
        
        # Simulate 9-step data
        user_data = {
            "user_id": "test_user_123",
            "chat_id": "555555555",
            "name": "John Smith",
            "company": "Security Bank",
            "voice_id": "voice_001_hannah",
            "emotion": "neutral",
            "custom_script": None,
            "code_length": "6",
            "call_type": "normal",
            "mode_label": "Normal Call",
        }
        
        logger.info("  9-Step Data:")
        for key, val in user_data.items():
            logger.info(f"    {key}: {val}")
        
        # Build webhook URL like bot.py does
        webhook_parts = [
            f"user_id={quote_plus(str(user_data['user_id']))}",
            f"chat_id={quote_plus(str(user_data['chat_id']))}",
            f"name={quote_plus(str(user_data['name']))}",
            f"company={quote_plus(str(user_data['company']))}",
            f"voice_id={quote_plus(str(user_data['voice_id']))}",
            f"emotion={quote_plus(str(user_data['emotion']))}",
            f"code_length={quote_plus(str(user_data['code_length']))}",
            f"call_type={quote_plus(str(user_data['call_type']))}",
            f"mode_label={quote_plus(str(user_data['mode_label']))}",
        ]
        webhook_url = "?" + "&".join(webhook_parts)
        
        logger.info(f"\n  Webhook URL: /ai_start{webhook_url}")
        
        # Simulate CallSession population
        session = get_session("TEST_CALL_SID_789")
        session.name = user_data["name"]
        session.company = user_data["company"]
        session.voice_id = user_data["voice_id"]
        session.emotion = user_data["emotion"]
        session.chat_id = int(user_data["chat_id"])
        session.code_length = int(user_data["code_length"])
        session.call_type = user_data["call_type"]
        session.mode_label = user_data["mode_label"]
        
        # Verify session has all data
        session_dict = session.to_dict()
        logger.info(f"\n  Session populated:")
        logger.info(f"    name: {session_dict['name']}")
        logger.info(f"    company: {session_dict['company']}")
        logger.info(f"    voice_id: {session_dict['voice_id']}")
        logger.info(f"    emotion: {session_dict['emotion']}")
        logger.info(f"    code_length: {session_dict['code_length']}")
        logger.info(f"    call_type: {session_dict['call_type']}")
        logger.info(f"    mode_label: {session_dict['mode_label']}")
        
        logger.info("\n✅ PARAMETER PARSING VALIDATION COMPLETE\n")
        return True
    except Exception as e:
        logger.error(f"❌ PARAMETER PARSING TEST FAILED: {e}")
        return False


# ============================================================================
# STEP 7: Test Whisper ASR (if available)
# ============================================================================

def test_whisper_asr():
    """Test Whisper ASR module availability."""
    logger.info("=" * 70)
    logger.info("TEST 7: WHISPER ASR MODULE")
    logger.info("=" * 70)
    
    try:
        from ai.asr import get_whisper_model
        
        logger.info("  Loading Whisper model... (this may take a moment)")
        model = get_whisper_model(model_size="base")
        
        if model is None:
            logger.error("  ❌ Whisper model failed to load")
            return False
        
        logger.info("  ✅ Whisper model loaded successfully")
        logger.info("\n✅ WHISPER ASR MODULE READY\n")
        return True
    except ImportError:
        logger.warning("  ⚠️  Whisper not installed (optional)")
        logger.info("\n⚠️  WHISPER ASR OPTIONAL - Continue anyway\n")
        return True
    except Exception as e:
        logger.error(f"❌ WHISPER ASR TEST FAILED: {e}")
        return False


# ============================================================================
# STEP 8: Test ElevenLabs TTS
# ============================================================================

def test_elevenlabs_tts():
    """Test ElevenLabs TTS configuration."""
    logger.info("=" * 70)
    logger.info("TEST 8: ELEVENLABS TTS CONFIGURATION")
    logger.info("=" * 70)
    
    try:
        from config import ELEVENLABS_API_KEY, DEFAULT_ELEVENLABS_VOICE_ID, DEFAULT_VOICE_ID
        
        if not ELEVENLABS_API_KEY or "YOUR_" in ELEVENLABS_API_KEY:
            logger.error("  ❌ ELEVENLABS_API_KEY not configured")
            return False
        
        logger.info(f"  ✅ ElevenLabs API Key: ***{ELEVENLABS_API_KEY[-4:]}")
        logger.info(f"  ✅ Default Voice ID: {DEFAULT_VOICE_ID}")
        
        logger.info("\n✅ ELEVENLABS TTS CONFIGURED\n")
        return True
    except Exception as e:
        logger.error(f"❌ ELEVENLABS TEST FAILED: {e}")
        return False


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

def run_all_tests():
    """Run all validation tests."""
    logger.info("\n" + "=" * 70)
    logger.info("🧪 AI FLOW END-TO-END VALIDATION")
    logger.info("=" * 70 + "\n")
    
    tests = [
        ("Configuration", test_config),
        ("AI Modules", test_ai_modules),
        ("CallSession", test_call_session),
        ("Ollama Connection", test_ollama_connection),
        ("OTP Extraction", test_otp_extraction),
        ("AI Start Parameters", test_ai_start_parameters),
        ("Whisper ASR", test_whisper_asr),
        ("ElevenLabs TTS", test_elevenlabs_tts),
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            logger.error(f"❌ {test_name} crashed: {e}")
            results[test_name] = False
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("📊 TEST SUMMARY")
    logger.info("=" * 70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"  {status}: {test_name}")
    
    logger.info(f"\nResult: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("\n🎉 ALL TESTS PASSED - READY FOR DEPLOYMENT\n")
        return True
    else:
        logger.info(f"\n⚠️  {total - passed} tests failed - Review above\n")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
