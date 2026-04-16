from datetime import datetime
from typing import List

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from app.database import donation_request_collection
from app.models.donation_request import DonationRequestCreate, DonationRequestResponse, DonationRequestUpdate
from app.models.recipient import get_recipient_by_user_id
from app.models.user import User
from app.routes.auth import get_current_user

router = APIRouter()


def _serialize_request(request: dict) -> dict:
    return {
        "id": str(request["_id"]),
        "recipient_id": request["recipient_id"],
        "item": request["item"],
        "custom": request.get("custom"),
        "status": request.get("status", "pending"),
        "created_at": request.get("created_at"),
        "updated_at": request.get("updated_at"),
        "fulfilled_donation_id": request.get("fulfilled_donation_id"),
    }

@router.post("/donation-requests/", response_model=DonationRequestResponse)
async def create_donation_request(request: DonationRequestCreate, current_user: User = Depends(get_current_user)):
    if current_user.get("role") != "recipient":
        raise HTTPException(status_code=403, detail="Only recipients can create donation requests")

    recipient = await get_recipient_by_user_id(current_user["id"])
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient profile not found")

    if request.recipient_id != recipient["id"]:
        raise HTTPException(status_code=403, detail="recipient_id must match the authenticated recipient profile")

    data = request.dict()
    data["_id"] = ObjectId()
    data["status"] = "pending"
    data["created_at"] = datetime.utcnow().isoformat()
    data["updated_at"] = data["created_at"]
    data["fulfilled_donation_id"] = None
    await donation_request_collection.insert_one(data)
    return _serialize_request(data)

@router.get("/donation-requests/", response_model=List[DonationRequestResponse])
async def list_donation_requests(current_user: User = Depends(get_current_user)):
    query = {}
    if current_user.get("role") == "recipient":
        recipient = await get_recipient_by_user_id(current_user["id"])
        if not recipient:
            raise HTTPException(status_code=404, detail="Recipient profile not found")
        query = {"recipient_id": recipient["id"]}

    requests = []
    async for r in donation_request_collection.find(query):
        requests.append(_serialize_request(r))
    return requests


@router.put("/donation-requests/{request_id}/status", response_model=DonationRequestResponse)
async def update_donation_request_status(
    request_id: str,
    request_update: DonationRequestUpdate,
    current_user: User = Depends(get_current_user),
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update donation request status")

    update_payload = {k: v for k, v in request_update.dict(exclude_unset=True).items() if v is not None}
    if not update_payload:
        raise HTTPException(status_code=400, detail="No update fields provided")

    update_payload["updated_at"] = datetime.utcnow().isoformat()

    result = await donation_request_collection.update_one(
        {"_id": ObjectId(request_id)},
        {"$set": update_payload},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Donation request not found")

    updated_request = await donation_request_collection.find_one({"_id": ObjectId(request_id)})
    return _serialize_request(updated_request)
