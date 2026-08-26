from fastapi import APIRouter, Depends, HTTPException
from typing import List

from bson.objectid import ObjectId

from app.core.audit import write_audit
from app.core.rbac import require_roles
from app.core.security import get_current_user
from app.database import donor_collection, recipient_collection, user_collection, volunteer_collection
from app.models.user import User, get_all_users

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=User)
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.get("/users/", response_model=List[User])
async def get_users(current_user: dict = Depends(require_roles("admin"))):
    return await get_all_users()


@router.delete("/users/{user_id}", response_model=dict)
async def delete_user(user_id: str, reason: str, current_user: dict = Depends(require_roles("admin"))):
    if not reason or len(reason.strip()) < 5:
        raise HTTPException(status_code=400, detail="Admin deletions require a reason")
    if current_user.get("id") == user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    try:
        object_id = ObjectId(user_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid user id") from exc
    user_doc = await user_collection.find_one({"_id": object_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")
    role = user_doc.get("role")
    if role == "donor":
        await donor_collection.delete_many({"user_id": user_id})
    elif role == "recipient":
        await recipient_collection.delete_many({"user_id": user_id})
    elif role == "volunteer":
        await volunteer_collection.delete_many({"user_id": user_id})
    await user_collection.delete_one({"_id": object_id})
    await write_audit(
        actor_id=str(current_user.get("id")),
        actor_role="admin",
        action="user.deleted",
        entity_type="user",
        entity_id=user_id,
        reason=reason,
    )
    return {"message": "User deleted successfully"}


@router.post("/users/{user_id}/suspend")
async def suspend_user(user_id: str, reason: str, current_user: dict = Depends(require_roles("admin"))):
    if not reason or len(reason.strip()) < 5:
        raise HTTPException(400, "Suspension requires a reason")
    try:
        oid = ObjectId(user_id)
    except Exception as exc:
        raise HTTPException(400, "Invalid user id") from exc
    result = await user_collection.update_one({"_id": oid}, {"$set": {"status": "suspended"}})
    if result.matched_count == 0:
        raise HTTPException(404, "User not found")
    await write_audit(
        actor_id=str(current_user.get("id")),
        actor_role="admin",
        action="user.suspended",
        entity_type="user",
        entity_id=user_id,
        reason=reason,
    )
    return {"message": "User suspended"}


@router.post("/users/{user_id}/restore")
async def restore_user(user_id: str, reason: str, current_user: dict = Depends(require_roles("admin"))):
    if not reason or len(reason.strip()) < 5:
        raise HTTPException(400, "Restoration requires a reason")
    try:
        oid = ObjectId(user_id)
    except Exception as exc:
        raise HTTPException(400, "Invalid user id") from exc
    result = await user_collection.update_one({"_id": oid}, {"$set": {"status": "active"}})
    if result.matched_count == 0:
        raise HTTPException(404, "User not found")
    await write_audit(
        actor_id=str(current_user.get("id")),
        actor_role="admin",
        action="user.restored",
        entity_type="user",
        entity_id=user_id,
        reason=reason,
    )
    return {"message": "User restored"}
