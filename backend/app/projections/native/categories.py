from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class RateCategory:
    name: str
    opportunity_column: str
    rate_specs: dict[str, tuple[str, float]]  # rate_name -> (raw_stat_column, points_per_unit)


RECEIVING = RateCategory(
    name="receiving",
    opportunity_column="targets",
    rate_specs={
        "yards_per_target": ("receiving_yards", 0.1),
        "td_rate": ("receiving_tds", 6.0),
        "reception_rate": ("receptions", 1.0),
    },
)

RUSHING = RateCategory(
    name="rushing",
    opportunity_column="carries",
    rate_specs={
        "yards_per_carry": ("rushing_yards", 0.1),
        "td_rate": ("rushing_tds", 6.0),
    },
)

PASSING = RateCategory(
    name="passing",
    opportunity_column="attempts",
    rate_specs={
        "yards_per_attempt": ("passing_yards", 0.04),
        "td_rate": ("passing_tds", 4.0),
        "int_rate": ("passing_interceptions", -2.0),
    },
)

POSITION_CATEGORIES: dict[str, list[RateCategory]] = {
    "QB": [PASSING, RUSHING],
    "RB": [RUSHING, RECEIVING],
    "WR": [RECEIVING],
    "TE": [RECEIVING],
}

# Maps (category_name, rate_name) -> the ScoringRules field that should supply its real
# points-per-unit value, so a league's actual scoring settings can override the standard-PPR
# defaults baked into rate_specs above without changing RateCategory's own shape or any of the
# opportunity/efficiency estimation that consumes it.
SCORING_FIELD_BY_CATEGORY_RATE: dict[tuple[str, str], str] = {
    ("passing", "yards_per_attempt"): "pass_yard_points",
    ("passing", "td_rate"): "pass_td_points",
    ("passing", "int_rate"): "pass_int_points",
    ("rushing", "yards_per_carry"): "rush_yard_points",
    ("rushing", "td_rate"): "rush_td_points",
    ("receiving", "yards_per_target"): "rec_yard_points",
    ("receiving", "td_rate"): "rec_td_points",
    ("receiving", "reception_rate"): "reception_points",
}


def add_rate_columns(weekly_stats: pd.DataFrame, category: RateCategory) -> pd.DataFrame:
    has_opportunity = weekly_stats[category.opportunity_column] > 0
    scoped = weekly_stats[has_opportunity].copy()
    for rate_name, (raw_column, _points_per_unit) in category.rate_specs.items():
        scoped[rate_name] = scoped[raw_column] / scoped[category.opportunity_column]
    return scoped


def extract_player_rate_series(player_games: list[dict], category: RateCategory, rate_name: str) -> list[float]:
    raw_column, _points_per_unit = category.rate_specs[rate_name]
    values = []
    for game in player_games:
        opportunities = game.get(category.opportunity_column) or 0
        if opportunities > 0:
            values.append(game[raw_column] / opportunities)
    return values
