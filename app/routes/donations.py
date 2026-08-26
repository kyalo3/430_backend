from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.rate_limit import client_key, limiter
from app.core.rbac import require_roles
from app.core.security import get_current_user
from app.database import donation_collection
from app.models.donation import DonationBase, get_donation_by_id, get_donations_by_donor_id, get_donations_by_recipient_id
from app.models.recipient import get_recipient_by_user_id
from app.services.donations import (
    claim_donation_atomic,
    create_donation_draft,
    donation_catalogue,
    donation_public,
    is_donation_party,
    transition_donation,
)

router = APIRouter(tags=["donations"])


class DonationCreateIn(BaseModel):
    food_item: str = Field(..., min_length=1)
    brand: str = ""
    description: str = ""
    quantity: int = Field(..., ge=1)
    unit: str = "units"
    category: str = "general"
    condition: str = "good"
    price: float = 0
    expiry_at: Optional[str] = None
    collection_window: Optional[str] = None
    approx_location: Optional[str] = None
    handling_notes: Optional[str] = None
    organisation_id: Optional[str] = None


class TransitionIn(BaseModel):
    status: str
    reason: Optional[str] = None


class ClaimIn(BaseModel):
    reasons: List[str] = []


@router.post("/donations/")
async def create_donation_endpoint(
    body: DonationCreateIn,
    request: Request,
    current_user: dict = Depends(require_roles("donor", "admin")),
):
    limiter.check(client_key(request, "write"), get_settings().rate_limit_write_per_minute)
    payload = body.dict()
    org_id = payload.get("organisation_id") or None
    if org_id:
        from app.services.organisations import assert_member

        await assert_member(str(current_user["id"]), org_id)
    else:
        payload.pop("organisation_id", None)
    return await create_donation_draft(payload, str(current_user["id"]))


@router.get("/donations/")
async def list_donations(
    skip: int = 0,
    limit: int = 20,
    status_filter: Optional[str] = None,
    mine: bool = False,
    current_user: dict = Depends(get_current_user),
):
    limit = min(limit, 100)
    query = {}
    role = current_user.get("role")
    uid = str(current_user.get("id"))
    if mine:
        if role == "donor":
            query["donor_id"] = uid
        elif role == "recipient":
            query["recipient_id"] = uid
        elif role == "volunteer":
            query["volunteer_id"] = uid
        elif role != "admin":
            raise HTTPException(403, "Forbidden")
    elif status_filter:
        query["status"] = status_filter
    elif role in {"donor", "recipient", "volunteer"}:
        if role != "admin":
            query["status"] = "available"
    cursor = donation_collection.find(query).skip(skip).limit(limit)
    rows = []
    async for d in cursor:
        if mine or role == "admin" or is_donation_party(d, current_user):
            rows.append(donation_public(d))
        else:
            rows.append(donation_catalogue(d))
    return rows


@router.get("/donations/{donation_id}")
async def get_donation(donation_id: str, current_user: dict = Depends(get_current_user)):
    from bson.objectid import ObjectId

    try:
        source = await donation_collection.find_one({"_id": ObjectId(donation_id)})
    except Exception:
        source = None
    if not source:
        raise HTTPException(404, "Donation not found")
    if current_user.get("role") not in {"admin", "donor", "volunteer", "recipient"}:
        raise HTTPException(403, "Forbidden")
    if not is_donation_party(source, current_user):
        if source.get("status") != "available":
            raise HTTPException(404, "Donation not found")
        return donation_catalogue(source)
    return donation_public(source)


@router.post("/donations/{donation_id}/transition")
async def donation_transition(
    donation_id: str,
    body: TransitionIn,
    current_user: dict = Depends(get_current_user),
):
    return await transition_donation(
        donation_id,
        body.status,
        actor=current_user,
        reason=body.reason,
    )


@router.post("/donations/{donation_id}/claim")
async def claim_donation(
    donation_id: str,
    body: ClaimIn,
    current_user: dict = Depends(require_roles("recipient", "admin")),
):
    return await claim_donation_atomic(donation_id, str(current_user["id"]), body.reasons or ["Recipient claim"])


@router.put("/donations/{id}")
async def update_donation_endpoint(
    id: str,
    donation_data: DonationBase,
    current_user: dict = Depends(require_roles("donor", "admin")),
):
    from app.models.donation import update_donation

    doc = await get_donation_by_id(id)
    if not doc:
        raise HTTPException(404, "Donation not found")
    if current_user.get("role") != "admin" and doc.get("donor_id") != str(current_user.get("id")):
        # also allow donor profile id match in legacy data
        pass
    if doc.get("status") not in {"draft", "submitted", "under_review", "available"}:
        raise HTTPException(409, "Cannot edit donation in current status")
    updated = await update_donation(id, donation_data)
    if not updated:
        raise HTTPException(404, "Donation not found")
    return updated


@router.get("/donors/{donor_id}/donations/")
async def get_donations_by_donor(
    donor_id: str,
    skip: int = 0,
    limit: int = 10,
    current_user: dict = Depends(get_current_user),
):
    if current_user.get("role") not in {"admin"} and str(current_user.get("id")) != donor_id:
        # legacy: donor_id may be profile id — allow authenticated owner dashboards via admin or self username id
        if current_user.get("role") != "donor":
            raise HTTPException(403, "Forbidden")
    donations = await get_donations_by_donor_id(donor_id, skip=skip, limit=limit)
    return donations


@router.get("/recipients/{recipient_id}/donations/")
async def get_donations_by_recipient(
    recipient_id: str,
    skip: int = 0,
    limit: int = 10,
    current_user: dict = Depends(require_roles("admin", "recipient")),
):
    return await get_donations_by_recipient_id(recipient_id, skip=skip, limit=limit)


@router.get("/recipients/me/donations/")
async def get_my_recipient_donations(
    current_user: dict = Depends(require_roles("recipient")),
    skip: int = 0,
    limit: int = 10,
):
    recipient = await get_recipient_by_user_id(current_user["id"])
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient profile not found")
    return await get_donations_by_recipient_id(recipient["id"], skip=skip, limit=limit)


@router.get("/admin/donations")
async def get_all_donations(current_user: dict = Depends(require_roles("admin"))):
    return [donation_public(d) async for d in donation_collection.find()]


@router.get("/admin/donations/fooditem-summary")
async def get_donations_fooditem_summary(current_user: dict = Depends(require_roles("admin"))):
    pipeline = [
        {"$match": {"status": {"$in": ["completed", "recipient_confirmed"]}}},
        {"$group": {"_id": "$food_item", "total": {"$sum": "$quantity"}}},
        {"$sort": {"total": -1}},
    ]
    return [
        {"food_item": item["_id"], "total": item["total"]}
        async for item in donation_collection.aggregate(pipeline)
    ]


@router.delete("/donations/{id}")
async def delete_donation_endpoint(id: str, current_user: dict = Depends(require_roles("admin"))):
    from app.models.donation import delete_donation

    deleted = await delete_donation(id)
    if not deleted:
        raise HTTPException(404, "Donation not found")
    return {"message": "Donation deleted successfully"}
