"""
Groq LLM client for production-grade AI responses.
Uses Groq API with llama-3.1-8b-instant for low-latency, high-quality verification calls.
Maintains conversation history and ensures on-topic, human-like responses.
Production-only: No fallbacks to local LLM.
"""

import inspect
import requests
import logging
import time
import traceback
from typing import Optional
from config import GROQ_API_KEY, GROQ_MODEL, GROQ_FALLBACK_MODEL
from core.logging_utils import structured_log

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
    call_context: str = None,
    system_prompt: str = None,
    call_type: str = "normal",
    emotion: str = "neutral",
    max_retries: int = 2,
    session=None,
) -> str:
    """
    Generate AI response using Groq API.
    Production-only: No fallbacks to local LLM.
    
    Args:
        user_text: User's spoken input
        context: Recent conversation history
        call_context: Structured call metadata
        system_prompt: Custom system prompt (ignored in production; the canonical prompt is loaded from config)
        call_type: Call type (normal, manual, custom, emotion, crack_blast)
        emotion: Voice emotion (neutral, angry, calm, urgent)
        max_retries: Retry count on failure
        
    Returns:
        AI agent's response
    """
    
    call_sid = getattr(session, "call_sid", None)
    structured_log(logger, logging.INFO, "LLM_REQUEST", call_sid=call_sid, stage="LLM_REQUEST", call_type=call_type, emotion=emotion, prompt_preview=user_text[:160])
    if session and getattr(session, "mark_milestone", None) and session.mark_milestone("FIRST_LLM_REQUEST"):
        logger.info("[CALL_MILESTONE] FIRST_LLM_REQUEST call_sid=%s prompt_preview=%s", call_sid, user_text[:80])

    if not GROQ_API_KEY or "YOUR_" in GROQ_API_KEY:
        logger.error("[LLM-Groq] GROQ_API_KEY not configured. Set via Railway env or .env")
        structured_log(logger, logging.WARNING, "LLM_SKIPPED", call_sid=call_sid, stage="LLM_RESPONSE", reason="missing_api_key")
        return ""
    
    # Select the active system prompt by call mode.
    # Normal/fast flows always use the canonical prompt from config.
    # Manual/custom flows use the custom script as the prompt override.
    from config import get_system_prompt

    canonical_prompt = get_system_prompt()
    selected_prompt = canonical_prompt

    if session is not None:
        session_call_type = getattr(session, "call_type", None) or call_type
        session_custom_script = getattr(session, "custom_script", None)
        custom_script = session_custom_script or None

        if custom_script and str(session_call_type).lower() in {"manual", "custom", "manual_call", "custom_call"}:
            selected_prompt = custom_script.strip()

    # Emotion-based response modifier (subtle, for conversational tone)
    emotion_suffix = {
        "angry": "\nSpeak with urgency and slight concern.",
        "calm": "\nSpeak with calm reassurance.",
        "urgent": "\nSpeak with professional urgency.",
        "neutral": ""
    }.get(emotion.lower(), "")

    full_system_prompt = selected_prompt + emotion_suffix
    call_context = call_context or "Call Context: none"

    user_content = (
        f"Call Context:\n{call_context}\n\n"
        f"Conversation History:\n{context}\n\n"
        f"Latest Customer Message:\n{user_text}\n\n"
        "Respond naturally as a human customer verification representative."
    )

    messages = [
        {"role": "system", "content": full_system_prompt},
        {"role": "user", "content": user_content}
    ]

    # Call _call_groq defensively: some test monkeypatches may replace it
    # with functions that don't accept the `call_sid` kwarg. Try with the
    # keyword first, and fall back to a positional/keyword-only call if
    # a TypeError is raised.
    try:
        response = _call_groq(messages, max_retries=max_retries, call_sid=call_sid)
    except TypeError:
        # Fallback for test doubles that accept only (messages, max_retries)
        response = _call_groq(messages, max_retries=max_retries)

    if response:
        if session and getattr(session, "mark_milestone", None) and session.mark_milestone("FIRST_LLM_RESPONSE"):
            logger.info("[CALL_MILESTONE] FIRST_LLM_RESPONSE call_sid=%s response_preview=%s", call_sid, response[:80])
        structured_log(logger, logging.INFO, "LLM_RESPONSE", call_sid=call_sid, stage="LLM_RESPONSE", response=response[:200])
        return response

    structured_log(logger, logging.WARNING, "LLM_SKIPPED", call_sid=call_sid, stage="LLM_RESPONSE", reason="llm_unavailable_or_empty_response")
    return ""


