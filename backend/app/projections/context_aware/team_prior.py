from dataclasses import dataclass

import pandas as pd

TEAM_STATS = ["pass_attempts_per_game", "rush_attempts_per_game"]

FULL_CONFIDENCE_GAMES = 8  # a season below this many real games contributes proportionally less

# Chosen via walk-forward backtest (scripts/run_team_prior_validation.py): a 4-season lookback
# at this decay beat the single-season baseline on predicting next-season team pass attempts.
RECENCY_DECAY = 0.55
LOOKBACK_SEASONS = 4


@dataclass(frozen=True)
class TeamSeason:
    team: str
    season: int
    season_offset: int  # 0 = most recent real prior season
    games: int
    pass_attempts_per_game: float | None
    rush_attempts_per_game: float | None


@dataclass
class TeamPrior:
    pass_attempts_per_game: float | None
    rush_attempts_per_game: float | None
    seasons_used: int


def team_weight(season_offset: int, games_played: int, recency_decay: float = RECENCY_DECAY) -> float:
    sample_confidence = max(0.0, min(1.0, games_played / FULL_CONFIDENCE_GAMES))
    recency_factor = recency_decay ** season_offset
    return sample_confidence * recency_factor


def _weighted_average(seasons: list[TeamSeason], stat_name: str, weight_fn=team_weight) -> float | None:
    weighted_sum = 0.0
    total_weight = 0.0
    for season in seasons:
        value = getattr(season, stat_name)
        if value is None:
            continue
        weight = weight_fn(season.season_offset, season.games)
        weighted_sum += weight * value
        total_weight += weight
    return weighted_sum / total_weight if total_weight > 0 else None


def compute_team_prior(seasons: list[TeamSeason]) -> TeamPrior:
    return TeamPrior(
        pass_attempts_per_game=_weighted_average(seasons, "pass_attempts_per_game"),
        rush_attempts_per_game=_weighted_average(seasons, "rush_attempts_per_game"),
        seasons_used=len(seasons),
    )


def real_team_seasons(weekly_by_year: dict[int, pd.DataFrame]) -> dict[tuple[str, int], TeamSeason]:
    """season_offset left at 0 -- callers reassign it relative to whichever target season they're predicting."""
    result: dict[tuple[str, int], TeamSeason] = {}
    for season, df in weekly_by_year.items():
        reg = df[df["season_type"] == "REG"]
        if reg.empty:
            continue
        by_team_week = reg.groupby(["team", "week"]).agg(pass_attempts=("attempts", "sum"), rush_attempts=("carries", "sum"))
        by_team = by_team_week.groupby("team").agg(
            pass_attempts_per_game=("pass_attempts", "mean"),
            rush_attempts_per_game=("rush_attempts", "mean"),
            games=("pass_attempts", "count"),
        )
        for team, row in by_team.iterrows():
            result[(team, season)] = TeamSeason(
                team=team, season=season, season_offset=0, games=int(row["games"]),
                pass_attempts_per_game=float(row["pass_attempts_per_game"]),
                rush_attempts_per_game=float(row["rush_attempts_per_game"]),
            )
    return result


def build_team_seasons_for_prediction(
    all_team_seasons: dict[tuple[str, int], TeamSeason], team: str, target_season: int, lookback: int,
) -> list[TeamSeason]:
    """Leak-safe: only real seasons strictly before target_season, most recent first."""
    available = sorted(
        (s for (t, s) in all_team_seasons if t == team and target_season - lookback <= s < target_season),
        reverse=True,
    )
    seasons = []
    for offset, season in enumerate(available):
        base = all_team_seasons[(team, season)]
        seasons.append(TeamSeason(
            team=team, season=season, season_offset=offset, games=base.games,
            pass_attempts_per_game=base.pass_attempts_per_game, rush_attempts_per_game=base.rush_attempts_per_game,
        ))
    return seasons


def compute_team_prior_by_team(
    weekly_by_year: dict[int, pd.DataFrame], target_season: int,
    lookback: int = LOOKBACK_SEASONS, decay: float = RECENCY_DECAY,
) -> dict[str, TeamPrior]:
    """The multi-year team prior for every team with real history."""
    all_team_seasons = real_team_seasons(weekly_by_year)
    teams = sorted({t for (t, s) in all_team_seasons})
    weight_fn = lambda offset, g, d=decay: team_weight(offset, g, recency_decay=d)

    result: dict[str, TeamPrior] = {}
    for team in teams:
        team_seasons = build_team_seasons_for_prediction(all_team_seasons, team, target_season, lookback)
        if not team_seasons:
            continue
        result[team] = TeamPrior(
            pass_attempts_per_game=_weighted_average(team_seasons, "pass_attempts_per_game", weight_fn),
            rush_attempts_per_game=_weighted_average(team_seasons, "rush_attempts_per_game", weight_fn),
            seasons_used=len(team_seasons),
        )
    return result
