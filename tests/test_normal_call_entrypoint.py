import importlib


def test_normal_call_entrypoints_remain_distinct():
    cf = importlib.import_module('handlers.call_flow')
    assert callable(cf.initiate_call)
    assert callable(cf.initiate_call_from_query)
    assert cf.initiate_call.__name__ == 'initiate_call'
    assert cf.initiate_call_from_query.__name__ == 'initiate_call_from_query'
