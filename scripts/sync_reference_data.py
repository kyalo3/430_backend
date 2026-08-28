"""Refresh official reference snapshots (World Bank). Bundled county/category lists do not need a network call."""
from __future__ import annotations

import asyncio
import json
import os
import sys

os.environ.setdefault("APP_ENV", "development")

from app.services.opendata import sync_world_bank  # noqa: E402


async def main() -> int:
    result = await sync_world_bank(force=True)
    print(json.dumps({"world_bank": {k: v for k, v in result.items() if k != "snapshot"}, "status": result.get("status")}, indent=2))
    return 0 if result.get("status") in {"fetched", "cache_fresh", "disabled"} else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
