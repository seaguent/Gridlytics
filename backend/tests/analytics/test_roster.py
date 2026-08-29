import pandas as pd
import pytest

from app.analytics.roster import compute_bench_points


@pytest.fixture
def one_week_roster() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"team_id": 1, "week": 1, "points": 60.5, "is_starter": True},
            {"team_id": 1, "week": 1, "points": 45.0, "is_starter": True},
            {"team_id": 1, "week": 1, "points": 20.0, "is_starter": False},
            {"team_id": 2, "week": 1, "points": 98.2, "is_starter": True},
            {"team_id": 2, "week": 1, "points": 15.0, "is_starter": False},
        ]
    )


def test_bench_points_sums_only_non_starters(one_week_roster):
    result = compute_bench_points(one_week_roster)

    team_1_row = result[(result["team_id"] == 1) & (result["week"] == 1)].iloc[0]
    team_2_row = result[(result["team_id"] == 2) & (result["week"] == 1)].iloc[0]

    assert team_1_row["bench_points"] == pytest.approx(20.0)
    assert team_2_row["bench_points"] == pytest.approx(15.0)


def test_bench_points_excludes_teams_with_no_bench(one_week_roster):
    all_starters = pd.DataFrame(
        [{"team_id": 3, "week": 1, "points": 50.0, "is_starter": True}]
    )
    result = compute_bench_points(all_starters)

    assert len(result[result["team_id"] == 3]) == 0
