import sys
try:
    import pytest
    print('PYTEST_OK', pytest.__version__)
except Exception as e:
    print('PYTEST_IMPORT_ERROR', e, file=sys.stderr)
    raise
