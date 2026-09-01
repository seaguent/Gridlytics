import pytest

from app.projections.availability import classify_availability


@pytest.mark.parametrize("status", ["Out", "OUT", "IR", "PUP", "Sus", "NA"])
def test_out_like_statuses_are_unavailable(status):
    assert classify_availability(status, is_bye=False) == "unavailable"


def test_doubtful_status_is_doubtful():
    assert classify_availability("Doubtful", is_bye=False) == "doubtful"


def test_questionable_status_is_questionable():
    assert classify_availability("Questionable", is_bye=False) == "questionable"


@pytest.mark.parametrize("status", [None, "", "Active", "ACTIVE"])
def test_healthy_or_unknown_status_defaults_healthy(status):
    assert classify_availability(status, is_bye=False) == "healthy"


def test_bye_week_is_unavailable_regardless_of_injury_status():
    assert classify_availability(None, is_bye=True) == "unavailable"
    assert classify_availability("Questionable", is_bye=True) == "unavailable"


def test_bye_takes_priority_even_over_out_status():
    assert classify_availability("Out", is_bye=True) == "unavailable"
