from fastapi import APIRouter, Depends, HTTPException, status

from app.core.rbac import require_roles
from app.core.security import get_current_user
from app.models.volunteer import (
    VolunteerCreate,
    VolunteerUpdate,
    create_volunteer,
    delete_volunteer,
    get_volunteer_by_id,
    get_volunteer_by_user_id,
    update_volunteer,
)

router = APIRouter(tags=["volunteers"])


@router.get("/volunteers/")
async def get_current_user_volunteer(current_user: dict = Depends(require_roles("volunteer", "admin"))):
    volunteer = await get_volunteer_by_user_id(current_user["id"])
    if not volunteer:
        raise HTTPException(status_code=404, detail="Volunteer profile not found")
    return volunteer


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