def _call_groq(messages: list, max_retries: int = 2, call_sid: str | None = None) -> Optional[str]:
    """
    Send chat messages to Groq API with retries and a secondary fallback model.

    The primary model is attempted first. If it times out, rate-limits, or returns
    an error, the call automatically retries against a fallback model so the AI
    flow remains available in production.
    """
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    primary_model = getattr(__import__('config', fromlist=['GROQ_MODEL']), 'GROQ_MODEL', GROQ_MODEL)
    fallback_model = getattr(__import__('config', fromlist=['GROQ_FALLBACK_MODEL']), 'GROQ_FALLBACK_MODEL', GROQ_FALLBACK_MODEL)
    models = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models.append(fallback_model)

    session = get_groq_session()

    for model_idx, model_name in enumerate(models):
        for attempt in range(max_retries):
            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.55,
                "max_tokens": 140,
                "top_p": 0.92,
            }

            try:
                started_at = time.monotonic()
                resp = session.post(url, json=payload, timeout=10, headers=headers)

                if resp.status_code == 200:
                    data = resp.json()
                    response = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    if response:
                        logger.info(f"[LLM-Groq] ✅ Response from {model_name}: {response[:80]}")
                        return response
                    logger.warning(f"[LLM-Groq] Empty response from {model_name}")
                    return None

                if resp.status_code == 429:
                    elapsed_ms = int((time.monotonic() - started_at) * 1000)
                    structured_log(logger, logging.WARNING, "TIMEOUT", call_sid=call_sid, stage="LLM_TIMEOUT", timer_name="groq_chat_completion", elapsed_ms=elapsed_ms, who_created="ai.llm._call_groq", reason="rate_limited")
                    logger.warning(f"[LLM-Groq] Rate limited on {model_name} (attempt {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(1 + attempt * 2)
                        continue
                elif resp.status_code >= 500:
                    logger.error(f"[LLM-Groq] Server error on {model_name}: HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    logger.error(f"[LLM-Groq] HTTP {resp.status_code} on {model_name}: {resp.text[:200]}")

                if model_idx < len(models) - 1 and attempt == max_retries - 1:
                    logger.warning(f"[LLM-Groq] Switching from {model_name} to fallback model")
                    break
                return None

            except requests.Timeout:
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
                structured_log(logger, logging.ERROR, "TIMEOUT", call_sid=call_sid, stage="LLM_TIMEOUT", timer_name="groq_chat_completion", elapsed_ms=elapsed_ms, who_created="ai.llm._call_groq", reason="request_timeout")
                logger.warning(f"[LLM-Groq] Timeout on {model_name} (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                if model_idx < len(models) - 1:
                    logger.warning(f"[LLM-Groq] Switching from {model_name} to fallback model after timeout")
                    break
                return None
            except Exception as e:
                structured_log(logger, logging.ERROR, "EXCEPTION", call_sid=call_sid, stage="LLM_EXCEPTION", reason="llm_request_exception", error=str(e), traceback=traceback.format_exc())
                logger.error(f"[LLM-Groq] Error on {model_name}: {e}")
                if model_idx < len(models) - 1 and attempt == max_retries - 1:
                    logger.warning(f"[LLM-Groq] Switching from {model_name} to fallback model after exception")
                    break
                return None

    structured_log(logger, logging.WARNING, "LLM_SKIPPED", call_sid=call_sid, stage="LLM_RESPONSE", reason="all_retries_exhausted")
    logger.error("[LLM-Groq] All retries exhausted")
    return None


def get_initial_greeting(
    session,
    call_type: str = "normal",
    emotion: str = "neutral",
) -> str:
    """Generate the very first thing the AI agent says after the call connects.

    This is treated as an agent message (there is no customer input yet) and is
    produced using the canonical system prompt so the call starts talking immediately.
    """
    call_sid = getattr(session, "call_sid", None)
    structured_log(logger, logging.INFO, "LLM_GREETING", call_sid=call_sid, stage="LLM_GREETING", call_type=call_type, emotion=emotion)

    user_text = "[The customer has answered the phone. Begin the conversation naturally with a greeting and move toward verification. Do not wait for the customer to speak first.]"
    context = ""
    call_context = session.get_call_context()

    response = generate_response(
        user_text,
        context,
        call_context=call_context,
        call_type=call_type,
        emotion=emotion,
        max_retries=2,
        session=session,
    )
    if response:
        session.add_agent_message(response)
    logger.info(f"[CHAT] greeting generated: {response[:60]}")
    return response or ""


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
        return ""

    session.add_user_message(user_text)
    context = session.get_context(limit=8)  # Last 8 turns for context
    call_context = session.get_call_context()

    response = generate_response(
        user_text,
        context,
        call_context=call_context,
        system_prompt=system_prompt,
        call_type=call_type,
        emotion=emotion,
        max_retries=2,
        session=session,
    )

    session.add_agent_message(response)
    logger.info(f"[CHAT] {len(session.history)} turns, response: {response[:60]}")
    return response
