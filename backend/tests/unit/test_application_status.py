"""Unit tests for the documented application transition graph."""

from __future__ import annotations

import pytest

from app.models.enums import ApplicationStatus
from app.services.applications import TRANSITIONS, allowed_transitions


def test_transition_graph_matches_documented_lifecycle() -> None:
    assert allowed_transitions(ApplicationStatus.QUEUED) == {"prepared", "withdrawn", "closed"}
    assert allowed_transitions(ApplicationStatus.PREPARED) == {"submitted", "withdrawn", "closed"}
    assert allowed_transitions(ApplicationStatus.SUBMITTED) == {
        "interviewing",
        "assessment",
        "rejected",
        "offer",
        "withdrawn",
        "closed",
    }
    assert allowed_transitions(ApplicationStatus.INTERVIEWING) == {
        "assessment",
        "rejected",
        "offer",
        "withdrawn",
        "closed",
    }
    assert allowed_transitions(ApplicationStatus.ASSESSMENT) == {
        "interviewing",
        "rejected",
        "offer",
        "withdrawn",
        "closed",
    }
    assert allowed_transitions(ApplicationStatus.OFFER) == {"withdrawn", "closed"}


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for status in (
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.CLOSED,
    ):
        assert allowed_transitions(status) == set()
        assert TRANSITIONS[str(status)] == set()


@pytest.mark.parametrize(
    "value",
    [
        "queued",
        "prepared",
        "submitted",
        "interviewing",
        "assessment",
        "rejected",
        "offer",
        "withdrawn",
        "closed",
    ],
)
def test_all_statuses_are_valid_enum_values(value: str) -> None:
    ApplicationStatus(value)  # must not raise


def test_unknown_status_value_is_rejected() -> None:
    with pytest.raises(ValueError):
        ApplicationStatus("hired")
