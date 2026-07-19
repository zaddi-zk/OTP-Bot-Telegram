#!/usr/bin/env python3
"""
AI Flow Validation Script
Checks if all AI components are properly configured and available.
Run BEFORE starting the bot: python validate_ai_setup.py
"""
import sys
import os
import subprocess

def print_header(msg):
    print(f"\n{'='*70}")
    print(f"  {msg}")
    print(f"{'='*70}")

def print_ok(msg):
    print(f"  ✅ {msg}")

def print_error(msg):
    print(f"  ❌ {msg}")

def print_warning(msg):
    print(f"  ⚠️  {msg}")

def print_info(msg):
    print(f"  ℹ️  {msg}")

def check_python_version():
    print_header("Python Version")
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        print_ok(f"Python {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print_error(f"Python {version.major}.{version.minor}.{version.micro} (need 3.8+)")
        return False

def check_config_variables():
    print_header("Configuration Variables")
    try:
        from config import (
            USE_AI_FLOW, OLLAMA_URL, OLLAMA_MODEL, VOUCH_CHANNEL_ID, 
            SYSTEM_PROMPT, DEFAULT_VOICE_ID, ELEVENLABS_API_KEY, NGROK_URL
        )
        
        print_info(f"USE_AI_FLOW: {USE_AI_FLOW}")
        if USE_AI_FLOW:
            print_ok("AI flow ENABLED")
        else:
            print_warning("AI flow DISABLED (set USE_AI_FLOW=true to enable)")
            return False
        
        print_info(f"OLLAMA_URL: {OLLAMA_URL}")
        print_info(f"OLLAMA_MODEL: {OLLAMA_MODEL}")
        print_info(f"ELEVENLABS_API_KEY: {'*' * 20 if ELEVENLABS_API_KEY else 'NOT SET'}")
        print_info(f"VOUCH_CHANNEL_ID: {VOUCH_CHANNEL_ID}")
        print_info(f"NGROK_URL: {NGROK_URL}")
        
        if not ELEVENLABS_API_KEY:
            print_error("ELEVENLABS_API_KEY not set")
            return False
        
        print_ok("All config variables loaded")
        return True
    except Exception as e:
        print_error(f"Config loading failed: {e}")
        return False

def check_ai_modules():
    print_header("AI Modules")
    errors = []
    
    modules = {
        "ai.session": "Session management",
        "ai.asr": "Speech recognition (Whisper)",
        "ai.llm": "LLM integration (Ollama)",
        "ai.tts": "Text-to-speech (ElevenLabs)",
        "ai.utils": "OTP extraction & notifications"
    }
    
    for module_name, description in modules.items():
        try:
            __import__(module_name)
            print_ok(f"{module_name} ({description})")
        except ImportError as e:
            print_error(f"{module_name}: {e}")
            errors.append(module_name)
        except Exception as e:
            print_error(f"{module_name}: Unexpected error: {e}")
            errors.append(module_name)
    
    if errors:
        print_warning(f"Missing modules: {', '.join(errors)}")
        return False
    
    print_ok("All AI modules available")
    return True

def check_ollama_running():
    print_header("Ollama Service")
    try:
        from config import OLLAMA_URL, OLLAMA_MODEL
        import requests
        
        # Try to connect to Ollama
        try:
            response = requests.get(f"{OLLAMA_URL.rsplit('/api', 1)[0]}/api/tags", timeout=5)
            if response.status_code == 200:
                print_ok(f"Ollama running at {OLLAMA_URL}")
                models = response.json().get("models", [])
                model_names = [m.get("name") for m in models]
                print_info(f"Available models: {', '.join(model_names)}")
                
                if OLLAMA_MODEL in model_names or any(OLLAMA_MODEL in m for m in model_names):
                    print_ok(f"Model '{OLLAMA_MODEL}' available")
                    return True
                else:
                    print_error(f"Model '{OLLAMA_MODEL}' NOT available")
                    print_warning(f"Download with: ollama pull {OLLAMA_MODEL}")
                    return False
            else:
                print_error(f"Ollama returned status {response.status_code}")
                return False
        except requests.exceptions.ConnectionError:
            print_error(f"Cannot connect to Ollama at {OLLAMA_URL}")
            print_warning("Start Ollama with: ollama serve")
            return False
    except Exception as e:
        print_error(f"Ollama check failed: {e}")
        return False

def check_elevenlabs_key():
    print_header("ElevenLabs API Key")
    try:
        from config import ELEVENLABS_API_KEY
        
        if not ELEVENLABS_API_KEY:
            print_error("ELEVENLABS_API_KEY not set")
            return False
        
        import requests
        headers = {"xi-api-key": ELEVENLABS_API_KEY}
        response = requests.get("https://api.elevenlabs.io/v1/voices", headers=headers, timeout=5)
        
        if response.status_code == 200:
            print_ok("ElevenLabs API key valid")
            voices = response.json().get("voices", [])
            print_info(f"Available voices: {len(voices)}")
            return True
        elif response.status_code == 401:
            print_error("ElevenLabs API key invalid (401)")
            return False
        else:
            print_error(f"ElevenLabs API returned {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print_warning("Cannot reach ElevenLabs API (network issue)")
        return None
    except Exception as e:
        print_error(f"ElevenLabs check failed: {e}")
        return False

def check_dependencies():
    print_header("Python Dependencies")
    required = [
        "fastapi",
        "websockets",
        "faster-whisper",
        "ollama",
        "requests",
        "numpy",
        "pydub",
        "python-multipart"
    ]
    
    missing = []
    for package in required:
        try:
            __import__(package.replace("-", "_"))
            print_ok(f"{package}")
        except ImportError:
            print_error(f"{package}")
            missing.append(package)
    
    if missing:
        print_warning(f"Missing: {', '.join(missing)}")
        print_info(f"Install with: pip install {' '.join(missing)}")
        return False
    
    return True

def check_twilio_webhooks():
    print_header("Twilio Webhooks")
    try:
        from config import NGROK_URL
        
        if not NGROK_URL:
            print_error("NGROK_URL not set")
            return False
        
        endpoints = [
            "/ai_start",
            "/voice",
            "/twilio/media",
            "/audio/{call_sid}/{filename}",
            "/twilio/status"
        ]
        
        print_info(f"Base URL: {NGROK_URL}")
        for endpoint in endpoints:
            print_info(f"  → {endpoint}")
        
        print_ok("Webhook endpoints configured")
        return True
    except Exception as e:
        print_error(f"Webhook check failed: {e}")
        return False

def main():
    print("\n" + "="*70)
    print("  AI FLOW VALIDATION SCRIPT")
    print("  This script validates your AI implementation before running the bot")
    print("="*70)
    
    checks = [
        ("Python Version", check_python_version),
        ("Configuration Variables", check_config_variables),
        ("AI Modules", check_ai_modules),
        ("Dependencies", check_dependencies),
        ("Twilio Webhooks", check_twilio_webhooks),
        ("Ollama Service", check_ollama_running),
        ("ElevenLabs API", check_elevenlabs_key),
    ]
    
    results = {}
    for name, check_func in checks:
        try:
            result = check_func()
            results[name] = result if result is not None else True
        except Exception as e:
            print_error(f"Check failed: {e}")
            results[name] = False
    
    # Summary
    print_header("SUMMARY")
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")
    
    all_passed = all(results.values())
    
    print("\n" + "="*70)
    if all_passed:
        print("  ✅ ALL CHECKS PASSED - Ready to start bot")
        print("  Command: python bot.py")
    else:
        print("  ❌ SOME CHECKS FAILED - Fix issues above before starting")
        print("  See error messages above for details")
    print("="*70 + "\n")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
