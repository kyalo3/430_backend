"""MongoDB access — collections proxy until first use (avoids import-time SRV DNS hard-fail)."""
from __future__ import annotations

import os
from typing import Any, Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGO_DETAILS = os.getenv("MONGO_DETAILS")

_client: Optional[AsyncIOMotorClient] = None
_db = None
_bound = False


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        if not MONGO_DETAILS:
            raise RuntimeError(
                "MONGO_DETAILS is required. Copy .env.example to .env and set a MongoDB URI."
            )
        _client = AsyncIOMotorClient(
            MONGO_DETAILS,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
        )
    return _client


def bind_collections() -> Any:
    global _db, _bound
    if _bound and _db is not None:
        return _db
    _db = get_client().food_donation
    _bound = True
    return _db


class _CollectionProxy:
    def __init__(self, name: str):
        self._name = name

    def _real(self):
        return bind_collections().get_collection(self._name)

    def __getattr__(self, item: str):
        return getattr(self._real(), item)


donor_collection = _CollectionProxy("donors")
recipient_collection = _CollectionProxy("recipients")
donation_collection = _CollectionProxy("donations")
user_collection = _CollectionProxy("users")
volunteer_collection = _CollectionProxy("volunteers")
review_collection = _CollectionProxy("reviews")
donation_request_collection = _CollectionProxy("donation_requests")
audit_collection = _CollectionProxy("audit_events")
match_collection = _CollectionProxy("matches")
fulfilment_collection = _CollectionProxy("fulfilments")
impact_collection = _CollectionProxy("impact_records")
consent_collection = _CollectionProxy("consents")
notification_collection = _CollectionProxy("notifications")
refresh_token_collection = _CollectionProxy("refresh_tokens")
organisation_collection = _CollectionProxy("organisations")
organisation_member_collection = _CollectionProxy("organisation_members")
reference_snapshot_collection = _CollectionProxy("reference_snapshots")
verification_code_collection = _CollectionProxy("verification_codes")


class _DbProxy:
    def __getattr__(self, item: str):
        return getattr(bind_collections(), item)

    def __getitem__(self, item: str):
        return bind_collections()[item]


database = _DbProxy()
db = database


# main.py uses `client`
class _ClientProxy:
    def __getattr__(self, item: str):
        return getattr(get_client(), item)


client = _ClientProxy()


async def ensure_indexes() -> None:
    bind_collections()
    await user_collection.create_index("username", unique=True)
    await user_collection.create_index("email", unique=True)
    await donor_collection.create_index("user_id")
    await recipient_collection.create_index("user_id")
    await volunteer_collection.create_index("user_id")
    await donation_collection.create_index([("status", 1), ("category", 1)])
    await donation_collection.create_index("donor_id")
    await donation_collection.create_index([("status", 1), ("updated_at", -1)])
    await donation_request_collection.create_index([("status", 1), ("recipient_id", 1)])
    await match_collection.create_index([("donation_id", 1), ("status", 1)])
    await fulfilment_collection.create_index("donation_id")
    await fulfilment_collection.create_index("volunteer_id")
    await donation_collection.create_index("volunteer_id")
    await notification_collection.create_index([("user_id", 1), ("created_at", -1)])
    try:
        await notification_collection.create_index(
            [("user_id", 1), ("event", 1), ("entity_id", 1)],
            unique=True,
            name="notify_idempotent",
        )
    except Exception:
        # Existing duplicates in a long-lived database must not block startup.
        pass
    await user_collection.create_index("status")
    await consent_collection.create_index([("user_id", 1), ("purpose", 1), ("at", -1)])
    await audit_collection.create_index(
        [("entity_type", 1), ("entity_id", 1), ("created_at", -1)]
    )
    await impact_collection.create_index("donation_id", unique=True)
    await refresh_token_collection.create_index("jti", unique=True)
    await organisation_collection.create_index("slug", unique=True)
    await organisation_member_collection.create_index([("org_id", 1), ("user_id", 1)], unique=True)
    await donation_collection.create_index("organisation_id")
    await reference_snapshot_collection.create_index("key", unique=True)
    await verification_code_collection.create_index([("destination", 1), ("channel", 1)], unique=True)
