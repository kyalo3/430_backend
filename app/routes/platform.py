"""Privacy, consent, and platform metadata endpoints."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.audit import write_audit
from app.core.rbac import require_roles
from app.core.security import get_current_user
from app.database import consent_collection
from app.services.privacy import anonymise_account, export_user_data

router = APIRouter(tags=["platform"])


class ConsentIn(BaseModel):
    purpose: str
    granted: bool


class DeleteConfirmIn(BaseModel):
    confirmation: str


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
        "rights": [
            "Export a copy of your account data",
            "Request anonymisation of your account",
            "Withdraw optional story or photograph consent",
        ],
        "contact": "privacy@sustainashare.local",
    }


@router.post("/platform/consent")
async def record_consent(body: ConsentIn, current_user: dict = Depends(get_current_user)):
    allowed = {
        "impact_story",
        "photograph",
        "identity_publication",
        "analytics",
        "operational_updates",
    }
    if body.purpose not in allowed:
        raise HTTPException(400, "Unknown consent purpose")
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
        metadata={"purpose": body.purpose, "granted": body.granted},
    )
    return {"ok": True}


@router.get("/platform/me/export")
async def export_my_data(current_user: dict = Depends(get_current_user)):
    return await export_user_data(current_user)


@router.post("/platform/me/delete-request")
async def delete_request(body: DeleteConfirmIn, current_user: dict = Depends(get_current_user)):
    if body.confirmation.strip().upper() != "DELETE":
        raise HTTPException(400, "Type DELETE to confirm anonymisation")
    return await anonymise_account(
        current_user,
        actor=current_user,
        reason="Self-service account anonymisation",
    )


@router.get("/platform/audit")
async def list_audit(current_user: dict = Depends(require_roles("admin")), limit: int = 50):
    from app.database import audit_collection

    limit = min(limit, 200)
    rows = []
    async for row in audit_collection.find().sort("created_at", -1).limit(limit):
        row["id"] = str(row.pop("_id"))
        rows.append(row)
    return rows
