import requests
from config import OLLAMA_URL, OLLAMA_MODEL

payload = {"model": OLLAMA_MODEL, "prompt": "Hello", "num_predict": 10}
print('Posting to', OLLAMA_URL)
try:
    r = requests.post(OLLAMA_URL, json=payload, timeout=15)
    print('STATUS', r.status_code)
    try:
        print('JSON:', r.json())
    except Exception:
        print('TEXT:', r.text[:500])
except Exception as e:
    print('ERROR', repr(e))
