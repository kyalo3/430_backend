"""Replaceable object storage — disabled until a provider is configured. Files are never stored in MongoDB."""
from __future__ import annotations

from fastapi import HTTPException

from app.core.config import get_settings

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
MAX_BYTES = 5 * 1024 * 1024


class ObjectStorageAdapter:
    def accept_metadata(self, *, content_type: str, size: int, filename: str) -> dict:
        settings = get_settings()
        if not settings.feature_object_storage:
            raise HTTPException(
                501,
                "File uploads are not enabled. Photos stay on a replaceable object store, never in MongoDB.",
            )
        if content_type not in ALLOWED_TYPES:
            raise HTTPException(400, "Unsupported file type")
        if size < 1 or size > MAX_BYTES:
            raise HTTPException(400, "File exceeds size limit")
        safe = "".join(c for c in (filename or "file") if c.isalnum() or c in "._-")[:80]
        return {"status": "accepted", "key": f"pending/{safe}", "provider": "unconfigured"}


storage = ObjectStorageAdapter()
