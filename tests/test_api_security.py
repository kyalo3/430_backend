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


@pytest.mark.asyncio
async def test_volunteer_assignment_reveals_handover_after_accept(client):
    suffix = uuid.uuid4().hex[:8]
    donor = {"username": f"vd_{suffix}", "email": f"vd_{suffix}@example.com", "password": _pwd(), "role": "donor"}
    rec = {"username": f"vr_{suffix}", "email": f"vr_{suffix}@example.com", "password": _pwd(), "role": "recipient"}
    vol = {"username": f"vv_{suffix}", "email": f"vv_{suffix}@example.com", "password": _pwd(), "role": "volunteer"}
    for u in (donor, rec, vol):
        r = await client.post("/register", json=u)
        assert r.status_code == 201, r.text

    async def login(username):
        r = await client.post("/token", data={"username": username, "password": _pwd()})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    from app.database import user_collection
    from app.core.security import hash_password

    admin_name = f"va_{suffix}"
    await user_collection.insert_one(
        {
            "username": admin_name,
            "email": f"{admin_name}@example.com",
            "password": hash_password(_pwd()),
            "role": "admin",
            "status": "active",
        }
    )

    headers_d = {"Authorization": f"Bearer {await login(donor['username'])}"}
    created = await client.post(
        "/donations/",
        headers=headers_d,
        json={
            "food_item": "Rice",
            "quantity": 2,
            "category": "pantry",
            "collection_window": "Tomorrow 9-11",
            "handling_notes": "Keep dry",
            "approx_location": "Westlands",
        },
    )
    donation_id = created.json()["id"]
    await client.post(f"/donations/{donation_id}/transition", headers=headers_d, json={"status": "submitted"})
    headers_a = {"Authorization": f"Bearer {await login(admin_name)}"}
    for status in ("under_review", "available"):
        r = await client.post(
            f"/donations/{donation_id}/transition",
            headers=headers_a,
            json={"status": status, "reason": "moderation ok"},
        )
        assert r.status_code == 200, r.text
    headers_r = {"Authorization": f"Bearer {await login(rec['username'])}"}
    claim = await client.post(f"/donations/{donation_id}/claim", headers=headers_r, json={"reasons": ["nearby"]})
    assert claim.status_code == 200, claim.text
    assert claim.json().get("status") == "matched"

    headers_v = {"Authorization": f"Bearer {await login(vol['username'])}"}
    eligible = await client.get("/fulfilments/eligible", headers=headers_v)
    assert eligible.status_code == 200, eligible.text
    items = eligible.json()
    assert any(i["id"] == donation_id for i in items)
    preview = next(i for i in items if i["id"] == donation_id)
    assert preview["handover"]["handling_notes"] is None

    accepted = await client.post(f"/fulfilments/{donation_id}/accept", headers=headers_v)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["handover"]["handling_notes"] == "Keep dry"

    notes = await client.get("/notifications/me", headers=headers_d)
    assert notes.status_code == 200
    assert any(n["event"] == "fulfilment.accepted" for n in notes.json())

