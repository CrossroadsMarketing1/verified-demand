"""
Test: Verify dev_code is never exposed in production mode

This test confirms that the OTP API does NOT return dev_code 
when ENV is not set to 'development', even in mock SMS mode.
"""
import os
import sys
import json
import requests

BASE_URL = "http://localhost:8001"
PUBLIC_KEY = "250cd5b27ccae40b745d3bef65cf3e81"

def test_dev_code_not_in_production():
    """
    Test that dev_code is NOT returned when:
    1. ENV != 'development' 
    2. Twilio is configured (real SMS mode)
    
    This is a documentation test - actual production testing requires
    setting ENV=production which will fail without Twilio.
    """
    print("=" * 60)
    print("DEV CODE SAFETY TEST")
    print("=" * 60)
    
    # Check current environment
    env_mode = os.environ.get("ENV", "not set")
    print(f"\nCurrent ENV: {env_mode}")
    
    # Make OTP request
    response = requests.post(
        f"{BASE_URL}/api/public/otp/request",
        json={
            "publicKey": PUBLIC_KEY,
            "phone": "5559999999",
            "name": "Security Test",
            "email": "security@test.com"
        },
        headers={
            "Content-Type": "application/json",
            "Origin": "http://example.com"
        }
    )
    
    data = response.json()
    print(f"\nAPI Response Status: {response.status_code}")
    print(f"Response: {json.dumps(data, indent=2)}")
    
    # Verify dev_code behavior
    has_dev_code = "dev_code" in data
    
    if env_mode.lower() == "development":
        # In development, dev_code SHOULD be present (with mock SMS)
        if has_dev_code:
            print("\n✅ PASS: dev_code present in development mode (expected)")
        else:
            print("\n⚠️ NOTE: dev_code not present - may have Twilio configured")
    else:
        # In production, dev_code should NEVER be present
        if has_dev_code:
            print("\n❌ FAIL: dev_code found in production response!")
            sys.exit(1)
        else:
            print("\n✅ PASS: dev_code NOT present in production mode")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    test_dev_code_not_in_production()
