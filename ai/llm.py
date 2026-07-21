"""
Groq LLM client for production-grade AI responses.
Uses Groq API with llama-3.1-8b-instant for low-latency, high-quality verification calls.
Maintains conversation history and ensures on-topic, human-like responses.
Production-only: No fallbacks to local LLM.
"""

import requests
import logging
import time
from typing import Optional
from config import GROQ_API_KEY, GROQ_MODEL

logger = logging.getLogger(__name__)

# Reusable Groq client (session pooling for efficiency)
_groq_session = None

def get_groq_session():
    """Lazy-load and reuse a single requests.Session for Groq API."""
    global _groq_session
    if _groq_session is None:
        _groq_session = requests.Session()
    return _groq_session


def generate_response(
    user_text: str,
    context: str,
    system_prompt: str = None,
    call_type: str = "normal",
    emotion: str = "neutral",
    max_retries: int = 2
) -> str:
    """
    Generate AI response using Groq API.
    Production-only: No fallbacks to local LLM.
    
    Args:
        user_text: User's spoken input
        context: Recent conversation history
        system_prompt: Custom system prompt (overrides default)
        call_type: Call type (normal, manual, custom, emotion, crack_blast)
        emotion: Voice emotion (neutral, angry, calm, urgent)
        max_retries: Retry count on failure
        
    Returns:
        AI agent's response
    """
    
    if not GROQ_API_KEY or "YOUR_" in GROQ_API_KEY:
        logger.error("[LLM-Groq] GROQ_API_KEY not configured. Set via Railway env or .env")
        return "I'm having technical difficulties. Please try again."
    
    if system_prompt is None:
        from config import SYSTEM_PROMPT
        system_prompt = SYSTEM_PROMPT
    
    # Emotion-based response modifier (subtle, for TTS pacing)
    emotion_suffix = {
        "angry": "\nSpeak with urgency and slight concern.",
        "calm": "\nSpeak with calm reassurance.",
        "urgent": "\nSpeak with professional urgency.",
        "neutral": ""
    }.get(emotion.lower(), "")
    
    full_system_prompt = system_prompt + emotion_suffix
    
    full_prompt = f"""{full_system_prompt}

Conversation so far:
{context}

Customer: {user_text}
Agent:"""

    response = _call_groq(full_prompt, max_retries)
    if response:
        return response
    
    return "I didn't catch that. Could you please repeat?"


def _call_groq(prompt: str, max_retries: int = 2) -> Optional[str]:
    """
    Send prompt to Groq API with retries.
    Production-only implementation - no fallbacks.
    
    Args:
        prompt: Full prompt including system + context + customer input
        max_retries: Number of retry attempts
        
    Returns:
        Response text or None if all retries fail
    """
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,  # Low = consistent, professional
        "max_tokens": 120,   # Keep responses short (under 30 words typical)
        "top_p": 0.95,
        "stop": ["Customer:", "\n\n"]
    }
    
    session = get_groq_session()
    
    for attempt in range(max_retries):
        try:
            resp = session.post(url, json=payload, timeout=10, headers=headers)
            
            if resp.status_code == 200:
                data = resp.json()
                response = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if response:
                    logger.info(f"[LLM-Groq] ✅ Response: {response[:80]}")
                    return response
                else:
                    logger.warning("[LLM-Groq] Empty response from API")
                    return None
            elif resp.status_code == 429:
                logger.warning(f"[LLM-Groq] Rate limited (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(1 + attempt * 2)
                    continue
            else:
                logger.error(f"[LLM-Groq] HTTP {resp.status_code}: {resp.text[:200]}")
                return None
                
        except requests.Timeout:
            logger.warning(f"[LLM-Groq] Timeout (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
        except Exception as e:
            logger.error(f"[LLM-Groq] Error: {e}")
            return None
    
    logger.error("[LLM-Groq] All retries exhausted")
    return None


def chat_with_ai(
    user_text: str,
    session,
    system_prompt: str = None,
    call_type: str = "normal",
    emotion: str = "neutral"
) -> str:
    """
    High-level chat function: update history, get AI response, update history.
    
    Args:
        user_text: User's input
        session: CallSession object
        system_prompt: Custom system prompt (optional)
        call_type: Type of call
        emotion: Voice emotion for response
        
    Returns:
        AI response text
    """
    if not user_text or not user_text.strip():
        return "I didn't catch that. Could you please repeat?"
    
    session.add_user_message(user_text)
    context = session.get_context(limit=8)  # Last 8 turns for context
    
    response = generate_response(
        user_text,
        context,
        system_prompt,
        call_type=call_type,
        emotion=emotion,
        max_retries=2
    )
    
    session.add_agent_message(response)
    logger.info(f"[CHAT] {len(session.history)} turns, response: {response[:60]}")
    return response
