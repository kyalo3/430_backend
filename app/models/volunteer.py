from pydantic import BaseModel
from bson.objectid import ObjectId
from app.database import volunteer_collection
from typing import Any

"""
volunteer module
"""

class VolunteerBase(BaseModel):
    """ Define the fields for the Volunteer class """
    first_name: str
    last_name: str
    email: str
    id_no: str
    phone_number: str
    gender: str
    address: str

class VolunteerCreate(VolunteerBase):
    """
    Model for creating a volunteer
    """
    pass

class VolunteerUpdate(VolunteerBase):
    """
    Model for updating a volunteer
    """
    pass

class Volunteer(VolunteerBase):
    """
    class to represent a volunteer
    """
    id: str
    user_id: str

    class Config:
        """
        pydantic configuration for volunteer
        """
        from_attributes = True

def volunteer_helper(volunteer: Any) -> dict:
    """
    helper function to transform volunteer document to dictionary
    """
    return {
        "id": str(volunteer["_id"]),
        "user_id": volunteer["user_id"],
        "first_name": volunteer.get("first_name", ""),
        "last_name": volunteer.get("last_name", ""),
        "email": volunteer.get("email", ""),
        "id_no": volunteer.get("id_no", ""),
        "phone_number": volunteer.get("phone_number", ""),
        "gender": volunteer.get("gender", ""),
        "address": volunteer.get("address", ""),
        "service_area": volunteer.get("service_area", ""),
        "availability_notes": volunteer.get("availability_notes", ""),
        "capacity": volunteer.get("capacity", 1),
        "task_types": volunteer.get("task_types", []),
    }

async def create_volunteer(volunteer: VolunteerCreate, user_id: str) -> dict:
    """
    function that creates a new volunteer
    """
    volunteer_dict = volunteer.dict()
    volunteer_dict['user_id'] = user_id
    new_volunteer = await volunteer_collection.insert_one(volunteer_dict)
    return volunteer_helper(await volunteer_collection.find_one({"_id": new_volunteer.inserted_id}))

async def get_volunteer_by_id(volunteer_id: str) -> dict:
    """
    function that gets a volunteer by ID
    """
    volunteer = await volunteer_collection.find_one({"_id": ObjectId(volunteer_id)})
    if volunteer:
        return volunteer_helper(volunteer)
    return None

async def get_volunteer_by_user_id(user_id: str) -> dict:
    """
    function that gets a volunteer by user ID (returns the first match)
    """
    volunteer = await volunteer_collection.find_one({"user_id": user_id})
    if volunteer:
        return volunteer_helper(volunteer)
    return None

async def update_volunteer(volunteer_id: str, volunteer_data: VolunteerUpdate) -> dict:
    """
    function that updates a volunteer
    """
    volunteer = await volunteer_collection.find_one({"_id": ObjectId(volunteer_id)})
    if volunteer:
        updated_volunteer = await volunteer_collection.update_one({"_id": ObjectId(volunteer_id)}, {"$set": volunteer_data.dict()})
        if updated_volunteer:
            return await volunteer_collection.find_one({"_id": ObjectId(volunteer_id)})
    return None

async def delete_volunteer(volunteer_id: str) -> bool:
    """
    function that deletes a volunteer
    """
    volunteer = await volunteer_collection.find_one({"_id": ObjectId(volunteer_id)})
    if volunteer:
        await volunteer_collection.delete_one({"_id": ObjectId(volunteer_id)})
        return True
    return False
