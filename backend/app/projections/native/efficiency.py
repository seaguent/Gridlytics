FULL_CONFIDENCE_GAMES = 8
OUTLIER_CAP_MULTIPLE = 3.0
TEAM_CHANGE_DISCOUNT = 0.5


def _shrinkage_weight(games_played: int) -> float:
    return max(0.0, min(1.0, games_played / FULL_CONFIDENCE_GAMES))


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
) -> float:
    games_played = len(per_game_rates)
    player_rate = _capped_average(per_game_rates, position_average)

    if player_rate is None:
        return position_average

    weight = _shrinkage_weight(games_played)
    if team_changed:
        # Softer than the volume-side team-change handling -- a team change discounts how much
        # we trust a player's own rate, but doesn't erase their real skill signal outright.
        weight *= TEAM_CHANGE_DISCOUNT

    return weight * player_rate + (1 - weight) * position_average
