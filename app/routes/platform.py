"""Privacy, consent, and platform metadata endpoints."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.audit import write_audit
from app.core.rbac import require_roles
from app.core.security import get_current_user
from app.database import consent_collection, user_collection

router = APIRouter(tags=["platform"])


class ConsentIn(BaseModel):
    purpose: str
    granted: bool


@router.get("/platform/privacy-notice")
async def privacy_notice():
    return {
        "summary": "Sustainashare collects only data needed to verify participants, match surplus to needs, fulfil handovers, and measure verified impact.",
        "purposes": [
            "Account security and authentication",
            "Donation and need matching",
            "Fulfilment logistics for authorised volunteers",
            "Verified impact reporting (aggregates)",
            "Audit and abuse prevention",
        ],
        "not_done": [
            "Public recipient profiles",
            "Selling personal data",
            "Surveillance scoring of recipients",
        ],
        "contact": "privacy@sustainashare.local",
    }


@router.post("/platform/consent")
async def record_consent(body: ConsentIn, current_user: dict = Depends(get_current_user)):
    doc = {
        "user_id": str(current_user["id"]),
        "purpose": body.purpose,
        "granted": body.granted,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    await consent_collection.insert_one(doc)
    await write_audit(
        actor_id=str(current_user["id"]),
        actor_role=current_user.get("role"),
        action="consent.recorded",
        entity_type="user",
        entity_id=str(current_user["id"]),
        metadata=doc,
    )
    return {"ok": True}


@router.get("/platform/me/export")
async def export_my_data(current_user: dict = Depends(get_current_user)):
    return {
        "user": {
            "id": current_user.get("id"),
            "username": current_user.get("username"),
            "email": current_user.get("email"),
            "role": current_user.get("role"),
        },
        "note": "Extended export of profile collections can be expanded per role.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/platform/me/delete-request")
async def delete_request(current_user: dict = Depends(get_current_user)):
    await user_collection.update_one(
        {"username": current_user["username"]},
        {"$set": {"status": "pending_deletion", "deletion_requested_at": datetime.now(timezone.utc).isoformat()}},
    )
    await write_audit(
        actor_id=str(current_user["id"]),
        actor_role=current_user.get("role"),
        action="user.deletion_requested",
        entity_type="user",
        entity_id=str(current_user["id"]),
    )
    return {"message": "Deletion requested. An administrator will anonymise or remove account data per retention policy."}


@router.get("/platform/audit")
async def list_audit(current_user: dict = Depends(require_roles("admin")), limit: int = 50):
    from app.database import audit_collection

    limit = min(limit, 200)
    rows = []
    async for row in audit_collection.find().sort("created_at", -1).limit(limit):
        row["id"] = str(row.pop("_id"))
        rows.append(row)
    return rows
