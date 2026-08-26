"""Failed-login throttling — generic errors, no account enumeration copy."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.database import user_collection

FAILURE_LIMIT = 5
LOCK_MINUTES = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_locked(doc: dict[str, Any]) -> bool:
    until = _parse(doc.get("locked_until"))
    return bool(until and until > _now())


async def record_failure(doc: dict[str, Any]) -> bool:
    """Increment failures. Returns True if the account is now locked."""
    fails = int(doc.get("failed_login_count") or 0) + 1
    update: dict[str, Any] = {
        "failed_login_count": fails,
        "last_failed_login_at": _now().isoformat(),
    }
    locked = fails >= FAILURE_LIMIT
    if locked:
        update["locked_until"] = (_now() + timedelta(minutes=LOCK_MINUTES)).isoformat()
    await user_collection.update_one({"_id": doc["_id"]}, {"$set": update})
    return locked


async def clear_failures(doc: dict[str, Any]) -> None:
    await user_collection.update_one(
        {"_id": doc["_id"]},
        {"$set": {"failed_login_count": 0}, "$unset": {"locked_until": "", "last_failed_login_at": ""}},
    )
