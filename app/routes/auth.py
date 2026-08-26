"""Legacy auth module — re-exports core security and keeps authenticate_user."""
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password as get_password_hash,
    verify_password,
)
from app.models.user import get_user_by_email, get_user_by_username


async def authenticate_user(username: str, password: str):
    user = await get_user_by_username(username)
    if not user:
        user = await get_user_by_email(username)
    if not user or not verify_password(password, user["password"]):
        return False
    return user
