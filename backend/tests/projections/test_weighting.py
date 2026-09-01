import pandas as pd
import pytest

from app.projections.weighting import compute_weighted_recent_form


@pytest.fixture
def five_week_scores() -> pd.DataFrame:
    # Weeks 1-5: 20, 8, 12, 18, 21 (week 5 is most recent)
    return pd.DataFrame(
        [
            {"team_id": "A", "week": 1, "points": 20},
            {"team_id": "A", "week": 2, "points": 8},
            {"team_id": "A", "week": 3, "points": 12},
            {"team_id": "A", "week": 4, "points": 18},
            {"team_id": "A", "week": 5, "points": 21},
        ]
    )


def test_weighted_recent_form_matches_hand_calculation(five_week_scores):
    # decay=0.7 weights (newest to oldest) 1, 0.7, 0.49, 0.343, 0.2401 -> weighted mean ~= 16.958.
    result = compute_weighted_recent_form(five_week_scores, num_weeks=5, decay=0.7)
    assert result["A"] == pytest.approx(16.958, abs=0.005)


def test_weighted_recent_form_with_decay_one_equals_plain_average(five_week_scores):
    # decay=1.0 means every week gets equal weight -> collapses to plain mean.
    result = compute_weighted_recent_form(five_week_scores, num_weeks=5, decay=1.0)
    assert result["A"] == pytest.approx((20 + 8 + 12 + 18 + 21) / 5)


def test_weighted_recent_form_reacts_faster_than_plain_average(five_week_scores):
    # A low decay should pull the projection toward the most recent game (21) more than a plain average.
    plain_average = (20 + 8 + 12 + 18 + 21) / 5
    weighted = compute_weighted_recent_form(five_week_scores, num_weeks=5, decay=0.5)["A"]
    assert weighted > plain_average
    assert weighted < 21
