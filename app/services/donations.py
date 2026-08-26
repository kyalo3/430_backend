"""Donation lifecycle service with concurrency-safe allocation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson.objectid import ObjectId
from fastapi import HTTPException

from app.core.audit import write_audit
from app.core.lifecycle import DONATION_ROLE_ACTIONS, DONATION_TRANSITIONS, InvalidTransition, assert_transition
from app.database import donation_collection, impact_collection, match_collection
from app.services.notifications import notify


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def donation_public(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "food_item": doc.get("food_item") or doc.get("title", ""),
        "title": doc.get("title") or doc.get("food_item", ""),
        "brand": doc.get("brand", ""),
        "description": doc.get("description", ""),
        "quantity": doc.get("quantity", 0),
        "unit": doc.get("unit", "units"),
        "category": doc.get("category", "general"),
        "condition": doc.get("condition", "unknown"),
        "price": doc.get("price", 0),
        "donor_id": doc.get("donor_id", ""),
        "recipient_id": doc.get("recipient_id") or "",
        "status": doc.get("status", "draft"),
        "expiry_at": doc.get("expiry_at"),
        "collection_window": doc.get("collection_window"),
        "approx_location": doc.get("approx_location"),
        "handling_notes": doc.get("handling_notes"),
        "match_reasons": doc.get("match_reasons", []),
        "volunteer_id": doc.get("volunteer_id") or "",
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "version": doc.get("version", 1),
    }


async def create_donation_draft(payload: dict, donor_user_id: str) -> dict:
    doc = {
        **payload,
        "donor_id": donor_user_id,
        "recipient_id": payload.get("recipient_id") or None,
        "status": "draft",
        "version": 1,
        "created_at": _now(),
        "updated_at": _now(),
        "history": [{"status": "draft", "at": _now(), "by": donor_user_id}],
    }
    # Remove retail-oriented required recipient at create
    result = await donation_collection.insert_one(doc)
    created = await donation_collection.find_one({"_id": result.inserted_id})
    await write_audit(
        actor_id=donor_user_id,
        actor_role="donor",
        action="donation.created",
        entity_type="donation",
        entity_id=str(result.inserted_id),
    )
    return donation_public(created)


async def transition_donation(
    donation_id: str,
    target: str,
    *,
    actor: dict,
    reason: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    try:
        oid = ObjectId(donation_id)
    except Exception as exc:
        raise HTTPException(400, "Invalid donation id") from exc

    current = await donation_collection.find_one({"_id": oid})
    if not current:
        raise HTTPException(404, "Donation not found")

    role = actor.get("role")
    allowed_targets = DONATION_ROLE_ACTIONS.get(role, set())
    if role != "admin" and target not in allowed_targets:
        raise HTTPException(403, "Role cannot perform this transition")

    try:
        assert_transition(DONATION_TRANSITIONS, current.get("status", "draft"), target)
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc

    if role == "admin" and target in {"rejected", "recalled", "cancelled", "disputed"} and not reason:
        raise HTTPException(400, "Admin actions that revoke access require a reason")

    update_fields: dict[str, Any] = {
        "status": target,
        "updated_at": _now(),
        "version": int(current.get("version", 1)) + 1,
    }
    if extra:
        update_fields.update(extra)

    history_entry = {
        "status": target,
        "at": _now(),
        "by": str(actor.get("id")),
        "role": role,
        "reason": reason,
    }

    from pymongo import ReturnDocument

    result = await donation_collection.find_one_and_update(
        {"_id": oid, "status": current.get("status"), "version": current.get("version", 1)},
        {"$set": update_fields, "$push": {"history": history_entry}},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(409, "Donation changed concurrently; refresh and retry")

    await write_audit(
        actor_id=str(actor.get("id")),
        actor_role=role,
        action=f"donation.transition.{target}",
        entity_type="donation",
        entity_id=donation_id,
        reason=reason,
        metadata=extra or {},
    )

    if target == "recipient_confirmed":
        await _ensure_impact(result)
        await notify(
            user_id=str(result.get("donor_id") or actor.get("id")),
            title="Receipt confirmed",
            body="Verified impact was recorded for a completed handover.",
            event="donation.recipient_confirmed",
            entity_id=donation_id,
        )

    return donation_public(result)


async def _ensure_impact(donation: dict) -> None:
    donation_id = str(donation["_id"])
    existing = await impact_collection.find_one({"donation_id": donation_id})
    if existing:
        return
    await impact_collection.insert_one(
        {
            "donation_id": donation_id,
            "category": donation.get("category", "general"),
            "quantity": donation.get("quantity", 0),
            "unit": donation.get("unit", "units"),
            "completed_at": _now(),
            "verified": True,
            "methodology": "Counted only after recipient_confirmed or admin-verified completion.",
        }
    )


async def claim_donation_atomic(donation_id: str, recipient_user_id: str, reasons: list[str]) -> dict:
    """Prevent double allocation: only one successful claim from available → reserved."""
    from pymongo import ReturnDocument

    try:
        oid = ObjectId(donation_id)
    except Exception as exc:
        raise HTTPException(400, "Invalid donation id") from exc

    result = await donation_collection.find_one_and_update(
        {"_id": oid, "status": "available"},
        {
            "$set": {
                "status": "reserved",
                "recipient_id": recipient_user_id,
                "match_reasons": reasons,
                "updated_at": _now(),
            },
            "$inc": {"version": 1},
            "$push": {
                "history": {
                    "status": "reserved",
                    "at": _now(),
                    "by": recipient_user_id,
                    "role": "recipient",
                }
            },
        },
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(409, "Donation is no longer available")

    await match_collection.insert_one(
        {
            "donation_id": donation_id,
            "recipient_id": recipient_user_id,
            "status": "reserved",
            "reasons": reasons,
            "created_at": _now(),
        }
    )
    await write_audit(
        actor_id=recipient_user_id,
        actor_role="recipient",
        action="donation.claimed",
        entity_type="donation",
        entity_id=donation_id,
        metadata={"reasons": reasons},
    )
    donor_id = result.get("donor_id")
    if donor_id:
        await notify(
            user_id=str(donor_id),
            title="Listing reserved",
            body="A recipient claimed your available listing. A volunteer can now complete handover.",
            event="donation.claimed",
            entity_id=donation_id,
        )
    return donation_public(result)
