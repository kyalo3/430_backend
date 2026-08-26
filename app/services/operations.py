"""Operational metrics from verified and in-flight journeys — no invented conversions."""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Optional

from app.database import donation_collection, impact_collection


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _hours(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if not a or not b:
        return None
    delta = (b - a).total_seconds() / 3600
    if delta < 0:
        return None
    return round(delta, 2)


async def operations_snapshot() -> dict:
    by_status: dict[str, int] = {}
    match_hours: list[float] = []
    fulfil_hours: list[float] = []
    total = 0
    async for doc in donation_collection.find().limit(2000):
        total += 1
        status = doc.get("status") or "unknown"
        by_status[status] = by_status.get(status, 0) + 1
        hist = {h.get("status"): _parse(h.get("at")) for h in (doc.get("history") or []) if h.get("status")}
        created = _parse(doc.get("created_at"))
        matched = hist.get("matched") or hist.get("reserved")
        confirmed = hist.get("recipient_confirmed") or hist.get("completed")
        mh = _hours(created, matched)
        fh = _hours(matched, confirmed)
        if mh is not None:
            match_hours.append(mh)
        if fh is not None:
            fulfil_hours.append(fh)

    verified = await impact_collection.count_documents({"verified": True})
    terminal_fail = sum(by_status.get(s, 0) for s in ("expired", "cancelled", "rejected", "failed", "recalled"))
    return {
        "north_star": "Verified successful fulfilments per active service area per week",
        "verified_fulfilments": verified,
        "listings_sampled": total,
        "by_status": by_status,
        "request_fulfilment_rate": round(verified / total, 4) if total else None,
        "exception_rate": round(terminal_fail / total, 4) if total else None,
        "median_hours_to_match": round(median(match_hours), 2) if match_hours else None,
        "median_hours_match_to_confirm": round(median(fulfil_hours), 2) if fulfil_hours else None,
        "empty": total == 0,
        "methodology": "Times use donation history timestamps. Rates use listing counts, not meal or currency conversion.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
