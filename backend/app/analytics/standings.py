import pandas as pd


def compute_expected_wins(scores: pd.DataFrame) -> dict:
    ranks = scores.groupby("week")["points"].rank(method="average")
    teams_per_week = scores.groupby("week")["team_id"].transform("count")
    expected_fraction = (ranks - 1) / (teams_per_week - 1)

    return scores.assign(expected_fraction=expected_fraction).groupby("team_id")[
        "expected_fraction"
    ].sum().to_dict()


def compute_schedule_strength(scores: pd.DataFrame) -> dict:
    team_averages = scores.groupby("team_id")["points"].mean()
    opponent_strength = scores["opponent_team_id"].map(team_averages)

    return scores.assign(opponent_strength=opponent_strength).groupby("team_id")[
        "opponent_strength"
    ].mean().to_dict()


def compute_recent_form(scores: pd.DataFrame, num_weeks: int = 3) -> dict:
    recent_weeks = sorted(scores["week"].unique())[-num_weeks:]
    recent = scores[scores["week"].isin(recent_weeks)]
    return recent.groupby("team_id")["points"].mean().to_dict()
