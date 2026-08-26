"""Privacy, lockout, catalogue redaction, and notification idempotency."""
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
from app.services.notifications import notify  # noqa: E402


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _pwd():
    return "Str0ngPass!"


async def _register(client, role="donor"):
    suffix = uuid.uuid4().hex[:8]
    body = {
        "username": f"{role}_{suffix}",
        "email": f"{role}_{suffix}@example.com",
        "password": _pwd(),
        "role": role,
    }
    r = await client.post("/register", json=body)
    assert r.status_code == 201, r.text
    return body


async def _login(client, username):
    r = await client.post("/token", data={"username": username, "password": _pwd()})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_users_me_does_not_include_password(client):
    user = await _register(client)
    token = await _login(client, user["username"])
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert "password" not in body
    assert body["username"] == user["username"]


@pytest.mark.asyncio
async def test_login_lockout_after_repeated_failures(client):
    user = await _register(client)
    last = None
    for _ in range(5):
        last = await client.post("/token", data={"username": user["username"], "password": "WrongPass1!"})
    assert last.status_code == 429
    still = await client.post("/token", data={"username": user["username"], "password": _pwd()})
    assert still.status_code == 429


@pytest.mark.asyncio
async def test_export_and_self_anonymise(client):
    user = await _register(client, "donor")
    token = await _login(client, user["username"])
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        "/donations/",
        headers=headers,
        json={"food_item": "Apples", "quantity": 3, "category": "produce", "description": "Firm apples"},
    )
    assert created.status_code == 200, created.text
    exported = await client.get("/platform/me/export", headers=headers)
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    assert payload["user"]["username"] == user["username"]
    assert any(row["food_item"] == "Apples" for row in payload["donations_listed"])
    refused = await client.post("/platform/me/delete-request", headers=headers, json={"confirmation": "no"})
    assert refused.status_code == 400
    done = await client.post("/platform/me/delete-request", headers=headers, json={"confirmation": "DELETE"})
    assert done.status_code == 200, done.text
    login = await client.post("/token", data={"username": user["username"], "password": _pwd()})
    assert login.status_code == 400


@pytest.mark.asyncio
async def test_available_listing_hides_handling_notes_and_recipient(client):
    donor = await _register(client, "donor")
    other = await _register(client, "recipient")
    from app.database import user_collection
    from app.core.security import hash_password

    suffix = uuid.uuid4().hex[:8]
    admin_name = f"padmin_{suffix}"
    await user_collection.insert_one(
        {
            "username": admin_name,
            "email": f"{admin_name}@example.com",
            "password": hash_password(_pwd()),
            "role": "admin",
            "status": "active",
        }
    )
    h_d = {"Authorization": f"Bearer {await _login(client, donor['username'])}"}
    created = await client.post(
        "/donations/",
        headers=h_d,
        json={
            "food_item": "Milk",
            "quantity": 2,
            "category": "dairy",
            "description": "Chilled",
            "handling_notes": "Keep refrigerated",
            "approx_location": "Kilimani",
        },
    )
    donation_id = created.json()["id"]
    await client.post(f"/donations/{donation_id}/transition", headers=h_d, json={"status": "submitted"})
    h_a = {"Authorization": f"Bearer {await _login(client, admin_name)}"}
    for status in ("under_review", "available"):
        r = await client.post(
            f"/donations/{donation_id}/transition",
            headers=h_a,
            json={"status": status, "reason": "moderation ok"},
        )
        assert r.status_code == 200, r.text
    h_r = {"Authorization": f"Bearer {await _login(client, other['username'])}"}
    listed = await client.get("/donations/", headers=h_r)
    assert listed.status_code == 200
    row = next(item for item in listed.json() if item["id"] == donation_id)
    assert row["handling_notes"] is None
    assert row["recipient_id"] == ""
    detail = await client.get(f"/donations/{donation_id}", headers=h_r)
    assert detail.status_code == 200
    assert detail.json()["handling_notes"] is None


@pytest.mark.asyncio
async def test_notification_retries_do_not_duplicate(client):
    await client.get("/health/live")
    uid = f"user_{uuid.uuid4().hex[:8]}"
    first = await notify(user_id=uid, title="Matched", body="A listing was matched", event="donation.matched", entity_id="abc")
    second = await notify(user_id=uid, title="Matched", body="A listing was matched", event="donation.matched", entity_id="abc")
    assert first == second
    from app.database import notification_collection

    count = await notification_collection.count_documents({"user_id": uid, "event": "donation.matched", "entity_id": "abc"})
    assert count == 1
