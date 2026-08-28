"""Public reference datasets used for matching, coverage, and partner context."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.audit import write_audit
from app.core.rbac import require_roles
from app.services import opendata

router = APIRouter(tags=["reference"])


class PlaceNormalizeIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=120)


@router.get("/platform/reference/catalog")
async def catalog():
    return {
        "theory": "Public datasets contextualise geography, listing language, and SDG reporting. They never replace verified fulfilments.",
        "datasets": opendata.CATALOG,
        "source_index": "https://github.com/awesomedata/awesome-public-datasets",
    }


@router.get("/platform/reference/service-areas")
async def service_areas():
    areas = opendata.service_areas()
    return {"country": "KE", "count": len(areas), "items": areas}


@router.get("/platform/reference/food-categories")
async def food_categories():
    return {
        "items": opendata.food_categories(),
        "note": "Aligned to Open Food Facts group language. Not a product catalogue or shop inventory.",
    }


@router.get("/platform/reference/sdg-context")
async def sdg_context():
    return await opendata.sdg_context()


@router.post("/platform/reference/normalize-place")
async def normalize_place(body: PlaceNormalizeIn):
    return opendata.normalize_place(body.query)


@router.post("/platform/reference/sync")
async def sync_reference(current_user: dict = Depends(require_roles("admin"))):
    result = await opendata.sync_world_bank(force=True)
    await write_audit(
        actor_id=str(current_user.get("id")),
        actor_role="admin",
        action="reference.synced",
        entity_type="reference_snapshot",
        entity_id="worldbank:KEN:SN.ITK.DEFC.ZS",
        reason="Admin refresh of official SDG context",
        metadata={"status": result.get("status")},
    )
    return {"bundled": ["kenya_counties", "food_categories"], "world_bank": result}
