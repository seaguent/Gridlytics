import pandas as pd

RED_ZONE_YARDLINE = 20
MIN_GAMES_FOR_PLAYER_RATIO = 4
MIN_POOLED_RATIOS = 10
LOW_PERCENTILE = 0.2
HIGH_PERCENTILE = 0.8


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


def compute_position_volatility_priors(weekly_stats: pd.DataFrame) -> dict[str, tuple[float, float, int]]:
    if weekly_stats.empty:
        return {}

    regular_season = weekly_stats[weekly_stats["season_type"] == "REG"]

    priors: dict[str, tuple[float, float, int]] = {}
    for position, group in regular_season.groupby("position"):
        ratios: list[float] = []
        for _, player_games in group.groupby("player_id"):
            scores = player_games["fantasy_points_ppr"].dropna()
            if len(scores) < MIN_GAMES_FOR_PLAYER_RATIO:
                continue
            mean = scores.mean()
            if mean == 0 or pd.isna(mean):
                continue
            # Normalize to each player's own average so the pool reflects relative spread, not magnitude.
            ratios.extend((scores / mean).tolist())

        if len(ratios) < MIN_POOLED_RATIOS:
            continue

        series = pd.Series(ratios)
        priors[position] = (
            float(series.quantile(LOW_PERCENTILE)),
            float(series.quantile(HIGH_PERCENTILE)),
            len(ratios),
        )

    return priors
