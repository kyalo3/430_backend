"""Immutable audit event helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.database import audit_collection


async def write_audit(
    *,
    actor_id: Optional[str],
    actor_role: Optional[str],
    action: str,
    entity_type: str,
    entity_id: str,
    reason: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    doc = {
        "actor_id": actor_id,
        "actor_role": actor_role,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "reason": reason,
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await audit_collection.insert_one(doc)
    return str(result.inserted_id)
