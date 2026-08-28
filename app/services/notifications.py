"""In-app notifications with replaceable email/SMS adapters.

Email is sent when FEATURE_EMAIL=true and SMTP_* are configured.
In development without SMTP, messages are recorded on the notification doc (channel_status)
so ops can verify wiring without a provider.
"""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Optional

from bson.objectid import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.database import notification_collection, user_collection

logger = logging.getLogger("sustainashare.notifications")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NotificationAdapter:
    """Replaceable channel adapters."""

    def send_email(self, to: str, subject: str, body: str) -> str:
        settings = get_settings()
        if not settings.feature_email:
            return "skipped_feature_off"
        if not to:
            return "skipped_no_recipient"
        if not settings.smtp_host or not settings.smtp_from:
            if settings.app_env != "production":
                logger.info("email.dev_log to=%s subject=%s", to, subject)
                return "dev_logged"
            return "skipped_no_smtp"

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to
        msg.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password or "")
                smtp.send_message(msg)
            return "sent"
        except Exception as exc:  # noqa: BLE001 — adapter must not break journeys
            logger.warning("email.send_failed to=%s err=%s", to, exc)
            return f"failed:{type(exc).__name__}"

    def send_sms(self, to: str, body: str) -> str:
        settings = get_settings()
        if not settings.feature_sms:
            return "skipped_feature_off"
        if not to:
            return "skipped_no_recipient"
        # Provider stub — wire Twilio/Africa's Talking later behind the same flag.
        if settings.app_env != "production":
            logger.info("sms.dev_log to=%s body=%s", to, body[:120])
            return "dev_logged"
        return "skipped_no_provider"


_adapter = NotificationAdapter()


async def _user_email(user_id: str) -> Optional[str]:
    try:
        doc = await user_collection.find_one({"_id": ObjectId(user_id)})
    except Exception:
        doc = await user_collection.find_one({"id": user_id})
    if not doc:
        # Some installs store string ids mirrored on documents
        doc = await user_collection.find_one({"username": user_id})
    if not doc:
        return None
    return doc.get("email")


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
        "channel_status": {},
    }
    try:
        result = await notification_collection.insert_one(doc)
    except DuplicateKeyError:
        raced = await notification_collection.find_one(
            {"user_id": user_id, "event": event, "entity_id": entity_id}
        )
        return str(raced["_id"]) if raced else ""

    dest = email or await _user_email(user_id)
    email_status = _adapter.send_email(dest or "", title, body) if dest else "skipped_no_email"
    channel_status = {"email": email_status}
    await notification_collection.update_one(
        {"_id": result.inserted_id},
        {"$set": {"channel_status": channel_status}},
    )
    return str(result.inserted_id)


async def notify_user(**kwargs: Any) -> str:
    """Alias used by fulfilment/donation services."""
    return await notify(**kwargs)


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
                "channel_status": row.get("channel_status") or {},
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
