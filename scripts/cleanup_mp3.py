import shutil
from pathlib import Path

def delete_mp3_files():
    """Delete all MP3 files from conf directory."""
    conf_path = Path("conf")
    for mp3 in conf_path.rglob("*.mp3"):
        print(f"🗑️ Deleting: {mp3}")
        mp3.unlink()
    
    # Delete tts_service.py if exists
    tts_file = Path("tts_service.py")
    if tts_file.exists():
        print(f"🗑️ Deleting: {tts_file}")
        tts_file.unlink()
    
    # Delete any __pycache__ folders
    for pycache in Path(".").rglob("__pycache__"):
        print(f"🗑️ Deleting: {pycache}")
        shutil.rmtree(pycache)

if __name__ == "__main__":
    print("🧹 HOTTBOIIHITZZ MP3 CLEANUP")
    print("=" * 60)
    delete_mp3_files()
    print("✅ All MP3 files, tts_service.py, and cache deleted.")
    print("🚀 Restart your bot now.")