import requests
url='http://127.0.0.1:5000/capture_otp'
payload={'user_id':'8366864444','chat_id':'8366864444','Digits':'676767','CallSid':'CAad43820cbf927a4e87a6acc3c875e7f9'}
try:
    r=requests.post(url,data=payload,timeout=10)
    print('POST status', r.status_code)
    print(r.text[:200])
except Exception as e:
    print('Error', e)
