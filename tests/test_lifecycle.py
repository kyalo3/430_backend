"""Unit tests — lifecycle and matching (no DB)."""
from app.core.lifecycle import DONATION_TRANSITIONS, InvalidTransition, assert_transition
from app.services.matching import score_match


def test_donation_happy_path_transitions():
    path = [
        ("draft", "submitted"),
        ("submitted", "under_review"),
        ("under_review", "available"),
        ("available", "reserved"),
        ("reserved", "matched"),
        ("matched", "pickup_scheduled"),
        ("pickup_scheduled", "collected"),
        ("collected", "in_transit"),
        ("in_transit", "delivered"),
        ("delivered", "recipient_confirmed"),
        ("recipient_confirmed", "completed"),
    ]
    for cur, nxt in path:
        assert_transition(DONATION_TRANSITIONS, cur, nxt)


def test_invalid_transition_raises():
    try:
        assert_transition(DONATION_TRANSITIONS, "draft", "completed")
        assert False, "expected InvalidTransition"
    except InvalidTransition:
        pass


def test_matching_reasons_explainable():
    donation = {"category": "produce", "quantity": 10, "approx_location": "Nairobi", "food_item": "produce"}
    need = {"item": "produce", "quantity": 5, "approx_location": "Nairobi", "urgency": "high"}
    score, reasons = score_match(donation, need)
    assert score > 50
    assert any("Category" in r or "category" in r.lower() or "overlap" in r.lower() for r in reasons)
