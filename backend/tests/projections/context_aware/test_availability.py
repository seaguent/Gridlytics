import pytest

from app.projections.context_aware.availability import gate_availability


@pytest.mark.parametrize("status", ["OUT", "IR", "Sus"])
def test_unavailable_statuses_are_blocked(status):
    blocked, resolved = gate_availability(status, is_bye=False)
    assert blocked is True
    assert resolved == "unavailable"


def test_bye_is_blocked_regardless_of_injury_status():
    blocked, resolved = gate_availability(None, is_bye=True)
    assert blocked is True
    assert resolved == "unavailable"


def test_doubtful_is_not_blocked():
    blocked, resolved = gate_availability("Doubtful", is_bye=False)
    assert blocked is False
    assert resolved == "doubtful"


def test_questionable_is_not_blocked():
    blocked, resolved = gate_availability("Questionable", is_bye=False)
    assert blocked is False
    assert resolved == "questionable"


def test_healthy_is_not_blocked():
    blocked, resolved = gate_availability(None, is_bye=False)
    assert blocked is False
    assert resolved == "healthy"
