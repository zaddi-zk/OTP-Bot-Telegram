from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TargetInfo:
    name: str
    phone: str
    identifier: Optional[str] = None
    customer_type: str = "customer"
    region: Optional[str] = None
    relationship: str = "customer"
    previous_context: Optional[str] = None


@dataclass
class CompanyInfo:
    name: str
    department: str = "Security"
    representative_name: Optional[str] = None
    brand: Optional[str] = None
    support_contact: Optional[str] = None
    website: Optional[str] = None


@dataclass
class OTPConfig:
    length: int = 6
    delivery_method: str = "sms"


@dataclass
class AIBehavior:
    voice_provider: str = "vapi"
    voice_id: Optional[str] = None
    language: str = "en"
    emotion: str = "neutral"
    speaking_style: Optional[str] = None
    speech_speed: float = 1.0
    temperature: float = 0.7
    greeting_style: Optional[str] = None
    conversation_personality: Optional[str] = None


@dataclass
class CallMetadata:
    target: TargetInfo
    company: CompanyInfo
    reason: str
    otp: OTPConfig = field(default_factory=OTPConfig)
    ai: AIBehavior = field(default_factory=AIBehavior)
    custom_instructions: Optional[str] = None

    internal: dict = field(default_factory=dict)

    def to_prompt_context(self) -> dict:
        return {
            "target_name": self.target.name,
            "target_identifier": self.target.identifier,
            "customer_type": self.target.customer_type,
            "region": self.target.region,
            "relationship": self.target.relationship,
            "previous_context": self.target.previous_context,
            "company_name": self.company.name,
            "department": self.company.department,
            "representative_name": self.company.representative_name,
            "brand": self.company.brand,
            "support_contact": self.company.support_contact,
            "website": self.company.website,
            "reason": self.reason,
            "otp_length": self.otp.length,
            "otp_delivery_method": self.otp.delivery_method,
            "voice_provider": self.ai.voice_provider,
            "language": self.ai.language,
            "emotion": self.ai.emotion,
            "speaking_style": self.ai.speaking_style,
            "speech_speed": self.ai.speech_speed,
            "greeting_style": self.ai.greeting_style,
            "conversation_personality": self.ai.conversation_personality,
            "custom_instructions": self.custom_instructions,
        }

    def validate(self) -> list[str]:
        errors = []
        if not self.target.name:
            errors.append("target.name is required")
        if not self.target.phone:
            errors.append("target.phone is required")
        if not self.company.name:
            errors.append("company.name is required")
        if not self.reason:
            errors.append("reason is required")
        if self.otp.length < 4 or self.otp.length > 10:
            errors.append("otp.length must be between 4 and 10")
        if self.otp.delivery_method not in ("sms", "email", "authenticator", "voice", "push_notification"):
            errors.append(f"otp.delivery_method invalid: {self.otp.delivery_method}")
        return errors

    def to_vapi_assistant_overrides(self) -> dict:
        from config import LEGACY_VOICE_ID_MAP, VAPI_MODEL_PROVIDER, VAPI_MODEL_NAME
        # Always use Vapi as the voice provider for outbound TTS calls.
        vapi_provider = "vapi"

        agent_name = self.company.representative_name
        company_name = self.company.name
        department = self.company.department
        target_name = self.target.name

        if agent_name:
            first_message = f"Hello, this is {agent_name} from {company_name} {department}. Am I speaking with {target_name}?"
        else:
            first_message = f"Hello, this is {company_name} {department}. Am I speaking with {target_name}?"

        overrides = {
            "firstMessage": first_message,
            "model": {
                "provider": VAPI_MODEL_PROVIDER,
                "model": VAPI_MODEL_NAME,
                "messages": [],
            },
        }
        # Vapi requires voiceId to be a valid Vapi voice. Only include a voice
        # override when we have a known-good voice; otherwise omit it so the
        # assistant falls back to its configured default voice.
        valid_vapi_voices = {
            "Clara", "Godfrey", "Elliot", "Savannah", "Nico", "Kai", "Emma",
            "Sagar", "Neil", "Layla", "Sid", "Gustavo", "Kylie", "Rohan",
            "Lily", "Hana", "Neha", "Cole", "Harry", "Paige", "Spencer",
            "Naina", "Leah", "Tara", "Jess", "Leo", "Dan", "Mia", "Zac", "Zoe",
        }
        resolved_voice_id = None
        if self.ai.voice_id:
            # Allow mapping from legacy voice IDs to Vapi voice IDs.
            mapped = None
            try:
                mapped = LEGACY_VOICE_ID_MAP.get(self.ai.voice_id)
            except Exception:
                mapped = None
            candidate = mapped or self.ai.voice_id
            if isinstance(candidate, str) and candidate in valid_vapi_voices:
                resolved_voice_id = candidate
        if resolved_voice_id:
            overrides["voice"] = {
                "provider": vapi_provider,
                "voiceId": resolved_voice_id,
            }
        if self.ai.temperature != 0.7:
            overrides["model"]["temperature"] = self.ai.temperature
        return overrides
