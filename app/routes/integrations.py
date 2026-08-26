"""Webhook foundations behind a feature flag — unfinished partner integrations stay dark."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.rbac import require_roles
from app.core.security import get_current_user
from app.services.storage import storage

router = APIRouter(tags=["integrations"])

SUPPORTED_EVENTS = [
    "donation.matched",
    "donation.recipient_confirmed",
    "fulfilment.accepted",
]


class UploadIntentIn(BaseModel):
    content_type: str
    size: int = Field(..., ge=1)
    filename: str = "file"


@router.get("/integrations/webhooks")
async def webhook_catalog(current_user: dict = Depends(require_roles("admin"))):
    settings = get_settings()
    if not settings.feature_webhooks:
        raise HTTPException(404, "Webhooks are not enabled")
    return {
        "status": "flagged",
        "events": SUPPORTED_EVENTS,
        "note": "Delivery adapter is not wired. Enable FEATURE_WEBHOOKS only after a signed-delivery provider exists.",
    }


@router.post("/storage/intent")
async def storage_intent(body: UploadIntentIn, current_user: dict = Depends(get_current_user)):
    return storage.accept_metadata(content_type=body.content_type, size=body.size, filename=body.filename)
