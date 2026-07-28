from models.call_metadata import CallMetadata


class PromptBuilder:
    def build(self, metadata: CallMetadata) -> str:
        ctx = metadata.to_prompt_context()

        target_lines = [
            f"- Customer Name: {ctx['target_name']}",
            f"- Customer Type: {ctx['customer_type']}",
            f"- Relationship: {ctx['relationship']}",
        ]
        if ctx.get("target_identifier"):
            target_lines.append(f"- Customer Identifier: {ctx['target_identifier']}")
        if ctx.get("region"):
            target_lines.append(f"- Region: {ctx['region']}")
        if ctx.get("previous_context"):
            target_lines.append(f"- Previous Context: {ctx['previous_context']}")

        company_lines = [
            f"- Company: {ctx['company_name']}",
            f"- Department: {ctx['department']}",
        ]
        if ctx.get("representative_name"):
            company_lines.append(f"- Your Name: {ctx['representative_name']}")
        if ctx.get("brand"):
            company_lines.append(f"- Brand: {ctx['brand']}")
        if ctx.get("support_contact"):
            company_lines.append(f"- Support Contact: {ctx['support_contact']}")
        if ctx.get("website"):
            company_lines.append(f"- Website: {ctx['website']}")

        rules = [
            "1. Do NOT ask for the code more than 3 times. If they fail 3 times, tell them to contact support.",
            "2. Do NOT read the code to the customer. They must provide it.",
            "3. If the customer asks questions about the reason for the call, answer professionally based on the reason provided.",
            "4. Keep responses concise and natural. This is a phone conversation.",
            "5. When the customer provides the code, thank them and tell them you've verified their account.",
        ]
        if ctx.get("greeting_style"):
            rules.append(f"6. Greeting style: {ctx['greeting_style']}")
        if ctx.get("conversation_personality"):
            rules.append(f"7. Personality: {ctx['conversation_personality']}")

        emotion_line = ""
        if ctx.get("emotion"):
            emotion_line = f"\nEMOTIONAL TONE:\nAdopt a {ctx['emotion']} tone throughout the conversation.\n"

        prompt = (
            f"You are a professional {ctx['department']} representative from {ctx['company_name']}.\n"
            "\n"
            "YOUR ROLE:\n"
            f"You are calling to {ctx['reason']}. You must speak naturally, confidently, and professionally. Your job is to guide the conversation and verify the customer's identity.\n"
            f"{emotion_line}"
            "\n"
            "TARGET INFORMATION:\n"
            + "\n".join(target_lines) + "\n"
            "\n"
            "COMPANY INFORMATION:\n"
            + "\n".join(company_lines) + "\n"
            "\n"
            "VERIFICATION PROCESS:\n"
            f"You need to verify the customer's identity by asking them to provide a {ctx['otp_length']}-digit verification code that was sent to them via {ctx['otp_delivery_method']}.\n"
            "\n"
            "IMPORTANT RULES:\n"
            + "\n".join(rules) + "\n"
        )

        if ctx.get("custom_instructions"):
            prompt += (
                "\n"
                "CUSTOM INSTRUCTIONS:\n"
                f"{ctx['custom_instructions']}\n"
            )

        return prompt

    def build_messages(self, metadata: CallMetadata) -> list[dict]:
        return [
            {"role": "system", "content": self.build(metadata)},
        ]
