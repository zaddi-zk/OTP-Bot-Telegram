import requests
import json
from config import OLLAMA_URL, OLLAMA_MODEL

print("Testing Ollama API...")
print(f"URL: {OLLAMA_URL}")
print(f"Model: {OLLAMA_MODEL}")

payload = {
    "model": OLLAMA_MODEL,
    "prompt": "Hello, how are you?",
    "num_predict": 20,
    "stream": False
}

try:
    print("Sending POST request (timeout 180s for model warmup)...")
    resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"Response: {data.get('response', '')[:200]}")
    else:
        print(f"Error response: {resp.text[:500]}")
except requests.Timeout:
    print("TIMEOUT after 180s - model still loading")
except Exception as e:
    print(f"ERROR: {e}")
