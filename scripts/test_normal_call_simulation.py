"""
Simple simulation for Normal Call AI flow.
Runs without Twilio by calling LLM, OTP extractor, and TTS save routines.
Prints results and basic heuristics to check on-topic behavior.
"""
import os
import logging
from ai.session import get_session
from ai.llm import chat_with_ai, generate_response
from ai.utils import extract_otp
from ai.tts import save_audio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_sim")

def run_simulation(ollama_check_only=False):
    session = get_session("SIM_CALL_001")
    session.name = "John"
    session.company = "Example Bank"
    session.voice_id = "default"
    session.emotion = "neutral"
    session.chat_id = None
    session.code_length = 6
    session.custom_script = None
    session.call_type = "normal"

    # Simulated customer input sequence
    customer_utterances = [
        "Hello, I'm John.",
        "I pressed 1.",
        "The verification code is 123456.",
    ]

    print("--- Simulation start ---")

    for i, utt in enumerate(customer_utterances, 1):
        print(f"\n[Customer] ({i}): {utt}")
        try:
            # Use chat_with_ai to get agent response
            resp = chat_with_ai(utt, session, system_prompt=None, call_type=session.call_type, emotion=session.emotion)
            print(f"[Agent] Response: {resp}")

            # Save TTS audio (will use ElevenLabs if key present, otherwise create placeholder filename)
            fname = save_audio(session.call_sid, resp, voice_id=session.voice_id)
            print(f"[TTS] Saved audio filename: {fname} (exists={os.path.exists(os.path.join('audio', session.call_sid, fname))})")

        except Exception as e:
            print(f"[ERROR] chat_with_ai failed: {e}")

    # OTP extraction test
    sample_text = "The verification code is 123456"
    otp = extract_otp(sample_text, code_length=session.code_length)
    print(f"\n[OTP] Extracted OTP from sample: {otp}")

    # Quick Ollama availability check
    try:
        test_resp = generate_response("Hello","", system_prompt=None)
        print(f"\n[OLLAMA] sample response (trimmed): {test_resp[:120]!r}")
    except Exception as e:
        print(f"[OLLAMA] generate_response error: {e}")

    print('\n--- Simulation complete ---')

if __name__ == '__main__':
    run_simulation()
