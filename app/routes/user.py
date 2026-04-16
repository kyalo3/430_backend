
from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordRequestForm
from typing import List
from typing import Optional
from app.models.user import User, UserCreate, create_user, get_user_by_username, get_user_by_email, get_all_users
from app.models.donor import DonorCreate, create_donor
from app.models.recipient import RecipientCreate, create_recipient
from app.models.volunteer import VolunteerCreate, create_volunteer
from app.routes.auth import authenticate_user, create_access_token, get_current_user
from app.database import user_collection, donor_collection, recipient_collection, volunteer_collection
from bson.objectid import ObjectId

router = APIRouter()

#registration endpoint
@router.post("/register", response_model=User, status_code=status.HTTP_201_CREATED)
async def register_user(user: UserCreate, admin_code: Optional[str] = Body(default=None)):
    # Restrict admin registration
    if user.role == "admin":
        # Use a secret code for admin registration
        SECRET_ADMIN_CODE = "supersecret2025"  # Change this to a secure value and keep it secret
        if admin_code != SECRET_ADMIN_CODE:
            raise HTTPException(status_code=403, detail="Invalid admin registration code.")
    existing_user = await get_user_by_username(user.username)
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    existing_email = await get_user_by_email(user.email)
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = await create_user(user)
    return new_user

# Get current authenticated user (for admin and general profile fetch)
@router.get("/users/me", response_model=User)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

# GET all users endpoint for dashboard
@router.get("/users/", response_model=List[User])
async def get_users(current_user: User = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view all users")
    users = await get_all_users()
    return users


@router.delete("/users/{user_id}", response_model=dict)
async def delete_user(user_id: str, current_user: User = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete users")

    if current_user.get("id") == user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    try:
        object_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user id")

    user_doc = await user_collection.find_one({"_id": object_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    role = user_doc.get("role")
    if role == "donor":
        await donor_collection.delete_many({"user_id": user_id})
    elif role == "recipient":
        await recipient_collection.delete_many({"user_id": user_id})
    elif role == "volunteer":
        await volunteer_collection.delete_many({"user_id": user_id})

    delete_result = await user_collection.delete_one({"_id": object_id})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "User deleted successfully"}


import logging

# Login endpoint
@router.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        logging.error(f"Authentication failed for user: {form_data.username}")
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    # Defensive: check for username attribute or key
    username = user.username if hasattr(user, 'username') else user.get('username', None)
    if not username:
        logging.error(f"User object missing username: {user}")
        raise HTTPException(status_code=500, detail="User data error: missing username")
    access_token = create_access_token({"sub": username})
    return {"access_token": access_token, "token_type": "bearer"}


async def get_user_by_credentials(username: str, email: str):
    """Fetch a user by their username and email"""
    user = await get_user_by_username(username)
    if user:
        return user
    user = await get_user_by_email(email)
    if user:
        return user
    return None
