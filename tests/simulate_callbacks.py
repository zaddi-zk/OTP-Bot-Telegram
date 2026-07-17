import sys
import time
try:
    import requests
except Exception:
    requests = None

BASE = 'http://127.0.0.1:5000'

def post(url, data=None, params=None):
    print(f"POST {url} params={params} data={data}")
    try:
        if requests:
            r = requests.post(url, data=data, params=params, timeout=60)
            print(f"-> {r.status_code} {r.text[:200]!r}\n")
        else:
            from urllib import parse, request
            full = url
            if params:
                full += '?' + parse.urlencode(params)
            data_bytes = None
            if data:
                data_bytes = parse.urlencode(data).encode('utf-8')
            req = request.Request(full, data=data_bytes, method='POST')
            with request.urlopen(req, timeout=60) as r:
                resp = r.read().decode('utf-8', errors='replace')
                print(f"-> {r.status} {resp[:200]!r}\n")
    except Exception as e:
        print(f"-> ERROR: {e}\n")

if __name__ == '__main__':
    # AMD handling disabled — skip AMD callback simulation
    params = {'user_id': 'test_user', 'chat_id': '12345'}
    print('Skipping AMD callback simulation (AMD disabled)')
    time.sleep(1)
    # Simulate capture_otp (DTMF gather)
    post(BASE + '/capture_otp', data={'Digits': '859201', 'CallSid': 'CA_TEST_HUMAN'}, params=params)
    print('Done')
