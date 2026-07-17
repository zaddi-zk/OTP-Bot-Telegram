import os
import re

def analyze_bot_code(directory):
    print(f"=== Starting Local Bot Scan in: {directory} ===")
    
    # Check for blocking files
    tmp_file = os.path.join(directory, "conf", "pending_verifications.tmp")
    if os.path.exists(tmp_file):
        print("[!] ALERT: Found stuck temporary lockfile at conf\\pending_verifications.tmp")
        print("    -> This is directly responsible for causing your button lag.")
        
    for root, dirs, files in os.walk(directory):
        if ".venv" in root or ".git" in root or "__pycache__" in root:
            continue
            
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    
                # Look for hazardous os.rename usage
                if "os.rename" in content:
                    print(f"\n[CRITICAL Fix Needed] File: {os.path.relpath(file_path)}")
                    print("  -> Found 'os.rename' statement. On Windows, this will crash with [WinError 183]")
                    print("     whenever files exist. Change this to 'os.replace' immediately.")
                    
                # Look for synchronous time.sleep inside async methods (Lag source)
                if "async def" in content and "time.sleep(" in content:
                    print(f"\n[PERFORMANCE WARNING] File: {os.path.relpath(file_path)}")
                    print("  -> Found synchronous 'time.sleep()' inside an async method.")
                    print("     This blocks the entire bot loop and freezes ALL concurrent buttons! Use 'await asyncio.sleep()' instead.")

if __name__ == "__main__":
    analyze_bot_code(os.getcwd())