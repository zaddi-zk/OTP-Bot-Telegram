"""
Diagnose MP3 file issues in the bot.
Run this to check if MP3s are being generated and accessible.
"""

import os
from pathlib import Path
import requests


def diagnose_mp3():
    print("🔍 MP3 DIAGNOSTIC")
    print("=" * 60)
    
    conf_path = Path("conf")
    if not conf_path.exists():
        print("❌ conf/ directory not found")
        return
    
    user_dirs = [d for d in conf_path.iterdir() if d.is_dir()]
    print(f"📁 Found {len(user_dirs)} user directories")
    
    for user_dir in user_dirs:
        mp3_files = list(user_dir.glob("*.mp3"))
        if mp3_files:
            print(f"\n🎵 User: {user_dir.name}")
            for mp3 in mp3_files:
                size = mp3.stat().st_size
                print(f"  ✅ {mp3.name} ({size:,} bytes)")
        else:
            print(f"\n⚠️  User: {user_dir.name} - No MP3 files")
    
    ngrok_url = os.getenv("NGROK_URL", "")
    if not ngrok_url:
        print("\n❌ NGROK_URL not set")
        return
    
    print(f"\n🔗 NGROK_URL: {ngrok_url}")
    
    for user_dir in user_dirs:
        mp3_files = list(user_dir.glob("*.mp3"))
        if mp3_files:
            test_file = mp3_files[0]
            audio_url = f"{ngrok_url}/audio?user_id={user_dir.name}&file={test_file.name}"
            try:
                r = requests.get(audio_url, timeout=5)
                if r.status_code == 200:
                    print(f"✅ Audio accessible: {audio_url}")
                else:
                    print(f"❌ Audio not accessible: {audio_url} ({r.status_code})")
            except Exception as e:
                print(f"❌ Audio request failed: {e}")
    
    for user_dir in user_dirs:
        mp3_files = list(user_dir.glob("*.mp3"))
        for mp3 in mp3_files:
            if os.access(mp3, os.R_OK):
                print(f"✅ Readable: {mp3}")
            else:
                print(f"❌ Not readable: {mp3}")


if __name__ == "__main__":
    diagnose_mp3()
