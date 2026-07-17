# test_twiml.py - UPDATED with bypass headers

import requests
import json

BASE_URL = "http://localhost:5000"

def test_twiml_validation():
    print("🔍 TESTING TWIML RESPONSES")
    print("=" * 60)
    print("📡 Sending requests with X-Test-Request header to bypass validation\n")
    
    test_data = {
        "user_id": "test_user",
        "chat_id": "123456789",
        "CallSid": "CA123456"
    }
    
    endpoints = [
        ("/voice", {"AnsweredBy": "human"}),
        ("/gather", {"Digits": "1"}),
        ("/capture_otp", {"Digits": "123456"}),
    ]
    
    # Headers to bypass validation
    headers = {
        "X-Test-Request": "true",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    for endpoint, extra_data in endpoints:
        data = {**test_data, **extra_data}
        url = f"{BASE_URL}{endpoint}"
        
        try:
            response = requests.post(url, data=data, headers=headers, timeout=60)
            
            print(f"📡 {endpoint}")
            print(f"  Status: {response.status_code}")
            print(f"  Content-Type: {response.headers.get('Content-Type')}")
            
            # Check if valid TwiML
            if "<?xml" in response.text or "<Response>" in response.text:
                print("  ✅ Valid TwiML")
                # Show first 100 chars
                print(f"  Response: {response.text[:100]}...")
            else:
                print("  ❌ INVALID TwiML")
                print(f"  Response: {response.text[:200]}...")
                
        except Exception as e:
            print(f"  ❌ Error: {e}")
        print()

if __name__ == "__main__":
    test_twiml_validation()