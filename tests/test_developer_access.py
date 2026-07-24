import bot


def test_developer_users_are_treated_as_premium(monkeypatch):
    monkeypatch.setattr(bot, "check_subscription", lambda user_id: "INACTIVE")
    monkeypatch.setattr(bot, "is_privileged_user", lambda user_id: True)

    assert bot.is_premium_user("999999") is True
    assert bot.is_full_premium_user("999999") is True
