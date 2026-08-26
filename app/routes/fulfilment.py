from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.rbac import require_roles
from app.services import fulfilment as fulfilment_service

router = APIRouter(tags=["fulfilment"])


class EvidenceIn(BaseModel):
    note: str


class ProgressIn(BaseModel):
    status: str
    note: Optional[str] = None


@router.get("/fulfilments/eligible")
async def eligible_tasks(current_user: dict = Depends(require_roles("volunteer", "admin"))):
    return await fulfilment_service.list_eligible(current_user)


@router.get("/fulfilments/mine")
async def my_tasks(current_user: dict = Depends(require_roles("volunteer", "admin"))):
    return await fulfilment_service.list_mine(str(current_user["id"]))


@router.post("/fulfilments/{donation_id}/accept")
async def accept_task(donation_id: str, current_user: dict = Depends(require_roles("volunteer"))):
    return await fulfilment_service.accept_assignment(donation_id, current_user)


@router.post("/fulfilments/{donation_id}/evidence")
async def add_evidence(
    donation_id: str,
    body: EvidenceIn,
    current_user: dict = Depends(require_roles("volunteer", "admin")),
):
    return await fulfilment_service.add_evidence(donation_id, current_user, body.note)


@router.post("/fulfilments/{donation_id}/progress")
async def progress_task(
    donation_id: str,
    body: ProgressIn,
    current_user: dict = Depends(require_roles("volunteer", "admin")),
):
    return await fulfilment_service.progress(donation_id, current_user, body.status, body.note)
