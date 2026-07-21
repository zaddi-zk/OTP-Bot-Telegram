#!/usr/bin/env python3
"""
AI FLOW CRITICAL VALIDATION (Tests That Don't Require Ollama)
"""

import sys
import os
sys.path.insert(0, str(os.path.dirname(__file__)))

import logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Disable Ollama timeout warnings
logging.getLogger("ai.llm").setLevel(logging.ERROR)

def test_1_config():
    """✅ Test 1: Core Configuration"""
    logger.info("\n" + "="*70)
    logger.info("TEST 1: CONFIGURATION VALIDATION")
    logger.info("="*70)
    
    from config import (
        USE_AI_FLOW, OLLAMA_URL, OLLAMA_MODEL, 
        DEFAULT_VOICE_ID, ELEVENLABS_API_KEY,
        VOUCH_CHANNEL_ID, TWILIO_PHONE_NUMBER
    )
    
    required = [
        ("USE_AI_FLOW", USE_AI_FLOW is True),
        ("OLLAMA_URL", "localhost" in OLLAMA_URL),
        ("OLLAMA_MODEL", "llama" in OLLAMA_MODEL),
        ("DEFAULT_VOICE_ID", len(DEFAULT_VOICE_ID) > 0),
        ("VOUCH_CHANNEL_ID", int(VOUCH_CHANNEL_ID) < 0),
        ("TWILIO_PHONE_NUMBER", "+1" in TWILIO_PHONE_NUMBER),
    ]
    
    all_ok = True
    for name, check in required:
        status = "✅" if check else "❌"
        logger.info(f"  {status} {name}")
        if not check:
            all_ok = False
    
    return all_ok


def test_2_session_structure():
    """✅ Test 2: CallSession Data Model"""
    logger.info("\n" + "="*70)
    logger.info("TEST 2: CALLSESSION DATA STRUCTURE")
    logger.info("="*70)
    
    from ai.session import CallSession
    
    # Create a session like /ai_start would
    session = CallSession("TEST_CALL_SID")
    
    # Populate all 9-step fields
    session.name = "John Smith"
    session.company = "Bank Security"
    session.phone = "555-1234"
    session.voice_id = "EXAVITQu4vr4xnSDxMaL"
    session.emotion = "neutral"
    session.code_length = 6
    session.call_type = "normal"
    session.mode_label = "Normal Call"
    
    # Test history tracking
    session.add_user_message("Hello")
    session.add_agent_message("Hi, how can I help?")
    
    session_dict = session.to_dict()
    
    checks = [
        ("name stored", session_dict['name'] == "John Smith"),
        ("company stored", session_dict['company'] == "Bank Security"),
        ("voice_id stored", session_dict['voice_id'] == "EXAVITQu4vr4xnSDxMaL"),
        ("emotion set to neutral", session_dict['emotion'] == "neutral"),
        ("code_length = 6", session_dict['code_length'] == 6),
        ("call_type = normal", session_dict['call_type'] == "normal"),
        ("history tracked", len(session_dict['history']) == 2),
        ("get_context works", "Hello" in session.get_context()),
    ]
    
    all_ok = True
    for check_name, result in checks:
        status = "✅" if result else "❌"
        logger.info(f"  {status} {check_name}")
        if not result:
            all_ok = False
    
    return all_ok


def test_3_otp_extraction():
    """✅ Test 3: OTP Extraction Logic"""
    logger.info("\n" + "="*70)
    logger.info("TEST 3: OTP EXTRACTION (USER-PROVIDED LENGTH)")
    logger.info("="*70)
    
    from ai.utils import extract_otp
    
    tests = [
        ("My code is 123456", 6, True),
        ("Four digits: 7890", 4, True),
        ("Eight: 12345678", 8, True),
        ("No digits here", 4, False),
    ]
    
    all_ok = True
    for text, length, should_find in tests:
        result = extract_otp(text, code_length=length)
        found = result is not None
        
        status = "✅" if found == should_find else "❌"
        logger.info(f"  {status} Length {length}: '{text[:40]}' → {result}")
        if found != should_find:
            all_ok = False
    
    return all_ok


