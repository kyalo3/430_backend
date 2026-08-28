"""Reset Motor client between tests — it cannot span closed event loops."""
import os

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "ci-test-secret-key-at-least-32-chars")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("TRUSTED_HOSTS", "localhost,127.0.0.1,testserver")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("RATE_LIMIT_AUTH_PER_MINUTE", "1000")
os.environ.setdefault("RATE_LIMIT_WRITE_PER_MINUTE", "1000")
os.environ.setdefault("FEATURE_WORLD_BANK", "false")

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
