from app.projections.blending import prior_season_weight

RECENT_GAMES_WINDOW = 3
RECENT_WEIGHT = 0.6
ROLE_CHANGE_DISCOUNT = 0.5


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def estimate_player_share(
    current_season_shares: list[float],
    prior_season_shares: list[float] | None,
    role_rank_prior_share: float | None,
    team_changed: bool,
    role_changed_recently: bool,
) -> float | None:
    games_played = len(current_season_shares)
    season_avg = _average(current_season_shares)
    recent_avg = _average(current_season_shares[-RECENT_GAMES_WINDOW:])

    if season_avg is not None and recent_avg is not None:
        current_estimate = RECENT_WEIGHT * recent_avg + (1 - RECENT_WEIGHT) * season_avg
    else:
        current_estimate = recent_avg if recent_avg is not None else season_avg

    effective_prior = None
    if not team_changed and prior_season_shares:
        effective_prior = _average(prior_season_shares)
        if role_changed_recently:
            effective_prior *= ROLE_CHANGE_DISCOUNT

    if current_estimate is None:
        return effective_prior if effective_prior is not None else role_rank_prior_share
    if effective_prior is None:
        return current_estimate

    weight = prior_season_weight(games_played)
    return weight * effective_prior + (1 - weight) * current_estimate
