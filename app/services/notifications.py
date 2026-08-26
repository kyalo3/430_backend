"""In-app notifications with a replaceable email/SMS adapter (no-op unless enabled)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson.objectid import ObjectId

from app.core.config import get_settings
from app.database import notification_collection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NotificationAdapter:
    """Replaceable channel. Local/dev defaults to log-only."""

    def send_email(self, to: str, subject: str, body: str) -> None:
        settings = get_settings()
        if settings.app_env == "production":
            # Adapter not wired to a provider — must not silently claim delivery.
            return
        _ = (to, subject, body)

    def send_sms(self, to: str, body: str) -> None:
        _ = (to, body)


_adapter = NotificationAdapter()


async def notify(
    *,
    user_id: str,
    title: str,
    body: str,
    event: str,
    entity_type: str = "donation",
    entity_id: str = "",
    email: Optional[str] = None,
) -> str:
    """Idempotent-ish: skip if same event+entity+user already exists."""
    existing = await notification_collection.find_one(
        {"user_id": user_id, "event": event, "entity_id": entity_id}
    )
    if existing:
        return str(existing["_id"])
    doc = {
        "user_id": user_id,
        "title": title,
        "body": body,
        "event": event,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "read": False,
        "created_at": _now(),
    }
    result = await notification_collection.insert_one(doc)
    if email:
        _adapter.send_email(email, title, body)
    return str(result.inserted_id)


async def list_for_user(user_id: str, limit: int = 40) -> list[dict[str, Any]]:
    limit = min(limit, 100)
    rows = []
    async for row in notification_collection.find({"user_id": user_id}).sort("created_at", -1).limit(limit):
        rows.append(
            {
                "id": str(row["_id"]),
                "title": row.get("title"),
                "body": row.get("body"),
                "event": row.get("event"),
                "entity_id": row.get("entity_id"),
                "read": bool(row.get("read")),
                "created_at": row.get("created_at"),
            }
        )
    return rows


async def mark_read(notification_id: str, user_id: str) -> bool:
    try:
        oid = ObjectId(notification_id)
    except Exception:
        return False
    result = await notification_collection.update_one(
        {"_id": oid, "user_id": user_id},
        {"$set": {"read": True}},
    )
    return result.matched_count == 1
