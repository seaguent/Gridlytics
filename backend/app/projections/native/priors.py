import pandas as pd


def compute_position_priors(
    weekly_stats: pd.DataFrame,
    stat_column: str,
    season: int,
    before_week: int | None,
) -> dict[str, float]:
    if weekly_stats.empty:
        return {}

    regular_season = weekly_stats[weekly_stats["season_type"] == "REG"]

    if before_week is None:
        # No cutoff within `season` -- the full season is eligible (e.g. a fully-elapsed prior season).
        eligible_mask = regular_season["season"] <= season
    else:
        eligible_mask = regular_season["season"] < season
        eligible_mask = eligible_mask | (
            (regular_season["season"] == season) & (regular_season["week"] < before_week)
        )
    eligible = regular_season[eligible_mask]

    means = eligible.groupby("position")[stat_column].mean()
    return means.dropna().to_dict()
