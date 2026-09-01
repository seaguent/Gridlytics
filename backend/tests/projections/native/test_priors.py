import pandas as pd
import pytest

from app.projections.native.priors import compute_position_priors


def _row(position: str, season: int, week: int, value: float, season_type: str = "REG") -> dict:
    return {"position": position, "season": season, "week": week, "stat": value, "season_type": season_type}


def test_empty_input_returns_empty_dict():
    assert compute_position_priors(pd.DataFrame(), "stat", season=2025, before_week=1) == {}


def test_pools_only_seasons_strictly_before_the_given_season():
    rows = [_row("RB", 2024, 1, 10.0), _row("RB", 2024, 2, 20.0), _row("RB", 2025, 1, 999.0)]
    result = compute_position_priors(pd.DataFrame(rows), "stat", season=2025, before_week=1)
    # before_week=1 excludes all of 2025 (no week < 1 exists) -- only the two 2024 rows count.
    assert result["RB"] == pytest.approx(15.0)


def test_pools_current_season_weeks_before_cutoff():
    rows = [
        _row("RB", 2024, 1, 10.0),
        _row("RB", 2025, 1, 20.0),
        _row("RB", 2025, 2, 30.0),
        _row("RB", 2025, 3, 999.0),
    ]
    result = compute_position_priors(pd.DataFrame(rows), "stat", season=2025, before_week=3)
    assert result["RB"] == pytest.approx(20.0)  # (10 + 20 + 30) / 3


def test_before_week_none_includes_the_full_given_season():
    rows = [_row("RB", 2025, 1, 10.0), _row("RB", 2025, 2, 20.0)]
    result = compute_position_priors(pd.DataFrame(rows), "stat", season=2025, before_week=None)
    assert result["RB"] == pytest.approx(15.0)


def test_excludes_non_regular_season_games():
    rows = [_row("RB", 2024, 1, 10.0), _row("RB", 2024, 19, 999.0, season_type="POST")]
    result = compute_position_priors(pd.DataFrame(rows), "stat", season=2025, before_week=None)
    assert result["RB"] == pytest.approx(10.0)


def test_leakage_future_weeks_never_affect_an_earlier_cutoff():
    rows = [_row("RB", 2024, 1, 10.0), _row("RB", 2025, 1, 20.0), _row("RB", 2025, 2, 30.0)]
    df = pd.DataFrame(rows)
    before = compute_position_priors(df, "stat", season=2025, before_week=2)

    # Mutate a week at/after the cutoff -- must not change the already-computed earlier result.
    df_mutated = df.copy()
    df_mutated.loc[df_mutated["week"] == 2, "stat"] = 99999.0
    after = compute_position_priors(df_mutated, "stat", season=2025, before_week=2)

    assert before == after
