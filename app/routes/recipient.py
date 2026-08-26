from fastapi import APIRouter, Depends, HTTPException
from typing import List

from app.core.rbac import redact_recipient, require_roles
from app.core.security import get_current_user
from app.models.recipient import (
    Recipient,
    RecipientCreate,
    create_recipient,
    delete_recipient,
    get_recipient_by_id,
    get_recipient_by_user_id,
    get_recipients,
    update_recipient,
)
from app.services.profiles import ensure_role_profile

router = APIRouter(tags=["recipients"])


@router.get("/recipients/")
async def get_current_user_recipient(current_user: dict = Depends(require_roles("recipient", "admin"))):
    recipient = await get_recipient_by_user_id(current_user["id"])
    if not recipient:
        recipient = await ensure_role_profile(current_user)
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient profile not found")
    return recipient


@router.post("/recipients/")
async def create_recipient_endpoint(
    recipient: RecipientCreate,
    current_user: dict = Depends(require_roles("recipient", "admin")),
):
    created = await create_recipient(recipient, user_id=current_user["id"])
    return created


@router.get("/recipients/all")
async def get_recipients_endpoint(current_user: dict = Depends(require_roles("admin"))):
    recipients = await get_recipients()
    return recipients


@router.get("/recipients/{recipient_id}")
async def get_recipient_endpoint(
    recipient_id: str,
    current_user: dict = Depends(get_current_user),
):
    recipient = await get_recipient_by_id(recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail=f"Recipient with id {recipient_id} not found")
    if current_user.get("role") == "admin":
        return recipient
    if current_user.get("role") == "recipient" and recipient.get("user_id") == current_user.get("id"):
        return recipient
    # Volunteers/donors only see redacted operational fields after assignment context
    return redact_recipient(recipient)


@router.put("/recipients/{recipient_id}")
async def update_recipient_endpoint(
    recipient_id: str,
    recipient: RecipientCreate,
    current_user: dict = Depends(require_roles("recipient", "admin")),
):
    existing = await get_recipient_by_id(recipient_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if current_user.get("role") != "admin" and existing.get("user_id") != current_user.get("id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    updated = await update_recipient(recipient_id, recipient)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update recipient")
    return updated


@router.delete("/recipients/{recipient_id}")
async def delete_recipient_endpoint(
    recipient_id: str,
    current_user: dict = Depends(require_roles("admin")),
):
    deleted = await delete_recipient(recipient_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Recipient not found")
    return {"message": "Recipient deleted successfully"}
