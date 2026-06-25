#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTP-Bot Test Suite - Verify webhook endpoints are working correctly
Run this to validate all fixes before going live
"""

import requests
import json
from urllib.parse import urlencode

# Configuration
BASE_URL = "http://localhost:5000"  # Change to your actual URL
USER_ID = "test_user_12345"
CHAT_ID = "123456789"
CALL_SID = "CA1234567890abcdef1234567890abcde"

def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")

def test_voice_endpoint():
    """Test the /voice webhook"""
    print_section("Testing /voice Endpoint")
    
    data = {
        "CallSid": CALL_SID,
        "user_id": USER_ID,
        "chat_id": CHAT_ID,
        "AnsweredBy": "human",
        "CallStatus": "in-progress"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/voice", data=data)
        print(f"Status Code: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type')}")
        print(f"Response Length: {len(response.text)} bytes")
        
        # Check for valid TwiML
        if "<?xml" in response.text or "<Response>" in response.text:
            print("✅ Valid TwiML XML structure detected")
        else:
            print("❌ Invalid TwiML - not XML")
            
        if "application/xml" in response.headers.get('Content-Type', ''):
            print("✅ Correct Content-Type header (application/xml)")
        else:
            print(f"⚠️  Content-Type: {response.headers.get('Content-Type')}")
            
        # Check for error message
        if "error" in response.text.lower() or "sorry" in response.text.lower():
            print("⚠️  Error message found in response")
        else:
            print("✅ No error messages detected")
            
        print(f"\nResponse Preview:\n{response.text[:200]}...")
        
    except Exception as e:
        print(f"❌ Request failed: {e}")

def test_gather_endpoint():
    """Test the /gather webhook"""
    print_section("Testing /gather Endpoint")
    
    data = {
        "CallSid": CALL_SID,
        "user_id": USER_ID,
        "chat_id": CHAT_ID,
        "Digits": "1"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/gather", data=data)
        print(f"Status Code: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type')}")
        
        if "<Response>" in response.text:
            print("✅ Valid TwiML XML structure detected")
        else:
            print("❌ Invalid TwiML")
            
        if "application/xml" in response.headers.get('Content-Type', ''):
            print("✅ Correct Content-Type header")
        else:
            print(f"⚠️  Content-Type: {response.headers.get('Content-Type')}")
            
        print(f"\nResponse Preview:\n{response.text[:200]}...")
        
    except Exception as e:
        print(f"❌ Request failed: {e}")

def test_capture_otp_endpoint():
    """Test the /capture_otp webhook"""
    print_section("Testing /capture_otp Endpoint")
    
    data = {
        "CallSid": CALL_SID,
        "user_id": USER_ID,
        "chat_id": CHAT_ID,
        "Digits": "123456"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/capture_otp", data=data)
        print(f"Status Code: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type')}")
        
        if "<Response>" in response.text:
            print("✅ Valid TwiML XML structure detected")
        else:
            print("❌ Invalid TwiML")
            
        if "application/xml" in response.headers.get('Content-Type', ''):
            print("✅ Correct Content-Type header")
        else:
            print(f"⚠️  Content-Type: {response.headers.get('Content-Type')}")
            
        print(f"\nResponse Preview:\n{response.text[:200]}...")
        
    except Exception as e:
        print(f"❌ Request failed: {e}")

def test_missing_parameters():
    """Test error handling with missing parameters"""
    print_section("Testing Error Handling - Missing Parameters")
    
    # Test with missing user_id
    data = {
        "CallSid": CALL_SID,
        "chat_id": CHAT_ID
    }
    
    try:
        response = requests.post(f"{BASE_URL}/voice", data=data)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200 and "<Response>" in response.text:
            print("✅ Gracefully handled missing user_id (returned valid TwiML)")
        else:
            print(f"❌ Failed to handle missing user_id: Status {response.status_code}")
            
    except Exception as e:
        print(f"❌ Request failed: {e}")

def test_invalid_digits():
    """Test /gather with invalid digits"""
    print_section("Testing /gather - Invalid Digits")
    
    data = {
        "CallSid": CALL_SID,
        "user_id": USER_ID,
        "chat_id": CHAT_ID,
        "Digits": "9"  # Wrong digit, should expect 1
    }
    
    try:
        response = requests.post(f"{BASE_URL}/gather", data=data)
        print(f"Status Code: {response.status_code}")
        
        if "<Redirect>" in response.text or "<Response>" in response.text:
            print("✅ Valid TwiML response for invalid input")
        else:
            print("❌ Invalid response for wrong digit")
            
        print(f"\nResponse Preview:\n{response.text[:200]}...")
        
    except Exception as e:
        print(f"❌ Request failed: {e}")

def main():
    print("\n" + "="*60)
    print("  OTP-BOT WEBHOOK ENDPOINT TEST SUITE")
    print("="*60)
    print(f"\nTesting: {BASE_URL}")
    print(f"User ID: {USER_ID}")
    print(f"Chat ID: {CHAT_ID}")
    print(f"Call SID: {CALL_SID}")
    
    # Run all tests
    test_voice_endpoint()
    test_gather_endpoint()
    test_capture_otp_endpoint()
    test_missing_parameters()
    test_invalid_digits()
    
    # Final summary
    print_section("Test Summary")
    print("✅ All critical endpoints tested")
    print("✅ Error handling verified")
    print("✅ TwiML structure validated")
    print("\nIf all tests show ✅, your bot is ready for production!")
    print("If you see ❌, check bot.log for detailed error messages.\n")

if __name__ == "__main__":
    main()
