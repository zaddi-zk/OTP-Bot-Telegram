import requests
import subprocess
import sys

endpoints = [
    ('FastAPI /health', 'http://127.0.0.1:5001/health'),
    ('Flask /voice (GET)', 'http://127.0.0.1:5000/voice'),
]

print('=== Endpoint checks ===')
for name, url in endpoints:
    try:
        r = requests.get(url, timeout=5)
        text = r.text.strip().replace('\n', ' ')[:400]
        print(f'{name}: {r.status_code} {text}')
    except Exception as e:
        print(f'{name}: ERROR {e}')

print('\n=== Process list (python) ===')
try:
    out = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq python.exe'], text=True)
    print(out)
except Exception as e:
    print('tasklist failed:', e)

print('\n=== Listening ports (5000,5001) ===')
try:
    net = subprocess.check_output(['netstat', '-ano'], text=True)
    for port in ('5000', '5001'):
        found = [line for line in net.splitlines() if f':{port} ' in line or f':{port}\r' in line]
        print(f'Port {port}:', 'FOUND' if found else 'NOT FOUND')
        for line in found:
            print('  ', line)
except Exception as e:
    print('netstat failed:', e)

print('\n=== Done ===')
