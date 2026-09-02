from dataclasses import dataclass

import pandas as pd

from app.projections.blending import prior_season_weight
from app.projections.native.categories import (
    POSITION_CATEGORIES,
    SCORING_FIELD_BY_CATEGORY_RATE,
    RateCategory,
    add_rate_columns,
    extract_player_rate_series,
)
from app.projections.native.efficiency import estimate_player_efficiency
from app.projections.native.priors import compute_position_priors
from app.projections.native.volume import project_expected_volume
from app.projections.scoring_rules import STANDARD_PPR, ScoringRules


def compute_all_position_priors(
    weekly_stats: pd.DataFrame, season: int, before_week: int | None
) -> dict[str, dict[str, dict[str, float | None]]]:
    result: dict[str, dict[str, dict[str, float | None]]] = {}
    for position, categories in POSITION_CATEGORIES.items():
        result[position] = {}
        for category in categories:
            opportunity_priors = compute_position_priors(weekly_stats, category.opportunity_column, season, before_week)
            rate_frame = add_rate_columns(weekly_stats, category)

            category_priors: dict[str, float | None] = {"opportunity": opportunity_priors.get(position)}
            for rate_name in category.rate_specs:
                rate_priors = compute_position_priors(rate_frame, rate_name, season, before_week)
                category_priors[rate_name] = rate_priors.get(position)

            result[position][category.name] = category_priors
    return result


def _blended_rate(
    current_season_games: list[dict],
    prior_season_games: list[dict] | None,
    category: RateCategory,
    rate_name: str,
    position_rate_avg: float,
    team_changed: bool,
    prior_weight: float,
    full_confidence_opportunities: float | None = None,
) -> float:
    current_rates = extract_player_rate_series(current_season_games, category, rate_name)
    current_opportunities = sum(g.get(category.opportunity_column) or 0 for g in current_season_games)
    current_shrunk = estimate_player_efficiency(
        current_rates, position_rate_avg,
        observed_opportunities=current_opportunities, full_confidence_opportunities=full_confidence_opportunities,
    )

    if not prior_season_games:
        return current_shrunk

    # Team change discounts (doesn't erase) how much we trust the PRIOR team's rate -- softer
    # than volume's hard zero-out, per the spec's explicit distinction between the two.
    prior_rates = extract_player_rate_series(prior_season_games, category, rate_name)
    prior_opportunities = sum(g.get(category.opportunity_column) or 0 for g in prior_season_games)
    prior_shrunk = estimate_player_efficiency(
        prior_rates, position_rate_avg, team_changed=team_changed,
        observed_opportunities=prior_opportunities, full_confidence_opportunities=full_confidence_opportunities,
    )

    return prior_weight * prior_shrunk + (1 - prior_weight) * current_shrunk


@dataclass
class CategoryBreakdown:
    name: str
    expected_opportunities: float | None
    prior_season_weight: float
    points: float
    shrunk_rates: dict[str, float]


@dataclass
class NativeProjectionBreakdown:
    total_points: float
    categories: list[CategoryBreakdown]


def project_player_points_detailed(
    position: str,
    current_season_games: list[dict],
    prior_season_games: list[dict] | None,
    position_priors: dict[str, dict[str, float | None]],
    team_changed: bool = False,
    use_player_efficiency: bool = True,
    scoring_rules: ScoringRules = STANDARD_PPR,
    td_shrinkage_opportunities: dict[str, float] | None = None,
) -> NativeProjectionBreakdown | None:
    categories = POSITION_CATEGORIES.get(position)
    if not categories:
        return None

    # Local name deliberately NOT `prior_season_weight` -- that would shadow the imported
    # function of the same name from app.projections.blending.
    prior_weight = prior_season_weight(len(current_season_games))

    total_points = 0.0
    category_breakdowns: list[CategoryBreakdown] = []
    for category in categories:
        current_opportunities = [g.get(category.opportunity_column) or 0 for g in current_season_games]
        prior_opportunities = (
            [g.get(category.opportunity_column) or 0 for g in prior_season_games] if prior_season_games else None
        )
        expected_opportunities = project_expected_volume(current_opportunities, prior_opportunities, team_changed)

        category_priors = position_priors.get(category.name, {})
        if expected_opportunities is None:
            expected_opportunities = category_priors.get("opportunity")

        category_points = 0.0
        shrunk_rates: dict[str, float] = {}
        if expected_opportunities is not None:
            for rate_name in category.rate_specs:
                position_rate_avg = category_priors.get(rate_name)
                if position_rate_avg is None:
                    continue  # Can't shrink without a position average -- skip this rate component.

                # Real per-league scoring value, not the hardcoded standard-PPR default baked
                # into rate_specs -- that default is still what STANDARD_PPR itself resolves to.
                points_per_unit = getattr(scoring_rules, SCORING_FIELD_BY_CATEGORY_RATE[(category.name, rate_name)])

                # Opt-in only: td_shrinkage_opportunities is None by default, so every existing
                # caller (production sync, prior backtests) keeps the games-based shrinkage curve
                # for every rate, td_rate included -- untouched by this experiment unless supplied.
                full_confidence_opportunities = (
                    td_shrinkage_opportunities.get(category.name)
                    if td_shrinkage_opportunities is not None and rate_name == "td_rate"
                    else None
                )

                if use_player_efficiency:
                    shrunk_rate = _blended_rate(
                        current_season_games, prior_season_games, category, rate_name,
                        position_rate_avg, team_changed, prior_weight,
                        full_confidence_opportunities=full_confidence_opportunities,
                    )
                else:
                    shrunk_rate = position_rate_avg

                shrunk_rates[rate_name] = shrunk_rate
                category_points += expected_opportunities * shrunk_rate * points_per_unit

        total_points += category_points
        category_breakdowns.append(
            CategoryBreakdown(
                name=category.name,
                expected_opportunities=expected_opportunities,
                prior_season_weight=prior_weight,
                points=category_points,
                shrunk_rates=shrunk_rates,
            )
        )

    return NativeProjectionBreakdown(total_points=total_points, categories=category_breakdowns)


def project_player_points(
    position: str,
    current_season_games: list[dict],
    prior_season_games: list[dict] | None,
    position_priors: dict[str, dict[str, float | None]],
    team_changed: bool = False,
    use_player_efficiency: bool = True,
    scoring_rules: ScoringRules = STANDARD_PPR,
    td_shrinkage_opportunities: dict[str, float] | None = None,
) -> float | None:
    breakdown = project_player_points_detailed(
        position, current_season_games, prior_season_games, position_priors,
        team_changed, use_player_efficiency, scoring_rules, td_shrinkage_opportunities,
    )
    return breakdown.total_points if breakdown is not None else None
