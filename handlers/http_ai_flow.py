"""
HTTP-based AI call flow using TwiML Gather instead of WebSocket Media Streams.
This handles the /ai_start and /handle_gather endpoints for Railway compatibility.
"""
import os
import time
import logging
from flask import request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather

logger = logging.getLogger(__name__)


def generate_ai_greeting(session, call_sid, user_id):
    """
    Generate AI greeting for the call.
    Returns: (greeting_text, audio_url) tuple
    """
    greeting_text = None
    audio_url = None
    
    try:
        logger.warning(f"[AI_GREETING] Generating AI greeting for {call_sid}")
        from ai.llm import generate_response
        from config import get_system_prompt
        
        system_prompt = get_system_prompt()
        greeting_prompt = (
            f"Generate a professional greeting for a {session.call_type} call. "
            f"Company: {session.company}. Target: {session.name}. "
            f"Emotion: {session.emotion}. Keep it under 30 seconds of speech. "
            f"Greeting only, no questions yet."
        )
        greeting_text = generate_response(
            greeting_prompt,
            context="",
            system_prompt=system_prompt,
            call_type=session.call_type,
            emotion=session.emotion,
            session=session
        )
        
        if greeting_text:
            greeting_text = greeting_text.strip()
            logger.info(f"[AI_GREETING] ✅ Greeting generated: {greeting_text[:100]}...")
            session.add_agent_message(greeting_text)
        else:
            logger.warning(f"[AI_GREETING] LLM returned empty greeting")
            greeting_text = f"Hello {session.name}, this is a call from {session.company}. Please hold."
    except Exception as e:
        logger.error(f"[AI_GREETING] Error generating greeting: {e}", exc_info=True)
        greeting_text = f"Hello {session.name}, this is a call from {session.company}. Please hold."
    
    # Convert greeting to audio
    try:
        if greeting_text:
            from ai.tts import generate_telephony_audio
            from config import build_public_base_url
            
            logger.warning(f"[AI_GREETING] Generating audio for greeting")
            audio_data = generate_telephony_audio(
                greeting_text,
                session.voice_id,
                output_format="ulaw_8000",
                call_sid=call_sid,
                session=session
            )
            
            if audio_data:
                # Save audio file temporarily
                audio_dir = os.path.join("conf", str(user_id))
                os.makedirs(audio_dir, exist_ok=True)
                audio_filename = f"greeting_{call_sid}.ulaw"
                audio_path = os.path.join(audio_dir, audio_filename)
                
                with open(audio_path, "wb") as f:
                    f.write(audio_data)
                
                # Build HTTP URL to serve the audio
                base_url = build_public_base_url()
                audio_url = f"{base_url}/audio/{user_id}/{audio_filename}"
                logger.info(f"[AI_GREETING] ✅ Audio saved and available at: {audio_url}")
    except Exception as e:
        logger.error(f"[AI_GREETING] Error generating audio: {e}", exc_info=True)
    
    return greeting_text, audio_url


def handle_ai_call_gather(user_id, chat_id, call_sid, base_url, bot):
    """
    Build initial TwiML with Gather element for AI call.
    """
    from ai.session import get_session
    
    session = get_session(call_sid)
    if not session:
        logger.error(f"[AI_GATHER_INIT] Session not found for {call_sid}")
        return Response("Session not found", status=404)
    
    # Generate greeting
    greeting_text, audio_url = generate_ai_greeting(session, call_sid, user_id)
    
    # Build TwiML with Gather to accept caller input
    resp = VoiceResponse()
    
    if audio_url:
        # Play greeting and gather input
        gather = Gather(
            num_digits=1,
            action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
            method="POST",
            timeout=10
        )
        gather.play(audio_url)
        resp.append(gather)
    else:
        # Fallback if audio generation failed
        gather = Gather(
            num_digits=1,
            action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
            method="POST",
            timeout=10
        )
        gather.say(greeting_text or f"Hello {session.name}. Please wait.")
        resp.append(gather)
    
    if chat_id:
        try:
            bot.send_message(int(chat_id), f"🤖 AI call started. Greeting playing now.")
        except Exception:
            pass
    
    twiml_str = str(resp)
    logger.warning(f"[AI_GATHER_INIT] ✅ Starting AI call with Gather: {call_sid}")
    logger.warning(f"[AI_GATHER_INIT] TwiML response: {twiml_str}")
    return Response(twiml_str, content_type="application/xml")


