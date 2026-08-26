"""Ensure each authenticated role has a private profile record."""
from __future__ import annotations

from app.database import donor_collection, recipient_collection, volunteer_collection
from app.models.donor import get_donor_by_user_id
from app.models.recipient import get_recipient_by_user_id
from app.models.volunteer import get_volunteer_by_user_id


def _base_profile(user: dict) -> dict:
    username = user.get("username") or "member"
    return {
        "user_id": str(user["id"]),
        "first_name": username,
        "last_name": (user.get("role") or "member").title(),
        "email": user.get("email") or "",
        "id_no": "",
        "phone_number": "",
        "gender": "",
        "address": "",
    }


async def ensure_role_profile(user: dict) -> dict | None:
    role = user.get("role")
    uid = str(user.get("id") or "")
    if not uid or not role:
        return None
    if role == "donor":
        existing = await get_donor_by_user_id(uid)
        if existing:
            return existing
        doc = {
            **_base_profile(user),
            "company": "",
            "services_interested_in": [],
            "participating_locations": [],
            "type_of_company": "",
        }
        await donor_collection.insert_one(doc)
        return await get_donor_by_user_id(uid)
    if role == "recipient":
        existing = await get_recipient_by_user_id(uid)
        if existing:
            return existing
        doc = {
            **_base_profile(user),
            "house_hold_size": 1,
            "house_hold_members": [],
            "disability": False,
        }
        await recipient_collection.insert_one(doc)
        return await get_recipient_by_user_id(uid)
    if role == "volunteer":
        existing = await get_volunteer_by_user_id(uid)
        if existing:
            return existing
        await volunteer_collection.insert_one(_base_profile(user))
        return await get_volunteer_by_user_id(uid)
    return None
