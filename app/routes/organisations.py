from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.rbac import require_roles
from app.core.security import get_current_user
from app.services import organisations as org_service

router = APIRouter(tags=["organisations"])


class OrgCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    type: str = "community"
    approx_location: str = ""


class OrgVerifyIn(BaseModel):
    reason: str = Field(min_length=5)


@router.get("/organisations/")
async def directory():
    """Verified partner names only — no member identities."""
    return await org_service.list_directory()


@router.get("/organisations/mine")
async def mine(current_user: dict = Depends(require_roles("donor", "volunteer", "admin"))):
    return await org_service.list_mine(str(current_user["id"]))


@router.post("/organisations/", status_code=201)
async def create_org(body: OrgCreateIn, current_user: dict = Depends(get_current_user)):
    return await org_service.create_organisation(
        current_user,
        name=body.name,
        org_type=body.type,
        approx_location=body.approx_location,
    )


@router.get("/organisations/admin")
async def admin_list(current_user: dict = Depends(require_roles("admin"))):
    return await org_service.list_all_admin()


@router.post("/organisations/{org_id}/verify")
async def verify_org(org_id: str, body: OrgVerifyIn, current_user: dict = Depends(require_roles("admin"))):
    return await org_service.verify_organisation(org_id, current_user, body.reason)