def handle_gather_input(user_id, chat_id, call_sid, base_url, bot):
    """
    Handle caller input from Gather element.
    Processes DTMF digits or speech, generates AI response, and continues conversation.
    """
    from ai.session import get_session
    from ai.llm import generate_response
    from ai.tts import generate_telephony_audio
    from config import get_system_prompt, build_public_base_url
    
    digits = request.values.get("Digits", "").strip()
    speech_result = request.values.get("SpeechResult", "").strip()
    
    logger.info(f"[HANDLE_GATHER] Call {call_sid[:8]} received input - digits={digits} speech={speech_result[:50] if speech_result else 'none'}")
    
    session = get_session(call_sid)
    if not session:
        logger.error(f"[HANDLE_GATHER] Session not found for {call_sid}")
        return Response("Session not found", status=404)
    
    # Determine caller input
    caller_input = speech_result or digits or ""
    if not caller_input:
        logger.info(f"[HANDLE_GATHER] No input from caller, replaying prompt")
        # Replay greeting
        resp = VoiceResponse()
        gather = Gather(
            num_digits=1,
            action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
            method="POST",
            timeout=10
        )
        gather.say("I didn't receive any input. Please try again.")
        resp.append(gather)
        return Response(str(resp), content_type="application/xml")
    
    # Add caller input to session
    session.add_user_message(caller_input)
    logger.info(f"[HANDLE_GATHER] Caller input added to session: {caller_input}")
    
    # Generate AI response based on input
    response_text = None
    try:
        system_prompt = get_system_prompt()
        
        # Create context-aware prompt for follow-up
        context = session.get_context()
        next_prompt = (
            f"The caller said: '{caller_input}'. Generate the next step in the {session.call_type} call. "
            f"Follow your system prompt. Be conversational and professional."
        )
        
        logger.info(f"[HANDLE_GATHER] Generating AI response for input")
        response_text = generate_response(
            next_prompt,
            context=context,
            system_prompt=system_prompt,
            call_type=session.call_type,
            emotion=session.emotion,
            session=session
        )
        
        if not response_text:
            logger.warning(f"[HANDLE_GATHER] LLM returned empty response")
            response_text = f"Thank you for your input. How else can I help you?"
        
        response_text = response_text.strip()
        logger.info(f"[HANDLE_GATHER] ✅ AI response generated: {response_text[:100]}...")
        session.add_agent_message(response_text)
        
    except Exception as e:
        logger.error(f"[HANDLE_GATHER] Error generating response: {e}", exc_info=True)
        response_text = "I'm having trouble processing your input. Please hold."
    
    # Convert response to audio
    audio_url = None
    try:
        if response_text:
            logger.info(f"[HANDLE_GATHER] Generating audio for response")
            audio_data = generate_telephony_audio(
                response_text,
                session.voice_id,
                output_format="ulaw_8000",
                call_sid=call_sid,
                session=session
            )
            
            if audio_data:
                # Save audio file
                audio_dir = os.path.join("conf", str(user_id))
                os.makedirs(audio_dir, exist_ok=True)
                audio_filename = f"response_{call_sid}_{int(time.time())}.ulaw"
                audio_path = os.path.join(audio_dir, audio_filename)
                
                with open(audio_path, "wb") as f:
                    f.write(audio_data)
                
                # Build HTTP URL
                base_url_get = build_public_base_url()
                audio_url = f"{base_url_get}/audio/{user_id}/{audio_filename}"
                logger.info(f"[HANDLE_GATHER] ✅ Response audio available at: {audio_url}")
    except Exception as e:
        logger.error(f"[HANDLE_GATHER] Error generating response audio: {e}", exc_info=True)
    
    # Build follow-up Gather TwiML
    resp = VoiceResponse()
    
    if audio_url:
        gather = Gather(
            num_digits=1,
            action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
            method="POST",
            timeout=10
        )
        gather.play(audio_url)
        resp.append(gather)
    else:
        gather = Gather(
            num_digits=1,
            action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
            method="POST",
            timeout=10
        )
        gather.say(response_text)
        resp.append(gather)
    
    logger.info(f"[HANDLE_GATHER] Returning follow-up Gather TwiML for {call_sid}")
    return Response(str(resp), content_type="application/xml")
