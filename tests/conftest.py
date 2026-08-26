"""Reset Motor client between tests — it cannot span closed event loops."""
import pytest

import app.database as database


@pytest.fixture(autouse=True)
def _reset_mongo_client():
    database._client = None
    database._db = None
    database._bound = False
    yield
    database._client = None
    database._db = None
    database._bound = False
