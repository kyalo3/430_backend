"""Unit tests for logistics gates (no DB)."""
from fastapi import HTTPException

from app.services.logistics import (
    normalize_listing_fields,
    volunteer_can_see,
    volunteer_open_slots,
)


def test_bulk_defaults_to_partner_mode():
    payload = normalize_listing_fields({"load_class": "bulk", "food_item": "rice"})
    assert payload["logistics_mode"] == "partner"
    assert payload["capacity_cost"] == 3


def test_structured_window_builds_label():
    payload = normalize_listing_fields(
        {
            "load_class": "small",
            "window_start": "2026-09-01T08:00:00+00:00",
            "window_end": "2026-09-01T12:00:00+00:00",
        }
    )
    assert payload["collection_window"]
    assert "2026-09-01" in payload["collection_window"]


def test_capacity_gate_hides_oversized_load():
    profile = {"capacity": 2, "task_types": ["handover"]}
    open_slots = volunteer_open_slots(profile, active_assignments=0)
    ok, _ = volunteer_can_see(
        {"load_class": "vehicle", "capacity_cost": 3, "logistics_mode": "either"},
        profile,
        open_slots=open_slots,
    )
    assert ok is False


def test_partner_mode_hidden_from_volunteers():
    ok, reason = volunteer_can_see(
        {"load_class": "small", "logistics_mode": "partner", "capacity_cost": 1},
        {"capacity": 5, "task_types": []},
        open_slots=5,
    )
    assert ok is False
    assert "partner" in reason.lower()


def test_cold_requires_task_type():
    ok, _ = volunteer_can_see(
        {"load_class": "cold", "capacity_cost": 2, "logistics_mode": "either"},
        {"capacity": 5, "task_types": ["handover"]},
        open_slots=5,
    )
    assert ok is False
    ok2, _ = volunteer_can_see(
        {"load_class": "cold", "capacity_cost": 2, "logistics_mode": "either"},
        {"capacity": 5, "task_types": ["cold"]},
        open_slots=5,
    )
    assert ok2 is True


def test_invalid_window_order_raises():
    try:
        normalize_listing_fields(
            {
                "load_class": "small",
                "window_start": "2026-09-01T12:00:00+00:00",
                "window_end": "2026-09-01T08:00:00+00:00",
            }
        )
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400
