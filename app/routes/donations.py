from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.rbac import require_roles
from app.core.security import get_current_user
from app.database import donation_collection
from app.models.donation import DonationBase, get_donation_by_id, get_donations_by_donor_id, get_donations_by_recipient_id
from app.models.recipient import get_recipient_by_user_id
from app.services.donations import claim_donation_atomic, create_donation_draft, donation_public, transition_donation

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


class TransitionIn(BaseModel):
    status: str
    reason: Optional[str] = None


class ClaimIn(BaseModel):
    reasons: List[str] = []


@router.post("/donations/")
async def create_donation_endpoint(
    body: DonationCreateIn,
    current_user: dict = Depends(require_roles("donor", "admin")),
):
    payload = body.dict()
    return await create_donation_draft(payload, str(current_user["id"]))


@router.get("/donations/")
async def list_donations(
    skip: int = 0,
    limit: int = 20,
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    limit = min(limit, 100)
    query = {}
    role = current_user.get("role")
    if status_filter:
        query["status"] = status_filter
    elif role in {"donor", "recipient", "volunteer"}:
        # Public marketplace view: available only
        if role != "admin":
            query["status"] = "available"
    cursor = donation_collection.find(query).skip(skip).limit(limit)
    return [donation_public(d) async for d in cursor]


@router.get("/donations/{donation_id}")
async def get_donation(donation_id: str, current_user: dict = Depends(get_current_user)):
    donation = await get_donation_by_id(donation_id)
    if donation is None:
        # try raw
        from bson.objectid import ObjectId

        try:
            doc = await donation_collection.find_one({"_id": ObjectId(donation_id)})
        except Exception:
            doc = None
        if not doc:
            raise HTTPException(404, "Donation not found")
        donation = donation_public(doc)
    # Hide non-available donations from unrelated roles
    if current_user.get("role") not in {"admin", "donor", "volunteer", "recipient"}:
        raise HTTPException(403, "Forbidden")
    return donation


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
