import json
import requests

try:
    r = requests.get('http://127.0.0.1:4040/api/tunnels', timeout=5)
    r.raise_for_status()
    data = r.json()
    print(json.dumps(data, indent=2))
except Exception as exc:
    print('ERROR', exc)
