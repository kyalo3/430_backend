"""Volunteer fulfilment — assign, progress, evidence. Exact details only after accept."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson.objectid import ObjectId
from fastapi import HTTPException
from pymongo import ReturnDocument

from app.core.audit import write_audit
from app.database import donation_collection, fulfilment_collection
from app.services.donations import donation_public, transition_donation
from app.services.notifications import notify

ELIGIBLE = {"matched", "pickup_scheduled"}
ACTIVE = {"pickup_scheduled", "collected", "in_transit", "delivered"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _volunteer_view(doc: dict, *, assigned: bool) -> dict:
    public = donation_public(doc)
    public["volunteer_id"] = doc.get("volunteer_id") or ""
    if assigned:
        public["handover"] = {
            "collection_window": doc.get("collection_window"),
            "handling_notes": doc.get("handling_notes"),
            "approx_location": doc.get("approx_location"),
        }
    else:
        public["handover"] = {
            "collection_window": None,
            "handling_notes": None,
            "approx_location": (doc.get("approx_location") or "Service area")[:48],
        }
        public["handling_notes"] = None
        public["collection_window"] = None
    return public


def _serialise_fulfilment(row: dict) -> dict:
    return {
        "id": str(row["_id"]),
        "donation_id": row.get("donation_id"),
        "volunteer_id": row.get("volunteer_id"),
        "status": row.get("status"),
        "evidence": row.get("evidence") or [],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


async def list_eligible() -> list[dict]:
    rows = []
    async for doc in donation_collection.find(
        {"status": {"$in": list(ELIGIBLE)}, "$or": [{"volunteer_id": {"$exists": False}}, {"volunteer_id": None}, {"volunteer_id": ""}]}
    ).limit(50):
        rows.append(_volunteer_view(doc, assigned=False))
    return rows


async def list_mine(volunteer_user_id: str) -> list[dict]:
    rows = []
    async for doc in donation_collection.find({"volunteer_id": volunteer_user_id}).limit(50):
        ful = await fulfilment_collection.find_one({"donation_id": str(doc["_id"]), "volunteer_id": volunteer_user_id})
        item = _volunteer_view(doc, assigned=True)
        item["fulfilment"] = _serialise_fulfilment(ful) if ful else None
        rows.append(item)
    return rows


async def accept_assignment(donation_id: str, actor: dict) -> dict:
    try:
        oid = ObjectId(donation_id)
    except Exception as exc:
        raise HTTPException(400, "Invalid donation id") from exc
    volunteer_id = str(actor.get("id"))
    result = await donation_collection.find_one_and_update(
        {
            "_id": oid,
            "status": {"$in": list(ELIGIBLE)},
            "$or": [{"volunteer_id": {"$exists": False}}, {"volunteer_id": None}, {"volunteer_id": ""}],
        },
        {
            "$set": {"volunteer_id": volunteer_id, "updated_at": _now()},
            "$inc": {"version": 1},
        },
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(409, "Assignment is no longer available")

    ful = {
        "donation_id": donation_id,
        "volunteer_id": volunteer_id,
        "status": "accepted",
        "evidence": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    inserted = await fulfilment_collection.insert_one(ful)
    ful["_id"] = inserted.inserted_id

    if result.get("status") == "matched":
        result = await transition_donation(
            donation_id,
            "pickup_scheduled",
            actor=actor,
            reason="Volunteer accepted assignment",
        )
        # re-attach volunteer_id after transition
        await donation_collection.update_one({"_id": oid}, {"$set": {"volunteer_id": volunteer_id}})
        result = donation_public(await donation_collection.find_one({"_id": oid}))
        result["volunteer_id"] = volunteer_id
    else:
        result = _volunteer_view(result, assigned=True)

    await write_audit(
        actor_id=volunteer_id,
        actor_role="volunteer",
        action="fulfilment.accepted",
        entity_type="donation",
        entity_id=donation_id,
    )
    donor_id = result.get("donor_id") if isinstance(result, dict) else None
    if donor_id:
        await notify(
            user_id=str(donor_id),
            title="Volunteer assigned",
            body="A volunteer accepted the handover for your listing.",
            event="fulfilment.accepted",
            entity_id=donation_id,
        )
    result["fulfilment"] = _serialise_fulfilment(ful)
    result["handover"] = {
        "collection_window": (await donation_collection.find_one({"_id": oid}) or {}).get("collection_window"),
        "handling_notes": (await donation_collection.find_one({"_id": oid}) or {}).get("handling_notes"),
        "approx_location": (await donation_collection.find_one({"_id": oid}) or {}).get("approx_location"),
    }
    return result


async def add_evidence(donation_id: str, actor: dict, note: str) -> dict:
    if not note or len(note.strip()) < 3:
        raise HTTPException(400, "Evidence note required")
    volunteer_id = str(actor.get("id"))
    ful = await fulfilment_collection.find_one({"donation_id": donation_id, "volunteer_id": volunteer_id})
    if not ful:
        raise HTTPException(404, "No assignment for this donation")
    entry = {"note": note.strip(), "at": _now(), "by": volunteer_id}
    await fulfilment_collection.update_one({"_id": ful["_id"]}, {"$push": {"evidence": entry}, "$set": {"updated_at": _now()}})
    await write_audit(
        actor_id=volunteer_id,
        actor_role="volunteer",
        action="fulfilment.evidence",
        entity_type="donation",
        entity_id=donation_id,
        reason=note.strip()[:200],
    )
    updated = await fulfilment_collection.find_one({"_id": ful["_id"]})
    return _serialise_fulfilment(updated)


async def progress(donation_id: str, actor: dict, status: str, note: Optional[str] = None) -> dict:
    allowed = {"collected", "in_transit", "delivered", "failed", "disputed"}
    if status not in allowed:
        raise HTTPException(400, "Invalid volunteer progress status")
    doc = None
    try:
        doc = await donation_collection.find_one({"_id": ObjectId(donation_id)})
    except Exception as exc:
        raise HTTPException(400, "Invalid donation id") from exc
    if not doc:
        raise HTTPException(404, "Donation not found")
    if doc.get("volunteer_id") != str(actor.get("id")) and actor.get("role") != "admin":
        raise HTTPException(403, "Only the assigned volunteer can update this handover")
    extra: dict[str, Any] = {}
    result = await transition_donation(donation_id, status, actor=actor, reason=note, extra=extra)
    if note:
        await add_evidence(donation_id, actor, note)
    recipient_id = doc.get("recipient_id")
    if status == "delivered" and recipient_id:
        await notify(
            user_id=str(recipient_id),
            title="Handover delivered",
            body="Please confirm receipt so verified impact can be recorded.",
            event="donation.delivered",
            entity_id=donation_id,
        )
    return result
