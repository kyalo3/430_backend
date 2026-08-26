from pydantic import BaseModel, EmailStr
from datetime import datetime

from app.database import _CollectionProxy

contact_collection = _CollectionProxy("contacts")


class ContactBase(BaseModel):
    """Base model for Contact"""
    name: str
    email: EmailStr
    message: str


class ContactCreate(ContactBase):
    """Model for creating a contact"""
    pass


class Contact(ContactBase):
    """Class to represent a Contact"""
    id: str
    created_at: str

    class Config:
        """Pydantic configuration for contact"""
        from_attributes = True


def contact_helper(contact) -> dict:
    """Helper function to transform contact document into dictionary"""
    return {
        "id": str(contact["_id"]),
        "name": contact["name"],
        "email": contact["email"],
        "message": contact["message"],
        "created_at": contact.get("created_at", "")
    }


async def create_contact(contact: ContactCreate):
    """Creates a new contact message"""
    contact_dict = contact.dict()
    contact_dict['created_at'] = datetime.utcnow().isoformat()
    new_contact = await contact_collection.insert_one(contact_dict)
    return contact_helper(await contact_collection.find_one({"_id": new_contact.inserted_id}))
