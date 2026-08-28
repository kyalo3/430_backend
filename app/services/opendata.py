"""Public reference data — geography, food taxonomy, official SDG context.

Never mixed into impact_records. Never used to rank recipients.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.database import reference_snapshot_collection

_DATA = Path(__file__).resolve().parent.parent / "data" / "kenya_counties.json"
WORLD_BANK_KEY = "worldbank:KEN:SN.ITK.DEFC.ZS"
CACHE_DAYS = 7

CATALOG = [
    {
        "id": "gadm-kenya-counties",
        "name": "Kenya counties (GADM-aligned)",
        "source": "https://gadm.org/",
        "status": "now",
        "sync": "bundled",
        "sdgs": ["11", "17"],
        "model_fields": ["approx_location", "service_area"],
    },
    {
        "id": "open-food-facts-taxonomy",
        "name": "Open Food Facts category language",
        "source": "https://world.openfoodfacts.org/",
        "status": "now",
        "sync": "bundled",
        "sdgs": ["2", "12"],
        "model_fields": ["category", "food_item"],
    },
    {
        "id": "world-bank-undernourishment",
        "name": "World Bank SN.ITK.DEFC.ZS",
        "source": "https://data.worldbank.org/indicator/SN.ITK.DEFC.ZS",
        "status": "now",
        "sync": "http-cache",
        "sdgs": ["2"],
        "model_fields": [],
    },
    {
        "id": "openstreetmap",
        "name": "OpenStreetMap / GeoFabrik",
        "source": "https://www.openstreetmap.org/",
        "status": "next",
        "sync": "not-wired",
        "sdgs": ["11"],
        "model_fields": ["approx_location"],
    },
    {
        "id": "geonames",
        "name": "GeoNames",
        "source": "https://www.geonames.org/",
        "status": "next",
        "sync": "not-wired",
        "sdgs": ["11"],
        "model_fields": ["approx_location", "service_area"],
    },
    {
        "id": "county-normalize",
        "name": "Kenya county place normaliser",
        "source": "bundled GADM-aligned counties",
        "status": "now",
        "sync": "bundled",
        "sdgs": ["11"],
        "model_fields": ["approx_location", "service_area"],
    },
    {
        "id": "hdx-kenya",
        "name": "Humanitarian Data Exchange (Kenya food security)",
        "source": "https://data.humdata.org/",
        "status": "next",
        "sync": "not-wired",
        "sdgs": ["2", "17"],
        "model_fields": [],
    },
]

FOOD_CATEGORIES = [
    {"id": "produce", "label": "Fresh produce", "off_group": "fruits-and-vegetables", "sdg": "2"},
    {"id": "bakery", "label": "Bakery", "off_group": "breads", "sdg": "12"},
    {"id": "dairy", "label": "Dairy", "off_group": "dairies", "sdg": "2"},
    {"id": "pantry", "label": "Pantry / dry goods", "off_group": "groceries", "sdg": "12"},
    {"id": "prepared", "label": "Prepared meals", "off_group": "meals", "sdg": "2"},
    {"id": "protein", "label": "Protein / cooked meats", "off_group": "meats", "sdg": "2"},
    {"id": "non_food", "label": "Non-food usable goods", "off_group": None, "sdg": "12"},
    {"id": "general", "label": "General surplus", "off_group": None, "sdg": "12"},
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache()
def kenya_counties() -> list[str]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def service_areas() -> list[dict[str, str]]:
    rows = []
    for name in kenya_counties():
        slug = name.lower().replace(" county", "").replace(" ", "-")
        rows.append(
            {
                "id": slug,
                "name": name,
                "country": "KE",
                "admin_level": "county",
                "source": "gadm-aligned-bundled",
            }
        )
    return rows


def food_categories() -> list[dict[str, Any]]:
    return list(FOOD_CATEGORIES)


def normalize_place(query: str) -> dict[str, Any]:
    """Match free text to a Kenya county without calling OSM yet (privacy-safe approx areas)."""
    raw = (query or "").strip()
    if not raw:
        return {"query": raw, "matched": False, "suggestions": service_areas()[:5]}
    needle = raw.lower().replace(" county", "").strip()
    exact = []
    partial = []
    for area in service_areas():
        name = area["name"].lower()
        slug = area["id"]
        if needle == slug or needle == name or needle == name.replace(" county", ""):
            exact.append(area)
        elif needle in name or needle in slug:
            partial.append(area)
    hits = exact or partial
    return {
        "query": raw,
        "matched": bool(hits),
        "canonical": hits[0] if hits else None,
        "suggestions": hits[:8] or service_areas()[:5],
        "engine": "gadm_county_normalize_v1",
        "note": "Approximate county matching only. Exact addresses are not geocoded.",
    }


def _empty_context(*, reason: str, snapshot: dict | None = None) -> dict[str, Any]:
    payload = {
        "indicator": "SN.ITK.DEFC.ZS",
        "indicator_name": "Prevalence of undernourishment (% of population)",
        "country": "KEN",
        "sdg": "2.1.1",
        "source": "World Bank Open Data",
        "source_url": "https://api.worldbank.org/v2/country/KEN/indicator/SN.ITK.DEFC.ZS",
        "usage": "National context for partners. Not a Sustainashare impact figure.",
        "available": False,
        "value": None,
        "year": None,
        "fetched_at": None,
        "reason": reason,
    }
    if snapshot:
        payload.update(
            {
                "available": snapshot.get("value") is not None,
                "value": snapshot.get("value"),
                "year": snapshot.get("year"),
                "fetched_at": snapshot.get("fetched_at"),
                "reason": None if snapshot.get("value") is not None else reason,
                "stale": True,
            }
        )
    return payload


async def _load_snapshot() -> dict | None:
    return await reference_snapshot_collection.find_one({"key": WORLD_BANK_KEY})


async def _save_snapshot(value: Any, year: str | None) -> dict[str, Any]:
    doc = {
        "key": WORLD_BANK_KEY,
        "source": "worldbank",
        "value": value,
        "year": year,
        "fetched_at": _now().isoformat(),
    }
    await reference_snapshot_collection.update_one({"key": WORLD_BANK_KEY}, {"$set": doc}, upsert=True)
    return doc


def _is_fresh(snapshot: dict | None) -> bool:
    if not snapshot or not snapshot.get("fetched_at"):
        return False
    raw = snapshot.get("fetched_at")
    if isinstance(raw, datetime):
        fetched = raw
    else:
        try:
            fetched = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return _now() - fetched < timedelta(days=CACHE_DAYS)


async def fetch_world_bank() -> dict[str, Any]:
    url = "https://api.worldbank.org/v2/country/KEN/indicator/SN.ITK.DEFC.ZS"
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.get(url, params={"format": "json", "mrnev": 1})
        response.raise_for_status()
        payload = response.json()
    rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else None
    if not rows:
        raise ValueError("World Bank returned no observations")
    latest = rows[0]
    value = latest.get("value")
    if value is None:
        raise ValueError("Latest observation has no value")
    return await _save_snapshot(value, latest.get("date"))


async def sync_world_bank(*, force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    snapshot = await _load_snapshot()
    if not settings.feature_world_bank:
        return {"source": WORLD_BANK_KEY, "status": "disabled", "snapshot": snapshot}
    if snapshot and _is_fresh(snapshot) and not force:
        return {"source": WORLD_BANK_KEY, "status": "cache_fresh", "snapshot": snapshot}
    try:
        saved = await fetch_world_bank()
        return {"source": WORLD_BANK_KEY, "status": "fetched", "snapshot": saved}
    except Exception as exc:
        return {
            "source": WORLD_BANK_KEY,
            "status": "upstream_unavailable",
            "error": str(exc),
            "snapshot": snapshot,
        }


def _context_from_snapshot(snapshot: dict, *, stale: bool) -> dict[str, Any]:
    return {
        "indicator": "SN.ITK.DEFC.ZS",
        "indicator_name": "Prevalence of undernourishment (% of population)",
        "country": "KEN",
        "sdg": "2.1.1",
        "source": "World Bank Open Data",
        "source_url": "https://api.worldbank.org/v2/country/KEN/indicator/SN.ITK.DEFC.ZS",
        "usage": "National context for partners. Not a Sustainashare impact figure.",
        "available": True,
        "value": snapshot.get("value"),
        "year": snapshot.get("year"),
        "fetched_at": snapshot.get("fetched_at"),
        "reason": None,
        "stale": stale,
    }


async def sdg_context() -> dict[str, Any]:
    settings = get_settings()
    snapshot = await _load_snapshot()
    if not settings.feature_world_bank:
        # Flag off: never present a cached World Bank figure as live context.
        return _empty_context(reason="FEATURE_WORLD_BANK is disabled", snapshot=None)
    if not (snapshot and _is_fresh(snapshot) and snapshot.get("value") is not None):
        result = await sync_world_bank(force=True)
        snapshot = result.get("snapshot")
        if not (snapshot and snapshot.get("value") is not None):
            return _empty_context(reason=result.get("error") or "World Bank upstream unavailable", snapshot=snapshot)
    return _context_from_snapshot(snapshot, stale=not _is_fresh(snapshot))
