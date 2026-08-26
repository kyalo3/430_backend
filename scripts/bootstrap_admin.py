#!/usr/bin/env python3
"""One-time administrator bootstrap. Never embeds default passwords."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap a Sustainashare administrator")
    parser.add_argument("--username", default=os.getenv("BOOTSTRAP_ADMIN_USERNAME"))
    parser.add_argument("--email", default=os.getenv("BOOTSTRAP_ADMIN_EMAIL"))
    parser.add_argument("--password", default=os.getenv("BOOTSTRAP_ADMIN_PASSWORD"))
    args = parser.parse_args()

    if not args.username or not args.email or not args.password:
        print("Provide --username/--email/--password or BOOTSTRAP_ADMIN_* env vars.", file=sys.stderr)
        return 1

    from app.core.security import password_is_strong, hash_password
    from app.database import user_collection
    from app.models.user import get_user_by_email, get_user_by_username

    if not password_is_strong(args.password):
        print("Password does not meet strength policy.", file=sys.stderr)
        return 1

    if await get_user_by_username(args.username) or await get_user_by_email(args.email):
        print("User already exists — refusing to overwrite.", file=sys.stderr)
        return 2

    await user_collection.insert_one(
        {
            "username": args.username,
            "email": args.email,
            "password": hash_password(args.password),
            "role": "admin",
            "status": "active",
        }
    )
    print(f"Admin '{args.username}' created. Store the password in your secret manager; it is not logged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
