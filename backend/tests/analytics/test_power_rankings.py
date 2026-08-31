import pandas as pd
import pytest

from app.analytics.power_rankings import compute_power_rankings


@pytest.fixture
def three_team_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "team_id": "A",
                "win_pct": 0.8,
                "points_per_game": 110,
                "expected_win_pct": 0.7,
                "recent_points_per_game": 115,
            },
            {
                "team_id": "B",
                "win_pct": 0.5,
                "points_per_game": 100,
                "expected_win_pct": 0.5,
                "recent_points_per_game": 95,
            },
            {
                "team_id": "C",
                "win_pct": 0.2,
                "points_per_game": 90,
                "expected_win_pct": 0.3,
                "recent_points_per_game": 80,
            },
        ]
    )


def test_power_rankings_best_team_scores_100_worst_scores_0(three_team_stats):
    # A leads every single metric -> normalizes to 1.0 on all four -> 100.
    # C trails every metric -> normalizes to 0.0 on all four -> 0.
    result = compute_power_rankings(three_team_stats)

    a_score = result.loc[result["team_id"] == "A", "power_score"].iloc[0]
    c_score = result.loc[result["team_id"] == "C", "power_score"].iloc[0]

    assert a_score == pytest.approx(100.0, abs=0.01)
    assert c_score == pytest.approx(0.0, abs=0.01)


def test_power_rankings_middle_team_matches_hand_calculation(three_team_stats):
    # B is exactly at the midpoint on win_pct/points/expected_win_pct (0.5
    # normalized each), and (95-80)/(115-80) = 0.42857 on recent form.
    # weighted: 0.5*0.35 + 0.5*0.25 + 0.5*0.25 + 0.42857*0.15 = 0.48929 -> 48.93
    result = compute_power_rankings(three_team_stats)
    b_score = result.loc[result["team_id"] == "B", "power_score"].iloc[0]

    assert b_score == pytest.approx(48.93, abs=0.01)


def test_power_rankings_sorted_highest_first(three_team_stats):
    result = compute_power_rankings(three_team_stats)
    assert list(result["team_id"]) == ["A", "B", "C"]


def test_power_rankings_handles_tied_metric_without_crashing():
    tied_stats = pd.DataFrame(
        [
            {"team_id": "X", "win_pct": 0.5, "points_per_game": 120, "expected_win_pct": 0.5, "recent_points_per_game": 100},
            {"team_id": "Y", "win_pct": 0.5, "points_per_game": 80, "expected_win_pct": 0.5, "recent_points_per_game": 100},
        ]
    )

    result = compute_power_rankings(tied_stats)

    # win_pct, expected_win_pct, recent_points_per_game are tied for both
    # teams (range=0) -> neutral 0.5 contribution each; points_per_game is
    # the only differentiator, so X should still rank above Y.
    x_score = result.loc[result["team_id"] == "X", "power_score"].iloc[0]
    y_score = result.loc[result["team_id"] == "Y", "power_score"].iloc[0]
    assert x_score > y_score
