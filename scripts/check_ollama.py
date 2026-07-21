import requests
url='http://localhost:11434/api/generate'
try:
    r = requests.get(url, timeout=3)
    print('STATUS', r.status_code)
    print('TEXT', r.text[:400])
except Exception as e:
    print('ERROR', repr(e))
