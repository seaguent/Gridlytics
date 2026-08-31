import pandas as pd
import pytest

from app.projections.uncertainty import compute_floor_ceiling_confidence


def test_compute_floor_ceiling_confidence_matches_hand_calculation():
    # scores: 10, 15, 20, 15, 10 -> mean=14, sample std (ddof=1) ~= 4.1833
    scores = pd.Series([10, 15, 20, 15, 10])

    floor, ceiling, confidence = compute_floor_ceiling_confidence(scores)

    assert floor == pytest.approx(9.817, abs=0.005)
    assert ceiling == pytest.approx(18.183, abs=0.005)
    assert confidence == pytest.approx(0.770, abs=0.005)


def test_compute_floor_ceiling_confidence_perfectly_consistent_player():
    # Every game the same score -> zero variance -> full confidence,
    # floor/ceiling collapse to the mean.
    scores = pd.Series([15, 15, 15, 15])

    floor, ceiling, confidence = compute_floor_ceiling_confidence(scores)

    assert floor == pytest.approx(15.0)
    assert ceiling == pytest.approx(15.0)
    assert confidence == pytest.approx(1.0)


def test_compute_floor_ceiling_confidence_single_data_point():
    # A single game can't have a variance -- treat it the same as
    # perfectly consistent (nothing to disagree with yet).
    scores = pd.Series([20])

    floor, ceiling, confidence = compute_floor_ceiling_confidence(scores)

    assert floor == pytest.approx(20.0)
    assert ceiling == pytest.approx(20.0)
    assert confidence == pytest.approx(1.0)


def test_compute_floor_ceiling_confidence_never_goes_negative():
    # A volatile low-scoring player shouldn't get a negative floor.
    scores = pd.Series([0, 1, 20, 0, 1])

    floor, _, _ = compute_floor_ceiling_confidence(scores)

    assert floor >= 0.0


def test_compute_floor_ceiling_confidence_more_volatile_player_has_lower_confidence():
    consistent = pd.Series([15, 16, 14, 15, 15])
    volatile = pd.Series([2, 28, 5, 25, 4])

    _, _, consistent_confidence = compute_floor_ceiling_confidence(consistent)
    _, _, volatile_confidence = compute_floor_ceiling_confidence(volatile)

    assert consistent_confidence > volatile_confidence
