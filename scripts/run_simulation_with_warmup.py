"""
Wait for Ollama model to be ready, then run the simulation.
"""
import requests
import time
import subprocess
import sys
from config import OLLAMA_URL, OLLAMA_MODEL

def wait_for_ollama_ready(max_wait=300, check_interval=5):
    """Poll Ollama until it responds to generate requests."""
    start = time.time()
    attempt = 0
    
    print(f"Waiting for Ollama ({OLLAMA_MODEL}) to be ready...")
    
    while time.time() - start < max_wait:
        attempt += 1
        try:
            # Quick test: send minimal prompt
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": "Hi",
                "num_predict": 1,
                "stream": False
            }
            resp = requests.post(OLLAMA_URL, json=payload, timeout=10)
            
            if resp.status_code == 200:
                print(f"✅ Ollama is ready! (attempt {attempt})")
                return True
            elif resp.status_code == 499:
                print(f"⏳ Ollama still loading... (attempt {attempt}, {int(time.time() - start)}s elapsed)")
            else:
                print(f"⚠️  Ollama returned {resp.status_code} (attempt {attempt})")
                
        except requests.Timeout:
            print(f"⏳ Timeout waiting for Ollama (attempt {attempt}, {int(time.time() - start)}s elapsed)")
        except Exception as e:
            print(f"⚠️  Error: {e}")
        
        time.sleep(check_interval)
    
    print(f"❌ Timeout waiting for Ollama after {max_wait}s")
    return False

if __name__ == "__main__":
    if wait_for_ollama_ready():
        print("\n" + "="*60)
        print("RUNNING NORMAL CALL SIMULATION")
        print("="*60 + "\n")
        # Run simulation
        result = subprocess.run(
            [sys.executable, "scripts/test_normal_call_simulation.py"],
            cwd="."
        )
        sys.exit(result.returncode)
    else:
        print("\n❌ Ollama failed to become ready. Check logs.")
        sys.exit(1)
