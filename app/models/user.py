# Get all users helper
async def get_all_users():
    from app.database import db
    users = []
    async for user in db["users"].find():
        users.append(
            User(
                id=str(user["_id"]),
                username=user.get("username", ""),
                email=user.get("email") or "unknown@local",
                role=user.get("role", ""),
                status=user.get("status", "active"),
            )
        )
    return users
from pydantic import BaseModel, EmailStr
from app.utils import get_password_hash, verify_password
from app.database import user_collection
"""
user model
"""




class UserBase(BaseModel):
    """ base model for User """
    username: str
    role: str




class UserCreate(UserBase):
    """ model for creating a user """
    email: EmailStr
    password: str

    



class User(UserBase):
    """ class to represent a User """
    id: str
    email: EmailStr
    status: str = "active"

    class Config:
        """ pydantic configuration for user """
        from_attributes = True




def user_helper(user) -> dict:
    """ helper function to transform user document into dictionary """
    return {
        "id": str(user["_id"]),
        "username": user["username"],
        "email": user.get("email", ""),
        "password": user["password"],
        "role": user.get("role", ""),
        "status": user.get("status", "active"),
    }



async def create_user(user: UserCreate):
    """ creates a new user """
    user_dict = {
        'username': user.username,
        'email': user.email,
        'password': get_password_hash(user.password),
        'role': user.role,
        'status': 'active',
    }
    new_user = await user_collection.insert_one(user_dict)
    created_user = await user_collection.find_one({"_id": new_user.inserted_id})
    return user_helper(created_user)


async def get_user_by_username(username: str):
    """ function that gets a user by username """
    user = await user_collection.find_one({"username": username})
    if user:
        return user_helper(user)
    return None

async def get_user_by_email(email: str):
    """ function that gets a user by email """
    user = await user_collection.find_one({"email": email})
    if user:
        return user_helper(user)
    return None

async def get_user_by_credentials(username: str, email: str, password: str):
    """Fetch a user by their username and password"""
    user = await get_user_by_username(username)
    if not user:
        user = await get_user_by_email(email)
    if not user or not verify_password(password, user["password"]):
        return False
    return user
