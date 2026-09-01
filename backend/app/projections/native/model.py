import pandas as pd

from app.projections.blending import prior_season_weight
from app.projections.native.categories import (
    POSITION_CATEGORIES,
    RateCategory,
    add_rate_columns,
    extract_player_rate_series,
)
from app.projections.native.efficiency import estimate_player_efficiency
from app.projections.native.priors import compute_position_priors
from app.projections.native.volume import project_expected_volume


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
    blend_weight: float,
) -> float:
    current_rates = extract_player_rate_series(current_season_games, category, rate_name)
    current_shrunk = estimate_player_efficiency(current_rates, position_rate_avg)

    if not prior_season_games:
        return current_shrunk

    # Team change discounts (doesn't erase) how much we trust the PRIOR team's rate -- softer
    # than volume's hard zero-out, per the spec's explicit distinction between the two.
    prior_rates = extract_player_rate_series(prior_season_games, category, rate_name)
    prior_shrunk = estimate_player_efficiency(prior_rates, position_rate_avg, team_changed=team_changed)

    return blend_weight * prior_shrunk + (1 - blend_weight) * current_shrunk


def project_player_points(
    position: str,
    current_season_games: list[dict],
    prior_season_games: list[dict] | None,
    position_priors: dict[str, dict[str, float | None]],
    team_changed: bool = False,
    use_player_efficiency: bool = True,
) -> float | None:
    categories = POSITION_CATEGORIES.get(position)
    if not categories:
        return None

    # Games observed THIS season drives how much current-season efficiency data replaces the
    # prior-season blend -- identical "actual games observed, not calendar week" rule as volume.
    blend_weight = prior_season_weight(len(current_season_games))

    total_points = 0.0
    for category in categories:
        current_opportunities = [g.get(category.opportunity_column) or 0 for g in current_season_games]
        prior_opportunities = (
            [g.get(category.opportunity_column) or 0 for g in prior_season_games] if prior_season_games else None
        )
        expected_opportunities = project_expected_volume(current_opportunities, prior_opportunities, team_changed)

        category_priors = position_priors.get(category.name, {})
        if expected_opportunities is None:
            expected_opportunities = category_priors.get("opportunity")
        if expected_opportunities is None:
            continue  # No real signal and no position prior for this category -- contributes zero, not fabricated.

        for rate_name, (_raw_column, points_per_unit) in category.rate_specs.items():
            position_rate_avg = category_priors.get(rate_name)
            if position_rate_avg is None:
                continue  # Can't shrink without a position average -- skip this rate component.

            if use_player_efficiency:
                shrunk_rate = _blended_rate(
                    current_season_games, prior_season_games, category, rate_name,
                    position_rate_avg, team_changed, blend_weight,
                )
            else:
                shrunk_rate = position_rate_avg

            total_points += expected_opportunities * shrunk_rate * points_per_unit

    return total_points
