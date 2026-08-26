"""API integration tests — require MONGO_DETAILS."""
import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "ci-test-secret-key-at-least-32-chars")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("TRUSTED_HOSTS", "localhost,127.0.0.1,testserver")
os.environ.setdefault("COOKIE_SECURE", "false")

if not os.getenv("MONGO_DETAILS"):
    pytest.skip("MONGO_DETAILS not set", allow_module_level=True)

from app.main import app  # noqa: E402


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _pwd():
    return "Str0ngPass!"


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health/live")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_register_blocks_admin(client):
    r = await client.post(
        "/register",
        json={"username": "badadmin1", "email": "badadmin1@example.com", "password": _pwd(), "role": "admin"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_donor_journey_and_double_claim(client):
    suffix = uuid.uuid4().hex[:8]
    donor = {
        "username": f"donor_{suffix}",
        "email": f"donor_{suffix}@example.com",
        "password": _pwd(),
        "role": "donor",
    }
    rec_a = {
        "username": f"rec_a_{suffix}",
        "email": f"rec_a_{suffix}@example.com",
        "password": _pwd(),
        "role": "recipient",
    }
    rec_b = {
        "username": f"rec_b_{suffix}",
        "email": f"rec_b_{suffix}@example.com",
        "password": _pwd(),
        "role": "recipient",
    }
    for u in (donor, rec_a, rec_b):
        r = await client.post("/register", json=u)
        assert r.status_code == 201, r.text

    async def login(username):
        r = await client.post("/token", data={"username": username, "password": _pwd()})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    donor_tok = await login(donor["username"])
    headers_d = {"Authorization": f"Bearer {donor_tok}"}
    created = await client.post(
        "/donations/",
        headers=headers_d,
        json={"food_item": "Bread", "quantity": 5, "category": "bakery", "description": "Day-old bread"},
    )
    assert created.status_code == 200, created.text
    donation_id = created.json()["id"]

    # Move to available via transitions (donor submit, then we need admin — use direct transitions as donor where allowed)
    r = await client.post(f"/donations/{donation_id}/transition", headers=headers_d, json={"status": "submitted"})
    assert r.status_code == 200, r.text

    # Bootstrap temporary admin via DB for moderation steps
    from app.database import user_collection
    from app.core.security import hash_password

    admin_name = f"admin_{suffix}"
    await user_collection.insert_one(
        {
            "username": admin_name,
            "email": f"{admin_name}@example.com",
            "password": hash_password(_pwd()),
            "role": "admin",
            "status": "active",
        }
    )
    admin_tok = await login(admin_name)
    headers_a = {"Authorization": f"Bearer {admin_tok}"}
    for status in ("under_review", "available"):
        r = await client.post(
            f"/donations/{donation_id}/transition",
            headers=headers_a,
            json={"status": status, "reason": "moderation ok"},
        )
        assert r.status_code == 200, r.text

    tok_a = await login(rec_a["username"])
    tok_b = await login(rec_b["username"])
    claim_a = await client.post(
        f"/donations/{donation_id}/claim",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={"reasons": ["category match"]},
    )
    claim_b = await client.post(
        f"/donations/{donation_id}/claim",
        headers={"Authorization": f"Bearer {tok_b}"},
        json={"reasons": ["category match"]},
    )
    assert claim_a.status_code == 200, claim_a.text
    assert claim_b.status_code == 409
