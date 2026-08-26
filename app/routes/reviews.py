from fastapi import APIRouter, Depends, HTTPException

from app.core.rbac import require_roles
from app.core.security import get_current_user
from app.models.reviews import ReviewCreate, create_review, get_all_reviews, get_reviews_by_user_id

router = APIRouter(tags=["reviews"])


@router.get("/reviews/")
async def get_reviews(current_user: dict = Depends(require_roles("admin"))):
    return await get_all_reviews()


@router.post("/reviews/")
async def register_review(review: ReviewCreate, current_user: dict = Depends(get_current_user)):
    forced = ReviewCreate(title=review.title, content=review.content, rating=review.rating, userId=str(current_user["id"]))
    created = await create_review(forced)
    if isinstance(created, dict):
        return created
    return {
        "id": created,
        "title": review.title,
        "content": review.content,
        "rating": review.rating,
        "user_id": str(current_user["id"]),
    }


@router.get("/reviews/user/{user_id}")
async def reviews_for_user(user_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin" and str(current_user.get("id")) != user_id:
        raise HTTPException(403, "Forbidden")
    return await get_reviews_by_user_id(user_id)
