import os
import sys

root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root not in sys.path:
    sys.path.insert(0, root)

from handlers.call_flow import handle_normal_step


class DummyTeleBot:
    def __init__(self):
        self.messages = []

    def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))


def test_normal_call_step_9_lists_voice_descriptions(monkeypatch):
    bot = DummyTeleBot()
    import handlers.call_flow as call_flow

    monkeypatch.setattr(call_flow, "_telebot_instance", bot)
    monkeypatch.setattr(
        call_flow,
        "get_voice_mapping",
        lambda: {
            "1": {"name": "Clara", "id": "clara-1", "desc": "Natural female, professional"},
            "2": {"name": "Naina", "id": "naina-1", "desc": "Friendly Indian English female"},
        },
    )

    handled = handle_normal_step(
        123,
        "user-1",
        "normal_call_step_9_digits",
        "6",
    )

    assert handled is True
    assert any("Clara" in msg[1] and "Natural female, professional" in msg[1] for msg in bot.messages)
    assert any("Naina" in msg[1] and "Friendly Indian English female" in msg[1] for msg in bot.messages)
