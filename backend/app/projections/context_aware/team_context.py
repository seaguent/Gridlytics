from dataclasses import dataclass

import pandas as pd

from app.projections.blending import prior_season_weight
from app.projections.context_aware.team_prior import TeamPrior


@dataclass
class TeamTendencies:
    pass_attempts_per_game: float | None
    rush_attempts_per_game: float | None

    @property
    def plays_per_game(self) -> float | None:
        if self.pass_attempts_per_game is None or self.rush_attempts_per_game is None:
            return None
        return self.pass_attempts_per_game + self.rush_attempts_per_game

    @property
    def pass_rate(self) -> float | None:
        plays = self.plays_per_game
        if plays is None or plays == 0:
            return None
        return self.pass_attempts_per_game / plays

    @property
    def rush_rate(self) -> float | None:
        plays = self.plays_per_game
        if plays is None or plays == 0:
            return None
        return self.rush_attempts_per_game / plays


def _blend(prior: float | None, current: float | None, weight: float) -> float | None:
    if current is None:
        return prior
    if prior is None:
        return current
    return weight * prior + (1 - weight) * current


def compute_team_tendencies(
    weekly_stats: pd.DataFrame, season: int, before_week: int | None
) -> dict[str, TeamTendencies]:
    if weekly_stats.empty:
        return {}

    reg = weekly_stats[weekly_stats["season_type"] == "REG"]

    prior_reg = reg[reg["season"] == season - 1]
    prior_by_team_week = prior_reg.groupby(["team", "week"]).agg(
        pass_attempts=("attempts", "sum"), rush_attempts=("carries", "sum")
    )
    prior_avg = prior_by_team_week.groupby("team").mean()

    if before_week is None:
        current_reg = reg[reg["season"] == season]
    else:
        current_reg = reg[(reg["season"] == season) & (reg["week"] < before_week)]
    current_by_team_week = current_reg.groupby(["team", "week"]).agg(
        pass_attempts=("attempts", "sum"), rush_attempts=("carries", "sum")
    )
    current_avg = current_by_team_week.groupby("team").mean()
    games_played_by_team = current_by_team_week.reset_index().groupby("team")["week"].nunique()

    result: dict[str, TeamTendencies] = {}
    for team in set(prior_avg.index) | set(current_avg.index):
        games_played = int(games_played_by_team.get(team, 0))
        weight = prior_season_weight(games_played)

        prior_pass = float(prior_avg.loc[team, "pass_attempts"]) if team in prior_avg.index else None
        prior_rush = float(prior_avg.loc[team, "rush_attempts"]) if team in prior_avg.index else None
        current_pass = float(current_avg.loc[team, "pass_attempts"]) if team in current_avg.index else None
        current_rush = float(current_avg.loc[team, "rush_attempts"]) if team in current_avg.index else None

        result[team] = TeamTendencies(
            pass_attempts_per_game=_blend(prior_pass, current_pass, weight),
            rush_attempts_per_game=_blend(prior_rush, current_rush, weight),
        )
    return result


def compute_team_tendencies_v2(
    weekly_stats: pd.DataFrame,
    multi_year_prior_by_team: dict[str, TeamPrior],
    season: int,
    before_week: int | None,
) -> dict[str, TeamTendencies]:
    """Same blend-by-current-season-games-observed mechanism as compute_team_tendencies, but the
    "prior" side is the multi-year team prior (team_prior.py's compute_team_prior -- recency-
    weighted multi-season history) instead of a single most-recent season. compute_team_tendencies
    itself is left unmodified for callers that still want the single-season baseline."""
    result: dict[str, TeamTendencies] = {}

    if not weekly_stats.empty:
        reg = weekly_stats[weekly_stats["season_type"] == "REG"]
        if before_week is None:
            current_reg = reg[reg["season"] == season]
        else:
            current_reg = reg[(reg["season"] == season) & (reg["week"] < before_week)]
        current_by_team_week = current_reg.groupby(["team", "week"]).agg(
            pass_attempts=("attempts", "sum"), rush_attempts=("carries", "sum")
        )
        current_avg = current_by_team_week.groupby("team").mean()
        games_played_by_team = current_by_team_week.reset_index().groupby("team")["week"].nunique()
    else:
        current_avg = None
        games_played_by_team = {}

    teams = set(multi_year_prior_by_team.keys())
    if current_avg is not None:
        teams |= set(current_avg.index)

    for team in teams:
        games_played = int(games_played_by_team.get(team, 0)) if hasattr(games_played_by_team, "get") else 0
        weight = prior_season_weight(games_played)

        prior = multi_year_prior_by_team.get(team)
        prior_pass = prior.pass_attempts_per_game if prior is not None else None
        prior_rush = prior.rush_attempts_per_game if prior is not None else None
        current_pass = (
            float(current_avg.loc[team, "pass_attempts"]) if current_avg is not None and team in current_avg.index else None
        )
        current_rush = (
            float(current_avg.loc[team, "rush_attempts"]) if current_avg is not None and team in current_avg.index else None
        )

        result[team] = TeamTendencies(
            pass_attempts_per_game=_blend(prior_pass, current_pass, weight),
            rush_attempts_per_game=_blend(prior_rush, current_rush, weight),
        )
    return result
