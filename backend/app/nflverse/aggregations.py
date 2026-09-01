import pandas as pd

RED_ZONE_YARDLINE = 20


def compute_red_zone_opportunities(pbp: pd.DataFrame) -> pd.DataFrame:
    columns = ["gsis_id", "week", "red_zone_opportunities"]
    if pbp.empty:
        return pd.DataFrame(columns=columns)

    red_zone = pbp[(pbp["season_type"] == "REG") & (pbp["yardline_100"] <= RED_ZONE_YARDLINE)]

    targets = red_zone.loc[red_zone["pass_attempt"] == 1, ["week", "receiver_player_id"]].dropna()
    targets = targets.rename(columns={"receiver_player_id": "gsis_id"})

    carries = red_zone.loc[red_zone["rush_attempt"] == 1, ["week", "rusher_player_id"]].dropna()
    carries = carries.rename(columns={"rusher_player_id": "gsis_id"})

    combined = pd.concat([targets, carries])
    if combined.empty:
        return pd.DataFrame(columns=columns)

    return (
        combined.groupby(["gsis_id", "week"])
        .size()
        .reset_index(name="red_zone_opportunities")
    )


def compute_position_defense_strength(weekly_stats: pd.DataFrame) -> pd.DataFrame:
    columns = ["opponent_team", "position", "points_allowed_avg"]
    if weekly_stats.empty:
        return pd.DataFrame(columns=columns)

    regular_season = weekly_stats[weekly_stats["season_type"] == "REG"]
    grouped = (
        regular_season.groupby(["opponent_team", "position"])["fantasy_points_ppr"]
        .mean()
        .reset_index(name="points_allowed_avg")
    )
    return grouped
