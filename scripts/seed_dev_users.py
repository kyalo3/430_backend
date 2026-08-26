#!/usr/bin/env python3
"""Create local demo users for each dashboard. Development only."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

DEMO_USERS = [
    {
        "username": "admin",
        "email": "admin@example.com",
        "role": "admin",
        "password": os.getenv("DEV_ADMIN_PASSWORD", "AdminShare1!"),
    },
    {
        "username": "donor",
        "email": "donor@local.dev",
        "role": "donor",
        "password": os.getenv("DEV_DEMO_PASSWORD", "ShareLocal1!"),
    },
    {
        "username": "recipient",
        "email": "recipient@local.dev",
        "role": "recipient",
        "password": os.getenv("DEV_DEMO_PASSWORD", "ShareLocal1!"),
    },
    {
        "username": "volunteer",
        "email": "volunteer@local.dev",
        "role": "volunteer",
        "password": os.getenv("DEV_DEMO_PASSWORD", "ShareLocal1!"),
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _upsert_user(spec: dict, reset_password: bool) -> dict:
    from app.core.security import hash_password, password_is_strong
    from app.database import user_collection
    from app.models.user import get_user_by_email, get_user_by_username, user_helper

    if not password_is_strong(spec["password"]):
        raise SystemExit(f"Password for {spec['username']} does not meet policy.")

    existing = await get_user_by_username(spec["username"]) or await get_user_by_email(spec["email"])
    if existing:
        updates = {"role": spec["role"], "status": "active", "email": spec["email"]}
        if reset_password:
            updates["password"] = hash_password(spec["password"])
        await user_collection.update_one({"username": existing["username"]}, {"$set": updates})
        refreshed = await get_user_by_username(existing["username"])
        return refreshed
    await user_collection.insert_one(
        {
            "username": spec["username"],
            "email": spec["email"],
            "password": hash_password(spec["password"]),
            "role": spec["role"],
            "status": "active",
        }
    )
    created = await get_user_by_username(spec["username"])
    return created


async def _seed_sample_surplus(donor: dict, recipient: dict | None) -> None:
    from app.database import donation_collection, donation_request_collection

    existing = await donation_collection.find_one({"donor_id": donor["id"], "seed_tag": "local-demo"})
    if not existing:
        await donation_collection.insert_one(
            {
                "food_item": "Assorted dry goods",
                "title": "Assorted dry goods",
                "brand": "",
                "description": "Local demo surplus listing so the recipient dashboard is not empty.",
                "quantity": 12,
                "unit": "units",
                "category": "general",
                "condition": "good",
                "price": 0,
                "donor_id": donor["id"],
                "recipient_id": None,
                "status": "available",
                "approx_location": "Nairobi (approx.)",
                "handling_notes": "Collect at a public handover point after assignment.",
                "match_reasons": ["Demo seed for local dashboards"],
                "volunteer_id": None,
                "created_at": _now(),
                "updated_at": _now(),
                "version": 1,
                "seed_tag": "local-demo",
                "history": [{"status": "available", "at": _now(), "by": "seed"}],
            }
        )
    matched = await donation_collection.find_one({"donor_id": donor["id"], "seed_tag": "local-demo-matched"})
    if not matched:
        await donation_collection.insert_one(
            {
                "food_item": "Packaged staples",
                "title": "Packaged staples",
                "brand": "",
                "description": "Matched demo listing so volunteers can accept a handover.",
                "quantity": 6,
                "unit": "packs",
                "category": "general",
                "condition": "good",
                "price": 0,
                "donor_id": donor["id"],
                "recipient_id": recipient["id"] if recipient else None,
                "status": "matched",
                "approx_location": "Westlands area (approx.)",
                "handling_notes": "Public pickup; confirm identity with the assignment code only after accept.",
                "match_reasons": ["Demo seed for volunteer handover"],
                "volunteer_id": None,
                "created_at": _now(),
                "updated_at": _now(),
                "version": 1,
                "seed_tag": "local-demo-matched",
                "history": [{"status": "matched", "at": _now(), "by": "seed"}],
            }
        )
    if recipient:
        need = await donation_request_collection.find_one({"seed_tag": "local-demo-need"})
        if not need:
            from app.models.recipient import get_recipient_by_user_id

            rec_profile = await get_recipient_by_user_id(recipient["id"])
            await donation_request_collection.insert_one(
                {
                    "recipient_id": rec_profile["id"] if rec_profile else recipient["id"],
                    "item": "Dry goods",
                    "custom": "Local demo need",
                    "status": "open",
                    "quantity": 4,
                    "urgency": "normal",
                    "approx_location": "Nairobi (approx.)",
                    "created_at": _now(),
                    "updated_at": _now(),
                    "fulfilled_donation_id": None,
                    "seed_tag": "local-demo-need",
                }
            )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed local Sustainashare dashboard users")
    parser.add_argument("--reset-passwords", action="store_true", default=True)
    parser.add_argument("--keep-passwords", action="store_true", help="Do not overwrite existing passwords")
    args = parser.parse_args()

    env = os.getenv("APP_ENV", "development").lower()
    if env == "production":
        print("Refusing to seed demo users in production.", file=sys.stderr)
        return 1

    from app.database import bind_collections
    from app.services.profiles import ensure_role_profile

    bind_collections()
    reset = args.reset_passwords and not args.keep_passwords
    print("Local dashboard accounts:")
    seeded = {}
    for spec in DEMO_USERS:
        user = await _upsert_user(spec, reset_password=reset)
        await ensure_role_profile(user)
        seeded[spec["role"]] = user
        print(f"  {spec['role']:10}  username={spec['username']:12}  password={spec['password']}")

    if seeded.get("donor"):
        await _seed_sample_surplus(seeded["donor"], seeded.get("recipient"))
        print("  sample surplus + matched handover + need ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
