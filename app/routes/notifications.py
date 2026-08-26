from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.services.notifications import list_for_user, mark_read

router = APIRouter(tags=["notifications"])


@router.get("/notifications/me")
async def my_notifications(current_user: dict = Depends(get_current_user)):
    return await list_for_user(str(current_user["id"]))


@router.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: str, current_user: dict = Depends(get_current_user)):
    ok = await mark_read(notification_id, str(current_user["id"]))
    if not ok:
        raise HTTPException(404, "Notification not found")
    return {"ok": True}
