

from fastapi import APIRouter, Depends, HTTPException
from app.models.recipient import Recipient, RecipientCreate, create_recipient, update_recipient, delete_recipient
from app.routes.auth import get_current_user
from app.models.user import User
from typing import List
from app.models.recipient import get_recipient_by_id, get_recipient_by_user_id, get_recipients

router = APIRouter()

# Get current user's recipient profile
@router.get("/recipients/", response_model=Recipient)
async def get_current_user_recipient(current_user: User = Depends(get_current_user)):
    recipient = await get_recipient_by_user_id(current_user["id"])
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient profile not found")
    return recipient


@router.post("/recipients/", response_model=Recipient)
async def create_recipient_endpoint(recipient: RecipientCreate, current_user: User = Depends(get_current_user)):
    """creates a new recipient, allows a recipient user to create a new
    by probiding necessary recipient data
    Args:
        recipient: recipient data to be created
        current_user: current logged_in user, obtained through dependency
        injection
    Returns:
        dict: a dictionary containing the created recipients's details.
    Raises:
        HTTPException: if there is an error in recipient creation
    """
    recipient = await create_recipient(recipient, user_id=current_user["id"])

    return {"id": recipient.get("id"), "name": recipient.get("name"), "user_id": current_user["id"]}

@router.get("/recipients/{recipient_id}", response_model=Recipient)
async def get_recipient_endpoint(recipient_id: str):
    """gets a recipient by id
    Args:
        recipient_id: id of the recipient to be fetched
    Returns:
        dict: a dictionary containing the recipient's details.
    Raises:
        HTTPException: if the recipient is not found
    """
    recipient = await get_recipient_by_id(recipient_id)
    if recipient:
        return recipient
    raise HTTPException(status_code=404, detail=f"Recipient with id {recipient_id} not found")

@router.get("/recipients/all", response_model=List[Recipient])
async def get_recipients_endpoint():
    """gets all recipients"""
    recipients = await get_recipients()
    return recipients

@router.put("/recipients/{recipient_id}", response_model=Recipient)
async def update_recipient_endpoint(recipient_id: str, recipient: RecipientCreate):
    """updates a recipient by id
    Args:
        recipient_id: id of the recipient to be updated
        recipient: updated recipient data
    Returns:
        dict: a dictionary containing the updated recipient's details.
    """
    existing_recipient = await get_recipient_by_id(recipient_id)
    if not existing_recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    updated_recipient = await update_recipient(recipient_id, recipient)
    if not updated_recipient:
        raise HTTPException(status_code=500, detail="Failed to update recipient")
    return updated_recipient

@router.delete("/recipients/{recipient_id}", response_model=dict)
async def delete_recipient_endpoint(recipient_id: str):
    """deletes a recipient by id
    Args:
        recipient_id: id of the recipient to be deleted
    """
    deleted_recipient = await delete_recipient(recipient_id)
    if not deleted_recipient:
        raise HTTPException(status_code=500, detail="Failed to delete recipient")
    return {"message": "Recipient deleted successfully"}
