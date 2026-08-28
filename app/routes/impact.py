from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.core.rbac import require_roles
from app.database import impact_collection
from app.services.operations import operations_snapshot

router = APIRouter(tags=["impact"])


@router.get("/impact/summary")
async def impact_summary():
    """Public aggregate stats — verified fulfilments only. No fabricated figures."""
    cursor = impact_collection.find({"verified": True})
    by_category = {}
    total_qty = 0
    count = 0
    async for row in cursor:
        count += 1
        qty = int(row.get("quantity") or 0)
        total_qty += qty
        cat = row.get("category") or "general"
        by_category[cat] = by_category.get(cat, 0) + qty
    return {
        "verified_fulfilments": count,
        "quantity_redistributed": total_qty,
        "by_category": by_category,
        "methodology": "Counts only impact_records created after recipient confirmation (or admin-verified completion). No meal/carbon conversion is applied.",
        "empty": count == 0,
    }


@router.get("/impact/mine")
async def my_impact(current_user: dict = Depends(get_current_user)):
    from app.database import donation_collection

    if current_user.get("role") == "donor":
        donation_ids = [
            str(d["_id"])
            async for d in donation_collection.find({"donor_id": str(current_user["id"])})
        ]
        rows = [r async for r in impact_collection.find({"donation_id": {"$in": donation_ids}, "verified": True})]
    else:
        rows = []
    return {
        "items": [
            {
                "donation_id": r.get("donation_id"),
                "category": r.get("category"),
                "quantity": r.get("quantity"),
                "unit": r.get("unit"),
                "completed_at": r.get("completed_at"),
            }
            for r in rows
        ],
        "methodology": "Verified fulfilments linked to your donations only.",
    }


@router.get("/impact/admin")
async def admin_impact(current_user: dict = Depends(require_roles("admin"))):
    items = []
    async for row in impact_collection.find({"verified": True}):
        items.append(
            {
                "id": str(row.get("_id")),
                "donation_id": row.get("donation_id"),
                "category": row.get("category"),
                "quantity": row.get("quantity"),
                "unit": row.get("unit"),
                "verified": row.get("verified"),
                "completed_at": row.get("completed_at"),
            }
        )
    return {"count": len(items), "items": items}


@router.get("/impact/organisation/{org_id}")
async def organisation_impact(org_id: str, current_user: dict = Depends(get_current_user)):
    """Verified impact pack for an organisation — parties and admins only."""
    from app.database import donation_collection
    from app.services.organisations import assert_member, public_org
    from app.database import organisation_collection
    from bson.objectid import ObjectId

    try:
        org = await organisation_collection.find_one({"_id": ObjectId(org_id)})
    except Exception:
        org = None
    if not org:
        from fastapi import HTTPException

        raise HTTPException(404, "Organisation not found")
    if current_user.get("role") != "admin":
        await assert_member(str(current_user["id"]), org_id)

    donation_ids = [
        str(d["_id"])
        async for d in donation_collection.find({"organisation_id": org_id})
    ]
    items = []
    total_qty = 0
    async for r in impact_collection.find({"donation_id": {"$in": donation_ids}, "verified": True}):
        qty = int(r.get("quantity") or 0)
        total_qty += qty
        items.append(
            {
                "donation_id": r.get("donation_id"),
                "category": r.get("category"),
                "quantity": qty,
                "unit": r.get("unit"),
                "completed_at": r.get("completed_at"),
            }
        )
    return {
        "organisation": public_org(org),
        "verified_fulfilments": len(items),
        "quantity_redistributed": total_qty,
        "items": items,
        "methodology": (
            "Counts only impact_records created after recipient confirmation "
            "(or admin-verified completion) for listings tagged to this organisation. "
            "No meal/carbon conversion is applied."
        ),
        "empty": len(items) == 0,
    }


@router.get("/impact/operations")
async def operations(current_user: dict = Depends(require_roles("admin"))):
    return await operations_snapshot()
