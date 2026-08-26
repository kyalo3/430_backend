from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.core.rbac import require_roles
from app.database import impact_collection

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
    rows = [r async for r in impact_collection.find({"verified": True})]
    return {"count": len(rows), "items": rows}
