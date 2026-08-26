"""Data export and anonymisation — purpose limitation and a real deletion workflow."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson.objectid import ObjectId
from fastapi import HTTPException

from app.core.audit import write_audit
from app.core.security import hash_password
from app.database import (
    consent_collection,
    donation_collection,
    donation_request_collection,
    donor_collection,
    notification_collection,
    organisation_member_collection,
    recipient_collection,
    refresh_token_collection,
    user_collection,
    volunteer_collection,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(user.get("id") or user.get("_id")),
        "username": user.get("username"),
        "email": user.get("email"),
        "role": user.get("role"),
        "status": user.get("status", "active"),
        "email_verified": user.get("email_verified", True),
    }


async def export_user_data(user: dict[str, Any]) -> dict[str, Any]:
    uid = str(user["id"])
    donations = [
        {
            "id": str(d["_id"]),
            "food_item": d.get("food_item"),
            "status": d.get("status"),
            "quantity": d.get("quantity"),
            "unit": d.get("unit"),
            "category": d.get("category"),
            "created_at": d.get("created_at"),
        }
        async for d in donation_collection.find({"donor_id": uid})
    ]
    received = [
        {
            "id": str(d["_id"]),
            "food_item": d.get("food_item"),
            "status": d.get("status"),
            "quantity": d.get("quantity"),
        }
        async for d in donation_collection.find({"recipient_id": uid})
    ]
    needs = [
        {
            "id": str(n["_id"]),
            "item": n.get("item") or n.get("food_item") or n.get("title"),
            "status": n.get("status"),
            "urgency": n.get("urgency"),
            "created_at": n.get("created_at"),
        }
        async for n in donation_request_collection.find({"recipient_id": uid})
    ]
    consents = [
        {"purpose": c.get("purpose"), "granted": c.get("granted"), "at": c.get("at")}
        async for c in consent_collection.find({"user_id": uid})
    ]
    notifications = [
        {"event": n.get("event"), "title": n.get("title"), "created_at": n.get("created_at")}
        async for n in notification_collection.find({"user_id": uid}).limit(100)
    ]
    memberships = [
        {"org_id": m.get("org_id"), "role": m.get("role"), "status": m.get("status")}
        async for m in organisation_member_collection.find({"user_id": uid})
    ]
    return {
        "user": _public_user(user),
        "donations_listed": donations,
        "donations_received": received,
        "needs": needs,
        "consents": consents,
        "notifications": notifications,
        "organisation_memberships": memberships,
        "generated_at": _now(),
        "note": "Operational records needed for verified impact may be retained in anonymised form after account closure.",
    }


async def anonymise_account(user: dict[str, Any], *, actor: dict[str, Any], reason: str) -> dict[str, str]:
    uid = str(user.get("id") or user.get("_id"))
    try:
        oid = ObjectId(uid)
    except Exception as exc:
        raise HTTPException(400, "Invalid user id") from exc
    doc = await user_collection.find_one({"_id": oid})
    if not doc:
        raise HTTPException(404, "User not found")
    if doc.get("status") == "anonymised":
        return {"message": "Account already anonymised", "id": uid}

    token = f"anon_{uid}"
    await user_collection.update_one(
        {"_id": oid},
        {
            "$set": {
                "username": token,
                "email": f"{token}@invalid.local",
                "password": hash_password(f"{token}-{_now()}"),
                "status": "anonymised",
                "anonymised_at": _now(),
                "email_verified": False,
                "failed_login_count": 0,
            },
            "$unset": {"locked_until": "", "phone": "", "last_failed_login_at": ""},
        },
    )
    await refresh_token_collection.update_many({"username": doc.get("username")}, {"$set": {"revoked": True}})
    await donor_collection.update_many(
        {"user_id": uid},
        {
            "$set": {
                "first_name": "Anonymised",
                "last_name": "Participant",
                "email": f"{token}@invalid.local",
                "id_no": "",
                "phone_number": "",
                "address": "",
                "company": "",
            }
        },
    )
    await recipient_collection.update_many(
        {"user_id": uid},
        {
            "$set": {
                "first_name": "Anonymised",
                "last_name": "Participant",
                "email": f"{token}@invalid.local",
                "id_no": "",
                "phone_number": "",
                "address": "",
                "house_hold_members": 0,
            }
        },
    )
    await volunteer_collection.update_many(
        {"user_id": uid},
        {
            "$set": {
                "first_name": "Anonymised",
                "last_name": "Participant",
                "email": f"{token}@invalid.local",
                "phone_number": "",
                "address": "",
                "availability_notes": "",
            }
        },
    )
    await write_audit(
        actor_id=str(actor.get("id")),
        actor_role=actor.get("role"),
        action="user.anonymised",
        entity_type="user",
        entity_id=uid,
        reason=reason,
    )
    return {"message": "Account anonymised. Operational donation records are retained without personal identifiers.", "id": uid}
