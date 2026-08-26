"""Principal donation journey — register through verified impact."""
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
async def test_organisation_matching_and_verified_journey(client):
    suffix = uuid.uuid4().hex[:8]
    donor = {"username": f"jd_{suffix}", "email": f"jd_{suffix}@example.com", "password": _pwd(), "role": "donor"}
    rec = {"username": f"jr_{suffix}", "email": f"jr_{suffix}@example.com", "password": _pwd(), "role": "recipient"}
    vol = {"username": f"jv_{suffix}", "email": f"jv_{suffix}@example.com", "password": _pwd(), "role": "volunteer"}
    for u in (donor, rec, vol):
        r = await client.post("/register", json=u)
        assert r.status_code == 201, r.text

    async def login(username):
        r = await client.post("/token", data={"username": username, "password": _pwd()})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    from app.core.security import hash_password
    from app.database import user_collection

    admin_name = f"ja_{suffix}"
    await user_collection.insert_one(
        {
            "username": admin_name,
            "email": f"{admin_name}@example.com",
            "password": hash_password(_pwd()),
            "role": "admin",
            "status": "active",
            "email_verified": True,
        }
    )

    h_d = {"Authorization": f"Bearer {await login(donor['username'])}"}
    org = await client.post(
        "/organisations/",
        headers=h_d,
        json={"name": f"Rescue Kitchen {suffix}", "type": "hospitality", "approx_location": "Nairobi"},
    )
    assert org.status_code == 201, org.text
    assert org.json()["status"] == "pending"

    created = await client.post(
        "/donations/",
        headers=h_d,
        json={
            "food_item": "produce",
            "quantity": 8,
            "category": "produce",
            "description": "Leafy greens",
            "approx_location": "Nairobi",
            "organisation_id": org.json()["id"],
        },
    )
    assert created.status_code == 200, created.text
    donation_id = created.json()["id"]
    await client.post(f"/donations/{donation_id}/transition", headers=h_d, json={"status": "submitted"})

    h_a = {"Authorization": f"Bearer {await login(admin_name)}"}
    verify = await client.post(
        f"/organisations/{org.json()['id']}/verify",
        headers=h_a,
        json={"reason": "Known community kitchen"},
    )
    assert verify.status_code == 200, verify.text
    directory = await client.get("/organisations/")
    assert any(row["id"] == org.json()["id"] for row in directory.json())

    for status in ("under_review", "available"):
        r = await client.post(
            f"/donations/{donation_id}/transition",
            headers=h_a,
            json={"status": status, "reason": "moderation ok"},
        )
        assert r.status_code == 200, r.text

    h_r = {"Authorization": f"Bearer {await login(rec['username'])}"}
    ranked = await client.post(
        "/matching/suggest",
        headers=h_r,
        json={"item": "produce", "quantity": 4, "approx_location": "Nairobi", "urgency": "high"},
    )
    assert ranked.status_code == 200, ranked.text
    assert ranked.json()["engine"] == "rules_v1"
    assert any(hit["donation"]["id"] == donation_id for hit in ranked.json()["results"])

    claim = await client.post(f"/donations/{donation_id}/claim", headers=h_r, json={"reasons": ["rules match"]})
    assert claim.status_code == 200
    assert claim.json()["status"] == "matched"

    h_v = {"Authorization": f"Bearer {await login(vol['username'])}"}
    await client.put(
        "/volunteers/me/logistics",
        headers=h_v,
        json={"service_area": "Nairobi", "capacity": 2, "task_types": ["handover"]},
    )
    eligible = await client.get("/fulfilments/eligible", headers=h_v)
    assert any(i["id"] == donation_id for i in eligible.json()), eligible.text
    accepted = await client.post(f"/fulfilments/{donation_id}/accept", headers=h_v)
    assert accepted.status_code == 200, accepted.text
    for status in ("collected", "in_transit", "delivered"):
        r = await client.post(
            f"/fulfilments/{donation_id}/progress",
            headers=h_v,
            json={"status": status, "note": "Safe public handover"},
        )
        assert r.status_code == 200, r.text

    confirmed = await client.post(
        f"/donations/{donation_id}/transition",
        headers=h_r,
        json={"status": "recipient_confirmed", "reason": "Received"},
    )
    assert confirmed.status_code == 200, confirmed.text
    impact = await client.get("/impact/mine", headers=h_d)
    assert impact.status_code == 200
    assert len(impact.json()["items"]) == 1
    ops = await client.get("/impact/operations", headers=h_a)
    assert ops.status_code == 200
    assert ops.json()["verified_fulfilments"] >= 1
    blocked = await client.post(
        "/storage/intent",
        headers=h_d,
        json={"content_type": "image/jpeg", "size": 100, "filename": "a.jpg"},
    )
    assert blocked.status_code == 501
    hooks = await client.get("/integrations/webhooks", headers=h_a)
    assert hooks.status_code == 404
    recip_org = await client.post(
        "/organisations/",
        headers=h_r,
        json={"name": "Should Fail", "type": "community"},
    )
    assert recip_org.status_code == 403
