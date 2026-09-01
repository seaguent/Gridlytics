import pandas as pd
import pytest

from app.analytics.standings import compute_expected_wins, compute_recent_form, compute_schedule_strength


@pytest.fixture
def two_week_scores() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"team_id": "A", "week": 1, "points": 100},
            {"team_id": "B", "week": 1, "points": 80},
            {"team_id": "C", "week": 1, "points": 90},
            {"team_id": "D", "week": 1, "points": 70},
            {"team_id": "A", "week": 2, "points": 95},
            {"team_id": "B", "week": 2, "points": 85},
            {"team_id": "C", "week": 2, "points": 100},
            {"team_id": "D", "week": 2, "points": 60},
        ]
    )


def test_expected_wins_matches_hand_calculation(two_week_scores):
    expected = compute_expected_wins(two_week_scores)

    # Week 1 ranks D,B,C,A -> fractions 0,1/3,2/3,1; week 2 ranks D,B,A,C -> fractions 0,1/3,2/3,1.
    assert expected["A"] == pytest.approx(1.667, abs=0.001)
    assert expected["B"] == pytest.approx(0.667, abs=0.001)
    assert expected["C"] == pytest.approx(1.667, abs=0.001)
    assert expected["D"] == pytest.approx(0.0, abs=0.001)


def test_expected_wins_sum_per_week_equals_number_of_matchups(two_week_scores):
    # 4 teams = 2 matchups/week = 1 "win" distributed per matchup = 2 weeks x 2 = 4 total
    expected = compute_expected_wins(two_week_scores)
    assert sum(expected.values()) == pytest.approx(4.0, abs=0.001)


@pytest.fixture
def two_week_scores_with_opponents() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"team_id": "A", "week": 1, "points": 100, "opponent_team_id": "B"},
            {"team_id": "B", "week": 1, "points": 80, "opponent_team_id": "A"},
            {"team_id": "C", "week": 1, "points": 90, "opponent_team_id": "D"},
            {"team_id": "D", "week": 1, "points": 70, "opponent_team_id": "C"},
            {"team_id": "A", "week": 2, "points": 95, "opponent_team_id": "C"},
            {"team_id": "C", "week": 2, "points": 100, "opponent_team_id": "A"},
            {"team_id": "B", "week": 2, "points": 85, "opponent_team_id": "D"},
            {"team_id": "D", "week": 2, "points": 60, "opponent_team_id": "B"},
        ]
    )


def test_schedule_strength_matches_hand_calculation(two_week_scores_with_opponents):
    # Season averages A=97.5 B=82.5 C=95 D=65; each team's strength is the avg of its two opponents' averages.
    strength = compute_schedule_strength(two_week_scores_with_opponents)

    assert strength["A"] == pytest.approx(88.75, abs=0.01)
    assert strength["B"] == pytest.approx(81.25, abs=0.01)
    assert strength["C"] == pytest.approx(81.25, abs=0.01)
    assert strength["D"] == pytest.approx(88.75, abs=0.01)


def test_recent_form_only_uses_the_last_n_weeks():
    scores = pd.DataFrame(
        [
            {"team_id": "A", "week": 1, "points": 50},
            {"team_id": "A", "week": 2, "points": 100},
            {"team_id": "A", "week": 3, "points": 110},
            {"team_id": "B", "week": 1, "points": 200},
            {"team_id": "B", "week": 2, "points": 60},
            {"team_id": "B", "week": 3, "points": 70},
        ]
    )

    # num_weeks=2 -> only weeks 2 and 3 count, week 1 is ignored for both teams.
    form = compute_recent_form(scores, num_weeks=2)

    assert form["A"] == pytest.approx((100 + 110) / 2)
    assert form["B"] == pytest.approx((60 + 70) / 2)
