import pandas as pd
import pytest

from app.analytics.roster import summarize_roster_efficiency


def test_summarize_roster_efficiency_averages_across_weeks():
    df = pd.DataFrame(
        [
            {"team_id": 1, "week": 1, "actual_points": 100, "optimal_points": 100, "efficiency": 1.0},
            {"team_id": 1, "week": 2, "actual_points": 80, "optimal_points": 100, "efficiency": 0.8},
            {"team_id": 2, "week": 1, "actual_points": 60, "optimal_points": 100, "efficiency": 0.6},
            {"team_id": 2, "week": 2, "actual_points": 70, "optimal_points": 100, "efficiency": 0.7},
        ]
    )

    result = summarize_roster_efficiency(df)

    team1 = result[result["team_id"] == 1].iloc[0]
    team2 = result[result["team_id"] == 2].iloc[0]
    assert team1["avg_efficiency"] == pytest.approx(0.9)
    assert team2["avg_efficiency"] == pytest.approx(0.65)
    # Sorted descending -> team 1 (higher average) comes first.
    assert result.iloc[0]["team_id"] == 1


def test_summarize_roster_efficiency_puts_missing_values_last():
    df = pd.DataFrame(
        [
            {"team_id": 1, "week": 1, "actual_points": 100, "optimal_points": 100, "efficiency": 1.0},
            {"team_id": 2, "week": 1, "actual_points": 0, "optimal_points": 0, "efficiency": None},
        ]
    )

    result = summarize_roster_efficiency(df)

    assert result.iloc[0]["team_id"] == 1
    assert pd.isna(result.iloc[1]["avg_efficiency"])
