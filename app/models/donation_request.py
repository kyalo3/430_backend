from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

class DonationRequestCreate(BaseModel):
    recipient_id: str
    item: str
    custom: Optional[str] = None


class DonationRequestUpdate(BaseModel):
    status: Optional[str] = None
    fulfilled_donation_id: Optional[str] = None

class DonationRequestInDB(DonationRequestCreate):
    id: str
    status: str = Field(default="pending")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    fulfilled_donation_id: Optional[str] = None

class DonationRequestResponse(DonationRequestInDB):
    pass
