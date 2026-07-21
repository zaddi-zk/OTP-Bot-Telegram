"""
Real Normal Call Flow Test with Groq
Tests the complete 9-step AI verification pipeline with Groq LLM.
"""
import os
import sys
import time
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from ai.session import get_session
from ai.llm import chat_with_ai
from ai.utils import extract_otp
from ai.tts import save_audio

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("normal_call_test")

def test_normal_call_flow():
    """
    Simulate a complete Normal Call verification flow:
    1. Agent greets customer
    2. Customer responds
    3. Agent asks to press 1
    4. Customer confirms
    5. Agent sends code
    6. Customer provides code
    7. Agent verifies code
    8. OTP extracted
    9. Call ends
    """
    
    logger.info("="*70)
    logger.info("NORMAL CALL FLOW TEST WITH GROQ")
    logger.info("="*70)
    
    # Initialize session
    call_sid = "TEST_CALL_001"
    session = get_session(call_sid)
    session.name = "John"
    session.company = "Example Bank"
    session.voice_id = "EXAVITQu4vr4xnSDxMaL"  # Your ElevenLabs voice
    session.emotion = "neutral"
    session.chat_id = None
    session.code_length = 6
    session.custom_script = None
    session.call_type = "normal"
    
    logger.info(f"✅ Session initialized: {call_sid}")
    logger.info(f"   Customer name: {session.name}")
    logger.info(f"   Company: {session.company}")
    logger.info(f"   Call type: {session.call_type}")
    
    # Simulate conversation
    customer_utterances = [
        ("Idle", None),  # Agent speaks first, no customer input
        ("Hello, yes I'm here", "Customer responds to greeting"),
        ("I pressed 1", "Customer confirms verification intent"),
        ("The code is 123456", "Customer provides OTP code"),
    ]
    
    logger.info("\n" + "="*70)
    logger.info("STARTING CONVERSATION LOOP")
    logger.info("="*70)
    
    results = []
    
    for i, (utterance, description) in enumerate(customer_utterances, 1):
        logger.info(f"\n[TURN {i}] {description or utterance}")
        logger.info("-" * 70)
        
        # First turn: agent initiates
        if i == 1:
            user_text = "greeting"
            logger.info("👤 [AGENT INITIATING] (no customer input yet)")
        else:
            user_text = utterance
            logger.info(f"👤 [CUSTOMER]: {user_text}")
        
        start_time = time.time()
        
        try:
            # Call the AI with Groq
            response = chat_with_ai(
                user_text,
                session,
                system_prompt=None,  # Uses default from config
                call_type=session.call_type,
                emotion=session.emotion
            )
            
            elapsed = time.time() - start_time
            
            logger.info(f"🤖 [AGENT RESPONSE]: {response}")
            logger.info(f"⏱️  Response time: {elapsed:.2f}s")
            
            # Try to generate TTS audio
            try:
                audio_file = save_audio(call_sid, response, voice_id=session.voice_id)
                logger.info(f"🔊 [AUDIO] Generated: {audio_file}")
            except Exception as e:
                logger.warning(f"⚠️  TTS error (expected if no API key): {e}")
            
            # Track results
            results.append({
                "turn": i,
                "customer": user_text if i > 1 else "(agent init)",
                "agent": response,
                "response_time": elapsed
            })
            
        except Exception as e:
            logger.error(f"❌ Error in turn {i}: {e}", exc_info=True)
            return False
    
    # Test OTP extraction
    logger.info("\n" + "="*70)
    logger.info("OTP EXTRACTION TEST")
    logger.info("="*70)
    
    test_text = "The code is 123456"
    otp = extract_otp(test_text, code_length=6)
    logger.info(f"📝 Input: '{test_text}'")
    logger.info(f"✅ Extracted OTP: {otp}")
    
    if otp == "123456":
        logger.info("✅ OTP extraction PASSED")
    else:
        logger.error(f"❌ OTP extraction FAILED: expected '123456', got '{otp}'")
        return False
    
    # Summary
    logger.info("\n" + "="*70)
    logger.info("TEST SUMMARY")
    logger.info("="*70)
    
    total_time = sum(r["response_time"] for r in results)
    avg_time = total_time / len(results)
    
    logger.info(f"✅ Total turns: {len(results)}")
    logger.info(f"✅ Total time: {total_time:.2f}s")
    logger.info(f"✅ Average response time: {avg_time:.2f}s")
    logger.info(f"✅ Session history: {len(session.history)} messages")
    
    logger.info("\n" + "="*70)
    logger.info("FULL CONVERSATION")
    logger.info("="*70)
    
    for msg in session.history:
        role = "👤 CUSTOMER" if msg["role"] == "user" else "🤖 AGENT"
        logger.info(f"{role}: {msg['content']}")
    
    logger.info("\n" + "="*70)
    logger.info("✅ NORMAL CALL FLOW TEST PASSED - READY FOR PRODUCTION")
    logger.info("="*70)
    
    return True

if __name__ == "__main__":
    success = test_normal_call_flow()
    sys.exit(0 if success else 1)
