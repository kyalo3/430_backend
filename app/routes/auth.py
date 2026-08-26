"""Legacy auth module — re-exports core security and keeps authenticate_user."""
from app.core.lockout import clear_failures, is_locked, record_failure
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password as get_password_hash,
    verify_password,
)
from app.database import user_collection
from app.models.user import user_helper

LOCKED = object()


async def authenticate_user(username: str, password: str):
    doc = await user_collection.find_one({"$or": [{"username": username}, {"email": username}]})
    if not doc:
        return False
    if doc.get("status") in {"anonymised", "pending_deletion"}:
        return False
    if is_locked(doc):
        return LOCKED
    if not verify_password(password, doc.get("password", "")):
        await record_failure(doc)
        refreshed = await user_collection.find_one({"_id": doc["_id"]})
        if refreshed and is_locked(refreshed):
            return LOCKED
        return False
    await clear_failures(doc)
    return user_helper(doc)
