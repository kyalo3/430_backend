from datetime import datetime
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.lifecycle import NEED_TRANSITIONS, InvalidTransition, assert_transition
from app.core.rbac import require_roles
from app.core.security import get_current_user
from app.database import donation_request_collection
from app.models.donation_request import DonationRequestCreate, DonationRequestResponse
from app.models.recipient import get_recipient_by_user_id

router = APIRouter(tags=["needs"])

ALLOWED_NEED_STATUS = set(NEED_TRANSITIONS.keys())


class NeedStatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = None
    fulfilled_donation_id: Optional[str] = None


def _serialize_request(request: dict) -> dict:
    return {
        "id": str(request["_id"]),
        "recipient_id": request["recipient_id"],
        "item": request["item"],
        "custom": request.get("custom"),
        "status": request.get("status", "draft"),
        "created_at": request.get("created_at"),
        "updated_at": request.get("updated_at"),
        "fulfilled_donation_id": request.get("fulfilled_donation_id"),
        "quantity": request.get("quantity", 1),
        "urgency": request.get("urgency", "normal"),
        "approx_location": request.get("approx_location"),
    }


@router.post("/donation-requests/", response_model=DonationRequestResponse)
async def create_donation_request(
    request: DonationRequestCreate,
    current_user: dict = Depends(require_roles("recipient")),
):
    recipient = await get_recipient_by_user_id(current_user["id"])
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient profile not found")
    if request.recipient_id != recipient["id"]:
        raise HTTPException(status_code=403, detail="recipient_id must match the authenticated recipient profile")

    data = request.dict()
    data["_id"] = ObjectId()
    data["status"] = "submitted"
    data["created_at"] = datetime.utcnow().isoformat()
    data["updated_at"] = data["created_at"]
    data["fulfilled_donation_id"] = None
    await donation_request_collection.insert_one(data)
    return _serialize_request(data)


@router.get("/donation-requests/", response_model=List[DonationRequestResponse])
async def list_donation_requests(current_user: dict = Depends(get_current_user)):
    query = {}
    role = current_user.get("role")
    if role == "recipient":
        recipient = await get_recipient_by_user_id(current_user["id"])
        if not recipient:
            return []
        query = {"recipient_id": recipient["id"]}
    elif role not in {"admin"}:
        raise HTTPException(status_code=403, detail="Only recipients and admins can list needs")

    return [_serialize_request(r) async for r in donation_request_collection.find(query)]


@router.put("/donation-requests/{request_id}/status", response_model=DonationRequestResponse)
async def update_donation_request_status(
    request_id: str,
    body: NeedStatusUpdate,
    current_user: dict = Depends(require_roles("admin")),
):
    if body.status not in ALLOWED_NEED_STATUS:
        raise HTTPException(status_code=400, detail="Invalid need status")
    if body.status in {"rejected", "cancelled", "disputed"} and not body.reason:
        raise HTTPException(status_code=400, detail="Reason required for this transition")

    existing = await donation_request_collection.find_one({"_id": ObjectId(request_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Donation request not found")

    current_status = existing.get("status", "draft")
    # Map legacy pending → submitted
    if current_status == "pending":
        current_status = "submitted"
    try:
        assert_transition(NEED_TRANSITIONS, current_status, body.status)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    update_payload = {
        "status": body.status,
        "updated_at": datetime.utcnow().isoformat(),
    }
    if body.fulfilled_donation_id:
        update_payload["fulfilled_donation_id"] = body.fulfilled_donation_id

    await donation_request_collection.update_one({"_id": ObjectId(request_id)}, {"$set": update_payload})
    updated = await donation_request_collection.find_one({"_id": ObjectId(request_id)})
    return _serialize_request(updated)
