import pandas as pd


def compute_weighted_recent_form(
    scores: pd.DataFrame, num_weeks: int = 5, decay: float = 0.75, group_by: str = "team_id"
) -> dict:
    recent_weeks = sorted(scores["week"].unique())[-num_weeks:]
    recent = scores[scores["week"].isin(recent_weeks)].copy()

    weeks_newest_first = sorted(recent_weeks, reverse=True)
    week_rank = {week: rank for rank, week in enumerate(weeks_newest_first)}
    recent["weight"] = recent["week"].map(week_rank).apply(lambda rank: decay**rank)
    recent["weighted_points"] = recent["points"] * recent["weight"]

    weighted_sums = recent.groupby(group_by)["weighted_points"].sum()
    weight_totals = recent.groupby(group_by)["weight"].sum()

    return (weighted_sums / weight_totals).to_dict()
