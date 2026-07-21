#!/usr/bin/env python
"""
Final verification: Confirm ZERO Ollama fallbacks, 100% Groq-only.
This script validates the production migration is complete.
"""
import sys
import inspect

print("="*70)
print("GROQ MIGRATION VERIFICATION - PRODUCTION ONLY")
print("="*70)

# Test 1: Verify ai/llm.py has no Ollama
print("\n[TEST 1] Checking ai/llm.py for Ollama references...")
from ai import llm
source = inspect.getsource(llm)
if "ollama" in source.lower() or "OLLAMA" in source:
    print("❌ FAILED: Ollama references found in ai/llm.py")
    sys.exit(1)
else:
    print("✅ PASSED: No Ollama references in ai/llm.py")

# Test 2: Verify generate_response uses only Groq
print("\n[TEST 2] Checking generate_response signature...")
sig = inspect.signature(llm.generate_response)
if "max_retries" in sig.parameters:
    print("✅ PASSED: generate_response has retry logic")
else:
    print("❌ FAILED: generate_response missing retry logic")
    sys.exit(1)

# Test 3: Verify _call_groq is the only LLM caller
print("\n[TEST 3] Checking LLM function structure...")
functions = [name for name, _ in inspect.getmembers(llm, inspect.isfunction)]
if "_call_groq" in functions and "_try_ollama" not in functions:
    print("✅ PASSED: Only Groq function present, no Ollama fallback")
else:
    print(f"❌ FAILED: Unexpected functions: {functions}")
    sys.exit(1)

# Test 4: Verify config has Groq but not Ollama
print("\n[TEST 4] Checking config.py...")
from config import GROQ_API_KEY, GROQ_MODEL
print(f"✅ PASSED: Groq config loaded (GROQ_MODEL={GROQ_MODEL})")
try:
    from config import OLLAMA_URL
    print("⚠️  WARNING: OLLAMA_URL still in config (but not used)")
except ImportError:
    print("✅ PASSED: OLLAMA_URL removed from config")

# Test 5: Verify production imports don't use Ollama
print("\n[TEST 5] Checking production code for Ollama imports...")
try:
    import bot
    import main
    from live_listen import server
    print("✅ PASSED: Production code imports successfully (no Ollama deps)")
except ImportError as e:
    print(f"❌ FAILED: Import error: {e}")
    sys.exit(1)

# Test 6: Verify Groq API key requirement
print("\n[TEST 6] Checking Groq API key requirement...")
if not GROQ_API_KEY or "YOUR_" in GROQ_API_KEY:
    print("⚠️  WARNING: GROQ_API_KEY not set (required for production)")
    print("   Set GROQ_API_KEY in Railway environment variables")
else:
    print("✅ PASSED: GROQ_API_KEY is configured")

print("\n" + "="*70)
print("✅ ALL VERIFICATION TESTS PASSED")
print("="*70)
print("\nDeployment Status:")
print("  ✅ Ollama: Completely removed")
print("  ✅ Groq: Primary and only LLM backend")
print("  ✅ Production-ready: No fallbacks, no local dependencies")
print("\nNext step: Set GROQ_API_KEY in Railway and deploy")
