import core.user_manager as user_manager


class FakeSession:
    def __init__(self):
        self.added = []
        self.committed = False

    def get(self, model, key):
        return None

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def test_add_user_if_not_exists_creates_a_user_record(monkeypatch):
    fake_session = FakeSession()

    monkeypatch.setattr(user_manager, "get_session", lambda: fake_session)

    created = user_manager.add_user_if_not_exists("12345")

    assert created is True
    assert fake_session.committed is True
    assert len(fake_session.added) == 1
    assert fake_session.added[0].user_id == "12345"
    assert fake_session.added[0].role == "free"
