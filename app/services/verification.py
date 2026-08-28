"""Email verification codes — replaceable adapter; no provider required in development."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.database import verification_code_collection


def _now() -> datetime:
    return datetime.now(timezone.utc)


class VerificationAdapter:
    def issue_code(self, channel: str, destination: str) -> str | None:
        settings = get_settings()
        if not settings.verification_required:
            return None
        code = "424242" if settings.app_env != "production" else secrets.token_hex(3)
        # Fire-and-forget persistence happens via async helper from routes.
        return code

    def verify_code_sync(self, destination: str, code: str) -> bool:
        settings = get_settings()
        if not settings.verification_required:
            return True
        return bool(destination and code and len(code) >= 4)


async def store_code(destination: str, code: str, *, channel: str = "email") -> None:
    await verification_code_collection.update_one(
        {"destination": destination.lower(), "channel": channel},
        {
            "$set": {
                "destination": destination.lower(),
                "channel": channel,
                "code": code,
                "expires_at": (_now() + timedelta(hours=24)).isoformat(),
                "consumed": False,
            }
        },
        upsert=True,
    )


async def consume_code(destination: str, code: str, *, channel: str = "email") -> bool:
    settings = get_settings()
    if not settings.verification_required:
        return True
    doc = await verification_code_collection.find_one(
        {"destination": destination.lower(), "channel": channel, "consumed": False}
    )
    if not doc:
        return False
    try:
        expires = datetime.fromisoformat(str(doc.get("expires_at")).replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < _now():
        return False
    if str(doc.get("code")) != str(code).strip():
        return False
    await verification_code_collection.update_one({"_id": doc["_id"]}, {"$set": {"consumed": True}})
    return True
