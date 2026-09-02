from dataclasses import dataclass

TALENT_STATS = [
    "yards_per_target", "catch_rate", "yards_per_carry",
    "yards_per_attempt", "receiving_td_rate", "rushing_td_rate",
    "passing_td_rate", "passing_int_rate",
]
WORKLOAD_STATS = [
    "targets_per_game", "target_share", "carries_per_game", "carry_share", "fantasy_points_per_game",
]


@dataclass(frozen=True)
class CareerSeason:
    season: int
    season_offset: int  # 0 = most recent real prior season
    games: int
    team: str | None
    targets: int | None
    receptions: int | None
    receiving_yards: int | None
    receiving_tds: int | None
    carries: int | None
    rushing_yards: int | None
    rushing_tds: int | None
    attempts: int | None
    passing_yards: int | None
    passing_tds: int | None
    fantasy_points_ppr: float | None
    target_share: float | None
    carry_share: float | None
    yards_per_target: float | None
    yards_per_carry: float | None
    catch_rate: float | None
    receiving_td_rate: float | None
    rushing_td_rate: float | None
    # Trailing field with a default so every existing positional/keyword CareerSeason(...)
    # call site (tests, scripts) built before this extension keeps working unchanged.
    passing_interceptions: int | None = None

    @property
    def yards_per_attempt(self) -> float | None:
        if not self.attempts:
            return None
        return self.passing_yards / self.attempts if self.passing_yards is not None else None

    @property
    def passing_td_rate(self) -> float | None:
        if not self.attempts:
            return None
        return self.passing_tds / self.attempts if self.passing_tds is not None else None

    @property
    def passing_int_rate(self) -> float | None:
        if not self.attempts:
            return None
        return self.passing_interceptions / self.attempts if self.passing_interceptions is not None else None

    @property
    def targets_per_game(self) -> float | None:
        if not self.games or self.targets is None:
            return None
        return self.targets / self.games

    @property
    def carries_per_game(self) -> float | None:
        if not self.games or self.carries is None:
            return None
        return self.carries / self.games

    @property
    def fantasy_points_per_game(self) -> float | None:
        if not self.games or self.fantasy_points_ppr is None:
            return None
        return self.fantasy_points_ppr / self.games


FULL_CONFIDENCE_SEASON_GAMES = 8  # a season below this many real games contributes proportionally less

# Chosen via walk-forward grid search over lookback/decay candidates (see
# scripts/run_career_prior_validation.py) -- a 3-season lookback with this decay beat both a
# single-season baseline and slower-decaying alternatives on held-out MAE.
RECENCY_DECAY = 0.40


def career_weight(
    season_offset: int, games_played_that_season: int, recency_decay: float = RECENCY_DECAY
) -> float:
    sample_confidence = max(0.0, min(1.0, games_played_that_season / FULL_CONFIDENCE_SEASON_GAMES))
    recency_factor = recency_decay ** season_offset
    return sample_confidence * recency_factor


def _weighted_average(
    seasons: list["CareerSeason"], stat_name: str, weight_fn=career_weight
) -> float | None:
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


def _average_talent(seasons: list["CareerSeason"]) -> dict[str, float | None]:
    return {stat: _weighted_average(seasons, stat) for stat in TALENT_STATS}


def _average_workload(seasons: list["CareerSeason"]) -> dict[str, float | None]:
    return {stat: _weighted_average(seasons, stat) for stat in WORKLOAD_STATS}


ROLE_CHANGE_WORKLOAD_DISCOUNT = 0.5  # mirrors share.py's existing ROLE_CHANGE_DISCOUNT


def classify_talent_tier(
    value: float | None, percentile_cutoffs: tuple[float, float, float, float] | None
) -> str:
    if value is None or percentile_cutoffs is None:
        return "unknown"
    p20, p40, p60, p80 = percentile_cutoffs
    if value >= p80:
        return "elite"
    if value >= p60:
        return "above_average"
    if value >= p40:
        return "average"
    return "below_average"


@dataclass
class CareerPrior:
    talent: dict[str, float | None]
    workload: dict[str, float | None]
    seasons_used: int
    talent_tier: str


def compute_career_prior(
    seasons: list["CareerSeason"],
    team_changed: bool = False,
    role_changed_recently: bool = False,
    workload_confidence_multiplier: float = 1.0,
    key_stat_name: str = "yards_per_target",
    key_stat_percentile_cutoffs: tuple[float, float, float, float] | None = None,
) -> "CareerPrior":
    talent = _average_talent(seasons)

    if team_changed:
        # Hard zero, mirrors volume.py's existing team-change handling -- a workload built on a
        # different team's offense doesn't transfer. Talent is untouched (see above).
        workload = {stat: None for stat in WORKLOAD_STATS}
    else:
        workload = _average_workload(seasons)
        discount = workload_confidence_multiplier
        if role_changed_recently:
            discount *= ROLE_CHANGE_WORKLOAD_DISCOUNT
        if discount != 1.0:
            workload = {
                stat: (value * discount if value is not None else None)
                for stat, value in workload.items()
            }

    talent_tier = classify_talent_tier(talent.get(key_stat_name), key_stat_percentile_cutoffs)

    return CareerPrior(talent=talent, workload=workload, seasons_used=len(seasons), talent_tier=talent_tier)
