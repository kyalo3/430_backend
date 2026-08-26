"""Email/phone verification adapter — disabled in local development by default."""
from __future__ import annotations

from app.core.config import get_settings


class VerificationAdapter:
    def issue_code(self, channel: str, destination: str) -> str | None:
        settings = get_settings()
        if not settings.verification_required:
            return None
        _ = (channel, destination)
        return "queued"

    def verify_code(self, destination: str, code: str) -> bool:
        settings = get_settings()
        if not settings.verification_required:
            return True
        return bool(destination and code and len(code) >= 4)