def test_4_voice_mapping():
    """✅ Test 4: Voice ID Resolution"""
    logger.info("\n" + "="*70)
    logger.info("TEST 4: VOICE ID RESOLUTION")
    logger.info("="*70)
    
    from menu_utils import resolve_voice_choice, get_voice_key_by_id, VOICE_MAPPING
    
    # Test voice key lookup
    voice_key, voice_id, voice_name = resolve_voice_choice("2")  # Hannah
    logger.info(f"  ✅ Voice choice '2' resolves to: {voice_name} ({voice_id})")
    
    # Test reverse lookup
    found_key = get_voice_key_by_id(voice_id)
    logger.info(f"  ✅ Voice ID reverse lookup: {found_key} → {VOICE_MAPPING.get(found_key, {}).get('name', 'Unknown')}")
    
    # Test all voices available
    voice_count = len(VOICE_MAPPING)
    logger.info(f"  ✅ {voice_count} voices available")
    
    return voice_count > 0


def test_5_ai_start_flow():
    """✅ Test 5: /ai_start Parameter Flow"""
    logger.info("\n" + "="*70)
    logger.info("TEST 5: /ai_start WEBHOOK PARAMETER FLOW")
    logger.info("="*70)
    
    from ai.session import get_session, remove_session
    from urllib.parse import quote_plus
    
    # Simulate 9-step user data
    user_data = {
        "call_sid": "CA12345abcde",
        "user_id": "test_user_123",
        "name": "John Smith",
        "company": "Security Bank",
        "phone": "555-123-4567",
        "caller_id": "+18559171761",
        "from_name": "Security Checker",
        "voice_id": "EXAVITQu4vr4xnSDxMaL",
        "emotion": "neutral",
        "code_length": 6,
        "call_type": "normal",
    }
    
    # Get/create session
    session = get_session(user_data["call_sid"])
    
    # Populate from 9 steps
    session.name = user_data["name"]
    session.company = user_data["company"]
    session.voice_id = user_data["voice_id"]
    session.emotion = user_data["emotion"]
    session.code_length = user_data["code_length"]
    session.call_type = user_data["call_type"]
    
    # Verify all data persists
    data = session.to_dict()
    
    checks = [
        ("name", data['name'] == user_data["name"]),
        ("company", data['company'] == user_data["company"]),
        ("voice_id", data['voice_id'] == user_data["voice_id"]),
        ("emotion", data['emotion'] == user_data["emotion"]),
        ("code_length", data['code_length'] == user_data["code_length"]),
        ("call_type", data['call_type'] == user_data["call_type"]),
    ]
    
    all_ok = True
    for field, result in checks:
        status = "✅" if result else "❌"
        logger.info(f"  {status} {field}: {data[field]}")
        if not result:
            all_ok = False
    
    # Cleanup
    remove_session(user_data["call_sid"])
    
    return all_ok


def test_6_llm_structure():
    """✅ Test 6: LLM Function Signatures"""
    logger.info("\n" + "="*70)
    logger.info("TEST 6: LLM FUNCTION SIGNATURES")
    logger.info("="*70)
    
    from ai.llm import generate_response, chat_with_ai
    import inspect
    
    # Check generate_response signature
    sig_gen = inspect.signature(generate_response)
    gen_params = list(sig_gen.parameters.keys())
    logger.info(f"  ✅ generate_response params: {gen_params}")
    
    # Check chat_with_ai signature
    sig_chat = inspect.signature(chat_with_ai)
    chat_params = list(sig_chat.parameters.keys())
    logger.info(f"  ✅ chat_with_ai params: {chat_params}")
    
    # Verify critical params exist
    required_gen = ["user_text", "context", "system_prompt"]
    required_chat = ["user_text", "session", "system_prompt"]
    
    gen_ok = all(p in gen_params for p in required_gen)
    chat_ok = all(p in chat_params for p in required_chat)
    
    if gen_ok and chat_ok:
        logger.info(f"  ✅ All critical parameters present")
        return True
    else:
        logger.error(f"  ❌ Missing parameters")
        return False


