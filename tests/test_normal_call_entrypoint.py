import importlib


def test_normal_call_entrypoints_remain_distinct():
    cf = importlib.import_module('handlers.call_flow')
    assert callable(cf.initiate_call)
    assert callable(cf.initiate_call_from_query)
    assert cf.initiate_call.__name__ == 'initiate_call'
    assert cf.initiate_call_from_query.__name__ == 'initiate_call_from_query'


def test_build_script_uses_configured_call_setup(monkeypatch):
    cf = importlib.import_module('handlers.call_flow')

    def fake_read_user_file(user_id, filename, default=""):
        values = {
            "Name.txt": "John Doe",
            "Company Name.txt": "Chase Fraud Prevention",
            "From Name.txt": "Fraud Prevention",
        }
        return values.get(filename, default)

    monkeypatch.setattr(cf, 'read_user_file', fake_read_user_file)

    script = cf.build_script('user-123', digits=6)

    assert 'Hello, this is Chase Fraud Prevention.' in script
    assert 'Am I speaking with John Doe?' in script
