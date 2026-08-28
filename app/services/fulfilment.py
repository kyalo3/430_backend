"""Volunteer fulfilment — assign, progress, evidence. Exact details only after accept."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson.objectid import ObjectId
from fastapi import HTTPException
from pymongo import ReturnDocument

from app.core.audit import write_audit
from app.database import donation_collection, fulfilment_collection, organisation_collection
from app.services.donations import donation_public, transition_donation
from app.services.logistics import volunteer_can_accept, volunteer_can_see, volunteer_open_slots
from app.services.notifications import notify_user

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
            "window_start": doc.get("window_start"),
            "window_end": doc.get("window_end"),
            "handling_notes": doc.get("handling_notes"),
            "approx_location": doc.get("approx_location"),
            "load_class": doc.get("load_class") or "small",
        }
    else:
        public["handover"] = {
            "collection_window": doc.get("collection_window"),
            "window_start": doc.get("window_start"),
            "window_end": doc.get("window_end"),
            "handling_notes": None,
            "approx_location": (doc.get("approx_location") or "Service area")[:48],
            "load_class": doc.get("load_class") or "small",
        }
        public["handling_notes"] = None
    return public


def _serialise_fulfilment(row: dict) -> dict:
    return {
        "id": str(row["_id"]),
        "donation_id": row.get("donation_id"),
        "volunteer_id": row.get("volunteer_id"),
        "logistics_org_id": row.get("logistics_org_id") or "",
        "status": row.get("status"),
        "evidence": row.get("evidence") or [],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


async def _active_count(volunteer_user_id: str) -> int:
    return await donation_collection.count_documents(
        {"volunteer_id": volunteer_user_id, "status": {"$in": list(ACTIVE)}}
    )


async def list_eligible(actor: dict | None = None) -> list[dict]:
    area = ""
    profile = None
    open_slots = 99
    if actor and actor.get("role") == "volunteer":
        from app.models.volunteer import get_volunteer_by_user_id

        profile = await get_volunteer_by_user_id(str(actor.get("id")))
        area = ((profile or {}).get("service_area") or "").strip().lower()
        open_slots = volunteer_open_slots(profile, await _active_count(str(actor.get("id"))))
    rows = []
    query = {
        "status": {"$in": list(ELIGIBLE)},
        "$and": [
            {"$or": [{"volunteer_id": {"$exists": False}}, {"volunteer_id": None}, {"volunteer_id": ""}]},
            {
                "$or": [
                    {"logistics_org_id": {"$exists": False}},
                    {"logistics_org_id": None},
                    {"logistics_org_id": ""},
                ]
            },
        ],
    }
    async for doc in donation_collection.find(query).limit(120):
        if actor and actor.get("role") == "volunteer":
            ok, _ = volunteer_can_see(doc, profile, open_slots=open_slots)
            if not ok:
                continue
        if area:
            loc = (doc.get("approx_location") or "").lower()
            if loc and area not in loc and loc not in area:
                continue
        rows.append(_volunteer_view(doc, assigned=False))
        if len(rows) >= 50:
            break
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
    from app.models.volunteer import get_volunteer_by_user_id

    profile = await get_volunteer_by_user_id(volunteer_id)
    open_slots = volunteer_open_slots(profile, await _active_count(volunteer_id))
    current = await donation_collection.find_one({"_id": oid})
    if not current:
        raise HTTPException(404, "Donation not found")
    volunteer_can_accept(current, profile, open_slots=open_slots)

    result = await donation_collection.find_one_and_update(
        {
            "_id": oid,
            "status": {"$in": list(ELIGIBLE)},
            "$and": [
                {"$or": [{"volunteer_id": {"$exists": False}}, {"volunteer_id": None}, {"volunteer_id": ""}]},
                {
                    "$or": [
                        {"logistics_org_id": {"$exists": False}},
                        {"logistics_org_id": None},
                        {"logistics_org_id": ""},
                    ]
                },
            ],
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
        await notify_user(
            user_id=str(donor_id),
            title="Volunteer assigned",
            body="A volunteer accepted the handover for your listing.",
            event="fulfilment.accepted",
            entity_id=donation_id,
        )
    result["fulfilment"] = _serialise_fulfilment(ful)
    fresh = await donation_collection.find_one({"_id": oid}) or {}
    result["handover"] = {
        "collection_window": fresh.get("collection_window"),
        "window_start": fresh.get("window_start"),
        "window_end": fresh.get("window_end"),
        "handling_notes": fresh.get("handling_notes"),
        "approx_location": fresh.get("approx_location"),
        "load_class": fresh.get("load_class") or "small",
    }
    return result


async def assign_partner(donation_id: str, actor: dict, organisation_id: str, reason: str = "") -> dict:
    """Mode B — assign a verified logistics (or partner) organisation to move bulk/partner loads."""
    from app.services.organisations import assert_member

    try:
        oid = ObjectId(donation_id)
        org_oid = ObjectId(organisation_id)
    except Exception as exc:
        raise HTTPException(400, "Invalid id") from exc
    org = await organisation_collection.find_one({"_id": org_oid})
    if not org or org.get("status") != "verified":
        raise HTTPException(400, "Organisation must be verified")
    if actor.get("role") != "admin":
        await assert_member(str(actor["id"]), organisation_id)
        if org.get("type") not in {"logistics", "ngo", "community", "hospitality"}:
            raise HTTPException(403, "Only logistics-capable partners can self-assign")

    result = await donation_collection.find_one_and_update(
        {
            "_id": oid,
            "status": {"$in": list(ELIGIBLE)},
            "$and": [
                {"$or": [{"volunteer_id": {"$exists": False}}, {"volunteer_id": None}, {"volunteer_id": ""}]},
                {
                    "$or": [
                        {"logistics_org_id": {"$exists": False}},
                        {"logistics_org_id": None},
                        {"logistics_org_id": ""},
                    ]
                },
            ],
        },
        {
            "$set": {
                "logistics_org_id": organisation_id,
                "logistics_mode": "partner",
                "updated_at": _now(),
            },
            "$inc": {"version": 1},
        },
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(409, "Donation is not available for partner assignment")

    ful = {
        "donation_id": donation_id,
        "logistics_org_id": organisation_id,
        "volunteer_id": "",
        "status": "partner_assigned",
        "evidence": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    inserted = await fulfilment_collection.insert_one(ful)
    ful["_id"] = inserted.inserted_id

    if result.get("status") == "matched":
        await transition_donation(
            donation_id,
            "pickup_scheduled",
            actor=actor,
            reason=reason or "Partner logistics assigned",
            extra={"logistics_org_id": organisation_id},
        )
        await donation_collection.update_one(
            {"_id": oid},
            {"$set": {"logistics_org_id": organisation_id, "logistics_mode": "partner"}},
        )

    await write_audit(
        actor_id=str(actor.get("id")),
        actor_role=actor.get("role"),
        action="fulfilment.partner_assigned",
        entity_type="donation",
        entity_id=donation_id,
        reason=(reason or org.get("name") or "")[:200],
    )
    donor_id = result.get("donor_id")
    if donor_id:
        await notify_user(
            user_id=str(donor_id),
            title="Partner logistics assigned",
            body="A verified partner organisation will complete the handover.",
            event="fulfilment.partner_assigned",
            entity_id=donation_id,
        )
    doc = await donation_collection.find_one({"_id": oid})
    out = donation_public(doc)
    out["fulfilment"] = _serialise_fulfilment(ful)
    return out


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
        await notify_user(
            user_id=str(recipient_id),
            title="Handover delivered",
            body="Please confirm receipt so verified impact can be recorded.",
            event="donation.delivered",
            entity_id=donation_id,
        )
    return result
