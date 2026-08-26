"""Partner organisations and membership — institutional participation without public recipient exposure."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bson.objectid import ObjectId
from fastapi import HTTPException

from app.core.audit import write_audit
from app.database import organisation_collection, organisation_member_collection

ORG_TYPES = {"community", "ngo", "retailer", "hospitality", "logistics", "other"}
MEMBER_ROLES = {"owner", "member"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:64] or "org"


def public_org(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name"),
        "slug": doc.get("slug"),
        "type": doc.get("type"),
        "status": doc.get("status"),
        "approx_location": doc.get("approx_location") or "",
    }


def _member(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "org_id": doc.get("org_id"),
        "user_id": doc.get("user_id"),
        "role": doc.get("role"),
        "status": doc.get("status"),
    }


async def create_organisation(actor: dict, *, name: str, org_type: str, approx_location: str = "") -> dict:
    if org_type not in ORG_TYPES:
        raise HTTPException(400, "Invalid organisation type")
    if actor.get("role") not in {"donor", "volunteer", "admin"}:
        raise HTTPException(403, "Recipients participate as individuals; organisations are for surplus and logistics partners")
    name = (name or "").strip()
    if len(name) < 2:
        raise HTTPException(400, "Organisation name required")
    slug = _slug(name)
    existing = await organisation_collection.find_one({"slug": slug})
    if existing:
        slug = f"{slug}-{str(ObjectId())[-6:]}"
    status = "verified" if actor.get("role") == "admin" else "pending"
    doc = {
        "name": name,
        "slug": slug,
        "type": org_type,
        "status": status,
        "approx_location": (approx_location or "")[:120],
        "created_by": str(actor.get("id")),
        "created_at": _now(),
    }
    result = await organisation_collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    await organisation_member_collection.insert_one(
        {
            "org_id": str(result.inserted_id),
            "user_id": str(actor.get("id")),
            "role": "owner",
            "status": "active",
            "created_at": _now(),
        }
    )
    await write_audit(
        actor_id=str(actor.get("id")),
        actor_role=actor.get("role"),
        action="organisation.created",
        entity_type="organisation",
        entity_id=str(result.inserted_id),
        reason=f"{org_type}:{status}",
    )
    return public_org(doc)


async def list_directory() -> list[dict]:
    rows = []
    async for doc in organisation_collection.find({"status": "verified"}).limit(100):
        rows.append(public_org(doc))
    return rows


async def list_mine(user_id: str) -> list[dict]:
    memberships = [m async for m in organisation_member_collection.find({"user_id": str(user_id), "status": "active"})]
    orgs = []
    for m in memberships:
        try:
            doc = await organisation_collection.find_one({"_id": ObjectId(m["org_id"])})
        except Exception:
            doc = None
        if doc:
            item = public_org(doc)
            item["membership"] = _member(m)
            orgs.append(item)
    return orgs


async def list_all_admin() -> list[dict]:
    rows = []
    async for doc in organisation_collection.find().limit(200):
        rows.append(public_org(doc))
    return rows


async def verify_organisation(org_id: str, actor: dict, reason: str) -> dict:
    if not reason or len(reason.strip()) < 5:
        raise HTTPException(400, "Verification requires a reason")
    try:
        oid = ObjectId(org_id)
    except Exception as exc:
        raise HTTPException(400, "Invalid organisation id") from exc
    result = await organisation_collection.find_one_and_update(
        {"_id": oid},
        {"$set": {"status": "verified", "updated_at": _now()}},
    )
    if not result:
        raise HTTPException(404, "Organisation not found")
    await write_audit(
        actor_id=str(actor.get("id")),
        actor_role="admin",
        action="organisation.verified",
        entity_type="organisation",
        entity_id=org_id,
        reason=reason.strip(),
    )
    doc = await organisation_collection.find_one({"_id": oid})
    return public_org(doc)


async def assert_member(user_id: str, org_id: str) -> None:
    row = await organisation_member_collection.find_one(
        {"user_id": str(user_id), "org_id": str(org_id), "status": "active"}
    )
    if not row:
        raise HTTPException(403, "Not a member of this organisation")
