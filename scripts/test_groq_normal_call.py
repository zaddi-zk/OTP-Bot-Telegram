"""
Test Normal Call flow with Groq API (production LLM).
Tests: conversation flow, OTP extraction, TTS integration.
"""
import os
import sys
import logging

# Add project root to path
sys.path.insert(0, os.getcwd())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_groq_normal_call")

from ai.session import get_session
from ai.llm import chat_with_ai, generate_response
from ai.utils import extract_otp
from ai.tts import save_audio
from config import GROQ_API_KEY, ELEVENLABS_API_KEY, DEFAULT_ELEVENLABS_VOICE_ID

def test_normal_call_with_groq():
    """Simulate a 9-step Normal Call flow with Groq."""
    
    # Check API keys
    print("\n" + "="*70)
    print("NORMAL CALL TEST (GROQ API)")
    print("="*70)
    
    if not GROQ_API_KEY or "YOUR_" in GROQ_API_KEY:
        print("❌ GROQ_API_KEY not configured!")
        print("   Set GROQ_API_KEY in env or conf/settings.txt")
        return False
    
    if not DEFAULT_ELEVENLABS_VOICE_ID:
        print("⚠️  DEFAULT_ELEVENLABS_VOICE_ID not set, TTS may fail")
    
    print("✅ GROQ_API_KEY configured")
    print(f"✅ Voice ID: {DEFAULT_ELEVENLABS_VOICE_ID}")
    
    # Create session
    session = get_session("TEST_GROQ_001")
    session.name = "Sarah"
    session.company = "ABC Bank"
    session.voice_id = DEFAULT_ELEVENLABS_VOICE_ID
    session.emotion = "calm"
    session.chat_id = None
    session.code_length = 6
    session.custom_script = None
    session.call_type = "normal"
    
    print(f"\nSession created: {session.call_sid}")
    print(f"Customer: {session.name}")
    print(f"Bank: {session.company}")
    
    # Simulate customer utterances (9-step flow)
    customer_utterances = [
        "Hello?",
        "Yes, hi",
        "I pressed 1",
        "The code is 123456",
    ]
    
    print("\n" + "-"*70)
    print("CONVERSATION FLOW")
    print("-"*70)
    
    for i, utt in enumerate(customer_utterances, 1):
        print(f"\n[{i}] CUSTOMER: {utt}")
        
        try:
            # Get AI response via Groq
            resp = chat_with_ai(utt, session, call_type=session.call_type, emotion=session.emotion)
            print(f"    AI (Groq): {resp}")
            
            # Try to generate TTS audio
            fname = save_audio(session.call_sid, resp, voice_id=session.voice_id)
            audio_path = os.path.join("audio", session.call_sid, fname)
            audio_exists = os.path.exists(audio_path)
            print(f"    TTS: {fname} (exists={audio_exists})")
            
        except Exception as e:
            print(f"    ❌ Error: {e}")
            return False
    
    # Test OTP extraction
    sample_text = "The verification code is 123456"
    otp = extract_otp(sample_text, code_length=6)
    print(f"\n[OTP] Extracted from sample: {otp}")
    if otp != "123456":
        print(f"❌ OTP extraction failed! Got '{otp}', expected '123456'")
        return False
    print("✅ OTP extraction working")
    
    # Summary
    print("\n" + "="*70)
    print("CONVERSATION HISTORY")
    print("="*70)
    for msg in session.history:
        print(f"{msg['role'].upper()}: {msg['content']}")
    
    print("\n" + "="*70)
    print("✅ NORMAL CALL TEST PASSED")
    print("="*70)
    return True

if __name__ == "__main__":
    success = test_normal_call_with_groq()
    sys.exit(0 if success else 1)
