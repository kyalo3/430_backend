from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List

from app.core.rbac import require_roles
from app.core.security import get_current_user
from app.database import volunteer_collection
from app.models.volunteer import (
    VolunteerCreate,
    VolunteerUpdate,
    create_volunteer,
    delete_volunteer,
    get_volunteer_by_id,
    get_volunteer_by_user_id,
    update_volunteer,
)
from app.services.profiles import ensure_role_profile

router = APIRouter(tags=["volunteers"])


class VolunteerLogisticsIn(BaseModel):
    service_area: str = ""
    availability_notes: str = ""
    capacity: int = Field(1, ge=1, le=50)
    task_types: List[str] = []


@router.get("/volunteers/")
async def get_current_user_volunteer(current_user: dict = Depends(require_roles("volunteer", "admin"))):
    volunteer = await get_volunteer_by_user_id(current_user["id"])
    if not volunteer:
        volunteer = await ensure_role_profile(current_user)
    if not volunteer:
        raise HTTPException(status_code=404, detail="Volunteer profile not found")
    return volunteer


@router.put("/volunteers/me/logistics")
async def update_logistics(
    body: VolunteerLogisticsIn,
    current_user: dict = Depends(require_roles("volunteer")),
):
    volunteer = await get_volunteer_by_user_id(current_user["id"])
    if not volunteer:
        volunteer = await ensure_role_profile(current_user)
    if not volunteer:
        raise HTTPException(404, "Volunteer profile not found")
    from bson.objectid import ObjectId

    await volunteer_collection.update_one(
        {"_id": ObjectId(volunteer["id"])},
        {
            "$set": {
                "service_area": body.service_area.strip()[:120],
                "availability_notes": body.availability_notes.strip()[:400],
                "capacity": body.capacity,
                "task_types": [t.strip() for t in body.task_types if t.strip()][:8],
            }
        },
    )
    return await get_volunteer_by_user_id(current_user["id"])


@router.post("/volunteers/")
async def create_volunteer_endpoint(
    volunteer: VolunteerCreate,
    current_user: dict = Depends(require_roles("volunteer", "admin")),
):
    return await create_volunteer(volunteer, user_id=current_user["id"])


@router.get("/volunteers/{volunteer_id}")
async def get_volunteer_endpoint(
    volunteer_id: str,
    current_user: dict = Depends(get_current_user),
):
    volunteer = await get_volunteer_by_id(volunteer_id)
    if not volunteer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Volunteer not found")
    if current_user.get("role") == "admin":
        return volunteer
    if volunteer.get("user_id") == current_user.get("id"):
        return volunteer
    # Limited public volunteer card
    return {
        "id": volunteer.get("id"),
        "first_name": volunteer.get("first_name"),
        "services_area": volunteer.get("approx_location") or volunteer.get("address", "")[:20] + "…",
        "privacy": "contact_details_hidden",
    }


@router.put("/volunteers/{volunteer_id}")
async def update_volunteer_endpoint(
    volunteer_id: str,
    volunteer: VolunteerUpdate,
    current_user: dict = Depends(require_roles("volunteer", "admin")),
):
    existing = await get_volunteer_by_id(volunteer_id)
    if not existing:
        raise HTTPException(404, "Volunteer not found")
    if current_user.get("role") != "admin" and existing.get("user_id") != current_user.get("id"):
        raise HTTPException(403, "Forbidden")
    updated = await update_volunteer(volunteer_id, volunteer)
    if not updated:
        raise HTTPException(404, "Volunteer not found")
    return updated


@router.delete("/volunteers/{volunteer_id}")
async def delete_volunteer_endpoint(
    volunteer_id: str,
    current_user: dict = Depends(require_roles("admin")),
):
    deleted = await delete_volunteer(volunteer_id)
    if not deleted:
        raise HTTPException(404, "Volunteer not found")
    return {"message": "Volunteer deleted successfully"}
