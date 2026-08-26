"""Explainable rules-based matching (no opaque AI)."""
from __future__ import annotations

from typing import Any


def score_match(donation: dict, need: dict) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    d_cat = (donation.get("category") or donation.get("food_item") or "").lower()
    n_item = (need.get("item") or need.get("category") or "").lower()
    if d_cat and n_item and (d_cat in n_item or n_item in d_cat):
        score += 40
        reasons.append(f"Category/item overlap ('{d_cat}' ≈ '{n_item}')")

    d_qty = int(donation.get("quantity") or 0)
    n_qty = int(need.get("quantity") or 1)
    if d_qty >= n_qty:
        score += 20
        reasons.append(f"Quantity sufficient ({d_qty} ≥ {n_qty})")
    elif d_qty > 0:
        score += 5
        reasons.append(f"Partial quantity available ({d_qty})")

    if donation.get("approx_location") and need.get("approx_location"):
        if str(donation["approx_location"]).lower() == str(need["approx_location"]).lower():
            score += 25
            reasons.append("Same approximate service area")
        else:
            score += 5
            reasons.append("Different areas — logistics may be required")

    urgency = (need.get("urgency") or "normal").lower()
    if urgency == "high":
        score += 10
        reasons.append("Need marked high urgency")

    if donation.get("expiry_at"):
        score += 5
        reasons.append("Donation has a usable window — prioritise timely match")

    if not reasons:
        reasons.append("General availability match (low confidence)")
        score += 1

    return score, reasons


def rank_donations_for_need(donations: list[dict], need: dict, limit: int = 10) -> list[dict[str, Any]]:
    ranked = []
    for d in donations:
        score, reasons = score_match(d, need)
        ranked.append({"donation": d, "score": score, "reasons": reasons})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:limit]
