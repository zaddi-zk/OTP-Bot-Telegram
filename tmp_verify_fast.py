import os
import sys
import types

os.environ['SYSTEM_PROMPT'] = 'CANONICAL_PROMPT'
sys.path.insert(0, r'c:\Users\Miller\Music\OTP-Bot-Telegram-clean')

import bot
from core.files import user_conf_path, read_user_file
from ai.session import CallSession
import ai.llm as llm

user_id = '123456789'
for name in [
    'Name.txt', 'Company Name.txt', 'phonenum.txt', 'Caller ID.txt', 'From Name.txt',
    'Language.txt', 'Delivery.txt', 'Digits.txt', 'Voice.txt', 'VoiceName.txt',
    'call_mode_label.txt', 'custom_script.txt'
]:
    try:
        os.remove(os.path.join(user_conf_path(user_id), name))
    except FileNotFoundError:
        pass

bot.is_premium_user = lambda uid: True
sent = []

def fake_send_message(chat_id, text, **kwargs):
    sent.append((chat_id, text))

bot.bot.send_message = fake_send_message

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMessage:
    def __init__(self, uid):
        self.from_user = FakeUser(uid)
        self.chat = types.SimpleNamespace(id=123456)
        self.text = 'Alice, Acme Bank, +15551234567, +15557654321, Support Team, en, sms, 6'

bot.set_user_state(user_id, 'fast_mode_awaiting')
bot.handle_stateful_text(FakeMessage(int(user_id)))

print('written_name', read_user_file(user_id, 'Name.txt', ''))
print('written_company', read_user_file(user_id, 'Company Name.txt', ''))
print('written_phone', read_user_file(user_id, 'phonenum.txt', ''))
print('written_caller_id', read_user_file(user_id, 'Caller ID.txt', ''))
print('written_from_name', read_user_file(user_id, 'From Name.txt', ''))
print('written_language', read_user_file(user_id, 'Language.txt', ''))
print('written_delivery', read_user_file(user_id, 'Delivery.txt', ''))
print('written_digits', read_user_file(user_id, 'Digits.txt', ''))
print('written_mode_label', read_user_file(user_id, 'call_mode_label.txt', ''))
print('custom_script_exists', os.path.exists(os.path.join(user_conf_path(user_id), 'custom_script.txt')))

captured = {}

def fake_call_groq(messages, max_retries=2):
    captured['messages'] = messages
    return 'ok'

llm._call_groq = fake_call_groq
session = CallSession('FAST_MODE_PROOF')
session.call_type = 'normal'
session.mode_label = 'Fast Mode'
session.custom_script = None
session.emotion = 'neutral'
llm.chat_with_ai('hello there', session, system_prompt=None, call_type=session.call_type, emotion=session.emotion)
print('prompt_head', captured['messages'][0]['content'].splitlines()[0])
print('contains_canonical', 'CANONICAL_PROMPT' in captured['messages'][0]['content'])
print('contains_custom_script', 'strict manual verification' in captured['messages'][0]['content'].lower())
