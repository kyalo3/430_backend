"""Logistics classification — load class, pickup windows, volunteer capacity gates.

Mode A: community volunteers (small/medium by default).
Mode B: partner logistics orgs for bulk / vehicle / explicit partner mode.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

LOAD_CLASSES = {
    "small": {"capacity_cost": 1, "volunteer_ok": True, "label": "Small (hand-carried)"},
    "medium": {"capacity_cost": 2, "volunteer_ok": True, "label": "Medium (bags/boxes)"},
    "bulk": {"capacity_cost": 3, "volunteer_ok": False, "label": "Bulk (partner preferred)"},
    "cold": {"capacity_cost": 2, "volunteer_ok": True, "requires_task": "cold", "label": "Cold-chain sensitive"},
    "vehicle": {"capacity_cost": 3, "volunteer_ok": True, "requires_task": "vehicle", "label": "Needs a vehicle"},
}

LOGISTICS_MODES = {"volunteer", "partner", "either"}


def normalize_load_class(value: Optional[str]) -> str:
    key = (value or "small").strip().lower()
    if key not in LOAD_CLASSES:
        raise HTTPException(400, f"Invalid load_class. Use: {', '.join(sorted(LOAD_CLASSES))}")
    return key


def normalize_logistics_mode(value: Optional[str], *, load_class: str) -> str:
    mode = (value or "").strip().lower()
    if not mode:
        mode = "partner" if load_class == "bulk" else "either"
    if mode not in LOGISTICS_MODES:
        raise HTTPException(400, "Invalid logistics_mode. Use: volunteer, partner, either")
    if load_class == "bulk" and mode == "volunteer":
        # Bulk must not silently land on random volunteers.
        mode = "partner"
    return mode


def capacity_cost(load_class: str) -> int:
    return int(LOAD_CLASSES.get(load_class, LOAD_CLASSES["small"])["capacity_cost"])


def compose_collection_window(
    *,
    window_start: Optional[str],
    window_end: Optional[str],
    collection_window: Optional[str],
) -> dict[str, Any]:
    """Prefer structured ISO windows; keep free-text as human label."""
    label = (collection_window or "").strip()[:200]
    start = (window_start or "").strip() or None
    end = (window_end or "").strip() or None
    for raw, name in ((start, "window_start"), (end, "window_end")):
        if not raw:
            continue
        try:
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(400, f"{name} must be ISO-8601") from exc
    if start and end:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if e < s:
            raise HTTPException(400, "window_end must be after window_start")
        if not label:
            label = f"{s.date().isoformat()} {s.strftime('%H:%M')}–{e.strftime('%H:%M')} UTC"
    return {
        "window_start": start,
        "window_end": end,
        "collection_window": label or None,
    }


def normalize_listing_fields(payload: dict) -> dict:
    """Mutate a donation create payload with logistics fields."""
    load_class = normalize_load_class(payload.get("load_class"))
    logistics_mode = normalize_logistics_mode(payload.get("logistics_mode"), load_class=load_class)
    windows = compose_collection_window(
        window_start=payload.get("window_start"),
        window_end=payload.get("window_end"),
        collection_window=payload.get("collection_window"),
    )
    payload["load_class"] = load_class
    payload["logistics_mode"] = logistics_mode
    payload["window_start"] = windows["window_start"]
    payload["window_end"] = windows["window_end"]
    payload["collection_window"] = windows["collection_window"]
    payload["capacity_cost"] = capacity_cost(load_class)
    return payload


def volunteer_open_slots(profile: dict | None, active_assignments: int) -> int:
    capacity = int((profile or {}).get("capacity") or 1)
    return max(0, capacity - max(0, active_assignments))


def volunteer_can_see(doc: dict, profile: dict | None, *, open_slots: int) -> tuple[bool, str]:
    """Whether a volunteer should see a task in eligible list."""
    mode = (doc.get("logistics_mode") or "either").lower()
    load_class = (doc.get("load_class") or "small").lower()
    meta = LOAD_CLASSES.get(load_class, LOAD_CLASSES["small"])
    if mode == "partner":
        return False, "Assigned to partner logistics"
    if not meta.get("volunteer_ok", True):
        return False, "Load class requires partner logistics"
    cost = int(doc.get("capacity_cost") or meta["capacity_cost"])
    if open_slots < cost:
        return False, "Insufficient remaining capacity"
    required = meta.get("requires_task")
    if required:
        types = [str(t).lower() for t in ((profile or {}).get("task_types") or [])]
        if required not in types and "any" not in types:
            return False, f"Task type '{required}' required"
    return True, "ok"


def volunteer_can_accept(doc: dict, profile: dict | None, *, open_slots: int) -> None:
    ok, reason = volunteer_can_see(doc, profile, open_slots=open_slots)
    if not ok:
        raise HTTPException(409, reason)
