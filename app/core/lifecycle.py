"""Donation and need lifecycle state machines — server-enforced only."""
from __future__ import annotations

from typing import Dict, Set

DONATION_TRANSITIONS: Dict[str, Set[str]] = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"under_review", "cancelled", "rejected"},
    "under_review": {"available", "rejected", "cancelled"},
    "available": {"reserved", "expired", "recalled", "cancelled"},
    "reserved": {"matched", "available", "cancelled", "expired"},
    "matched": {"pickup_scheduled", "cancelled", "disputed"},
    "pickup_scheduled": {"collected", "failed", "cancelled", "disputed"},
    "collected": {"in_transit", "failed", "disputed"},
    "in_transit": {"delivered", "failed", "disputed"},
    "delivered": {"recipient_confirmed", "disputed", "failed"},
    "recipient_confirmed": {"completed", "disputed"},
    "completed": set(),
    "expired": set(),
    "cancelled": set(),
    "rejected": set(),
    "recalled": set(),
    "failed": {"disputed", "cancelled"},
    "disputed": {"under_review", "cancelled", "completed"},
}

NEED_TRANSITIONS: Dict[str, Set[str]] = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"verified", "rejected", "cancelled"},
    "verified": {"open", "rejected", "cancelled"},
    "open": {"partially_matched", "fully_matched", "expired", "cancelled"},
    "partially_matched": {"fully_matched", "open", "expired", "cancelled", "disputed"},
    "fully_matched": {"fulfilled", "disputed", "cancelled"},
    "fulfilled": set(),
    "rejected": set(),
    "cancelled": set(),
    "expired": set(),
    "disputed": {"open", "cancelled", "fulfilled"},
}

# Who may attempt which transition (role → allowed target statuses broadly gated in service)
DONATION_ROLE_ACTIONS = {
    "donor": {"submitted", "cancelled", "recalled"},
    "admin": set().union(*DONATION_TRANSITIONS.values()) | set(DONATION_TRANSITIONS.keys()),
    "recipient": {"recipient_confirmed", "disputed"},
    "volunteer": {"collected", "in_transit", "delivered", "failed", "disputed"},
}


class InvalidTransition(Exception):
    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from '{current}' to '{target}'")


def assert_transition(machine: Dict[str, Set[str]], current: str, target: str) -> None:
    allowed = machine.get(current, set())
    if target not in allowed:
        raise InvalidTransition(current, target)
