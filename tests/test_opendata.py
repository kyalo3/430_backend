"""Reference catalog and bundled Kenya counties — no live World Bank required."""
import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "ci-test-secret-key-at-least-32-chars")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("TRUSTED_HOSTS", "localhost,127.0.0.1,testserver")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("FEATURE_WORLD_BANK", "false")

if not os.getenv("MONGO_DETAILS"):
    pytest.skip("MONGO_DETAILS not set", allow_module_level=True)

from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

get_settings.cache_clear()


@pytest.fixture
async def client():
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.mark.asyncio
async def test_reference_catalog_and_counties(client):
    catalog = await client.get("/platform/reference/catalog")
    assert catalog.status_code == 200
    ids = [row["id"] for row in catalog.json()["datasets"]]
    assert "gadm-kenya-counties" in ids
    assert "world-bank-undernourishment" in ids
    areas = await client.get("/platform/reference/service-areas")
    assert areas.status_code == 200
    body = areas.json()
    assert body["count"] == 47
    assert any(item["name"] == "Nairobi County" for item in body["items"])
    cats = await client.get("/platform/reference/food-categories")
    assert cats.status_code == 200
    assert any(item["id"] == "bakery" for item in cats.json()["items"])
    place = await client.post("/platform/reference/normalize-place", json={"query": "nairobi"})
    assert place.status_code == 200
    assert place.json()["matched"] is True
    assert place.json()["canonical"]["name"] == "Nairobi County"
    ctx = await client.get("/platform/reference/sdg-context")
    assert ctx.status_code == 200
    assert ctx.json()["available"] is False
    assert "impact" in ctx.json()["usage"].lower()
