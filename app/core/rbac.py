"""Role-based access control helpers."""
from __future__ import annotations

from typing import Callable, Iterable

from fastapi import Depends, HTTPException, status

from app.core.security import get_current_user

PUBLIC_ROLES = {"donor", "recipient", "volunteer"}
ALL_ROLES = PUBLIC_ROLES | {"admin", "partner"}


def require_roles(*roles: str) -> Callable:
    allowed = set(roles)

    async def _dependency(current_user: dict = Depends(get_current_user)) -> dict:
        role = current_user.get("role")
        if role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _dependency


def assert_owner_or_admin(resource_user_id: str, current_user: dict) -> None:
    if current_user.get("role") == "admin":
        return
    if str(current_user.get("id")) != str(resource_user_id):
        raise HTTPException(status_code=403, detail="Not allowed for this resource")


def redact_recipient(doc: dict) -> dict:
    """Strip sensitive recipient fields for non-privileged responses."""
    if not doc:
        return doc
    safe = {k: v for k, v in doc.items() if k not in {"id_no", "phone_number", "address", "house_hold_members", "email"}}
    safe["privacy"] = "sensitive_fields_redacted"
    return safe