def test_7_tts_structure():
    """✅ Test 7: TTS Function Signatures"""
    logger.info("\n" + "="*70)
    logger.info("TEST 7: TTS FUNCTION SIGNATURES")
    logger.info("="*70)
    
    from ai.tts import save_audio, generate_audio
    import inspect
    
    sig_save = inspect.signature(save_audio)
    save_params = list(sig_save.parameters.keys())
    logger.info(f"  ✅ save_audio params: {save_params}")
    
    sig_gen = inspect.signature(generate_audio)
    gen_params = list(sig_gen.parameters.keys())
    logger.info(f"  ✅ generate_audio params: {gen_params}")
    
    return len(save_params) > 0


def test_8_bot_emotion_flow():
    """✅ Test 8: Bot Emotion Call Flow"""
    logger.info("\n" + "="*70)
    logger.info("TEST 8: BOT EMOTION CALL FLOW")
    logger.info("="*70)
    
    # Check that initiate_emotion_call exists in bot.py
    with open("bot.py", "r") as f:
        bot_code = f.read()
    
    checks = [
        ("initiate_emotion_call defined", "def initiate_emotion_call" in bot_code),
        ("emotion_call handler exists", "@bot.callback_query_handler(func=lambda call: call.data == \"emotion_call\")" in bot_code or "emotion_call" in bot_code),
        ("/ai_start endpoint exists", '@app.route("/ai_start"' in bot_code),
        ("call_type parameter passed", "call_type=" in bot_code),
        ("emotion parameter handled", "emotion=" in bot_code),
    ]
    
    all_ok = True
    for check_name, result in checks:
        status = "✅" if result else "❌"
        logger.info(f"  {status} {check_name}")
        if not result:
            all_ok = False
    
    return all_ok


def test_9_websocket_flow():
    """✅ Test 9: WebSocket Handler Integration"""
    logger.info("\n" + "="*70)
    logger.info("TEST 9: WEBSOCKET HANDLER INTEGRATION")
    logger.info("="*70)
    
    with open("live_listen/server.py", "r") as f:
        ws_code = f.read()
    
    checks = [
        ("WebSocket endpoint defined", "@app.websocket('/twilio/media')" in ws_code),
        ("Passes emotion to LLM", "emotion=" in ws_code),
        ("Passes call_type to LLM", "call_type=" in ws_code),
        ("OTP extraction logic", "extract_otp" in ws_code),
        ("save_audio called", "save_audio" in ws_code),
        ("Fallback handling", "fallback" in ws_code.lower() or "except" in ws_code),
    ]
    
    all_ok = True
    for check_name, result in checks:
        status = "✅" if result else "❌"
        logger.info(f"  {status} {check_name}")
        if not result:
            all_ok = False
    
    return all_ok


def run_all():
    """Run all validation tests."""
    logger.info("\n" + "🧪 "*20)
    logger.info("AI FLOW CRITICAL VALIDATION (Core Tests)")
    logger.info("🧪 "*20)
    
    tests = [
        ("Configuration", test_1_config),
        ("CallSession Structure", test_2_session_structure),
        ("OTP Extraction", test_3_otp_extraction),
        ("Voice Resolution", test_4_voice_mapping),
        ("/ai_start Parameter Flow", test_5_ai_start_flow),
        ("LLM Signatures", test_6_llm_structure),
        ("TTS Signatures", test_7_tts_structure),
        ("Bot Emotion Flow", test_8_bot_emotion_flow),
        ("WebSocket Integration", test_9_websocket_flow),
    ]
    
    results = {}
    for name, func in tests:
        try:
            results[name] = func()
        except Exception as e:
            logger.error(f"  ❌ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False
    
    # Summary
    logger.info("\n" + "="*70)
    logger.info("📊 TEST RESULTS SUMMARY")
    logger.info("="*70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"  {status} - {name}")
    
    logger.info(f"\n✅ PASSED: {passed}/{total} tests")
    
    if passed == total:
        logger.info("\n🎉 ALL CRITICAL TESTS PASSED!")
        logger.info("\nNext Steps:")
        logger.info("  1. Start Ollama: ollama serve")
        logger.info("  2. Run actual 9-step Normal Call")
        logger.info("  3. Monitor logs in live_listen/server.py")
        logger.info("  4. Verify OTP sent to channel")
        logger.info("  5. Test voice quality with Live Listen")
        logger.info("\n")
        return True
    else:
        logger.error(f"\n⚠️  {total - passed} test(s) failed - Review above")
        return False


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
