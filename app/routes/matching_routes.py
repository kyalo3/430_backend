from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.rbac import require_roles
from app.database import donation_collection, donation_request_collection
from app.services.donations import donation_public
from app.services.matching import rank_donations_for_need

router = APIRouter(tags=["matching"])


class MatchQuery(BaseModel):
    need_id: str | None = None
    item: str | None = None
    quantity: int = 1
    urgency: str = "normal"
    approx_location: str | None = None
    category: str | None = None


@router.post("/matching/suggest")
async def suggest_matches(body: MatchQuery, current_user: dict = Depends(require_roles("recipient", "admin"))):
    need = {
        "item": body.item,
        "quantity": body.quantity,
        "urgency": body.urgency,
        "approx_location": body.approx_location,
        "category": body.category,
    }
    if body.need_id:
        from bson.objectid import ObjectId

        try:
            req = await donation_request_collection.find_one({"_id": ObjectId(body.need_id)})
        except Exception as exc:
            raise HTTPException(400, "Invalid need id") from exc
        if not req:
            raise HTTPException(404, "Need not found")
        need = {
            "item": req.get("item"),
            "quantity": req.get("quantity", 1),
            "urgency": req.get("urgency", "normal"),
            "approx_location": req.get("approx_location"),
            "category": req.get("category") or "general",
        }

    available = [donation_public(d) async for d in donation_collection.find({"status": "available"}).limit(100)]
    ranked = rank_donations_for_need(available, need)
    return {
        "engine": "rules_v1",
        "explanation": "Transparent category, quantity, location and urgency scoring. No opaque AI.",
        "need": {"item": need.get("item"), "category": need.get("category"), "approx_location": need.get("approx_location")},
        "results": ranked,
    }
