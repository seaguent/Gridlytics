FULL_CONFIDENCE_GAMES = 8
OUTLIER_CAP_MULTIPLE = 3.0
TEAM_CHANGE_DISCOUNT = 0.5


def _shrinkage_weight(games_played: int) -> float:
    return max(0.0, min(1.0, games_played / FULL_CONFIDENCE_GAMES))


def _opportunity_shrinkage_weight(observed_opportunities: float, full_confidence_opportunities: float) -> float:
    if full_confidence_opportunities <= 0:
        return 1.0
    return max(0.0, min(1.0, observed_opportunities / full_confidence_opportunities))


def _capped_average(per_game_rates: list[float], position_average: float) -> float | None:
    if not per_game_rates:
        return None
    if position_average <= 0:
        return sum(per_game_rates) / len(per_game_rates)
    cap = position_average * OUTLIER_CAP_MULTIPLE
    capped = [min(rate, cap) for rate in per_game_rates]
    return sum(capped) / len(capped)


def estimate_player_efficiency(
    per_game_rates: list[float],
    position_average: float,
    team_changed: bool = False,
    observed_opportunities: float | None = None,
    full_confidence_opportunities: float | None = None,
) -> float:
    player_rate = _capped_average(per_game_rates, position_average)

    if player_rate is None:
        return position_average

    # Opt-in only: omitting full_confidence_opportunities reproduces the games-based path
    # exactly, so every existing caller (production sync included) is untouched by this branch.
    if full_confidence_opportunities is not None:
        weight = _opportunity_shrinkage_weight(observed_opportunities or 0.0, full_confidence_opportunities)
    else:
        weight = _shrinkage_weight(len(per_game_rates))

    if team_changed:
        # Softer than the volume-side team-change handling -- a team change discounts how much
        # we trust a player's own rate, but doesn't erase their real skill signal outright.
        weight *= TEAM_CHANGE_DISCOUNT

    return weight * player_rate + (1 - weight) * position_average
