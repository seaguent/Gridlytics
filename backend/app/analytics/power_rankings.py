import pandas as pd

POWER_RANKING_WEIGHTS = {
    "win_pct": 0.35,
    "points_per_game": 0.25,
    "expected_win_pct": 0.25,
    "recent_points_per_game": 0.15,
}


def compute_power_rankings(team_stats: pd.DataFrame) -> pd.DataFrame:
    result = team_stats[["team_id"]].copy()
    normalized_total = pd.Series(0.0, index=team_stats.index)

    for metric, weight in POWER_RANKING_WEIGHTS.items():
        values = team_stats[metric]
        value_range = values.max() - values.min()
        if value_range == 0:
            normalized = pd.Series(0.5, index=team_stats.index)
        else:
            normalized = (values - values.min()) / value_range
        normalized_total += normalized * weight

    result["power_score"] = normalized_total * 100
    return result.sort_values("power_score", ascending=False).reset_index(drop=True)
