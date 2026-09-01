from app.projections.blending import prior_season_weight

RECENT_GAMES_WINDOW = 3
RECENT_WEIGHT = 0.6


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def project_expected_volume(
    current_season_games: list[float],
    prior_season_games: list[float] | None,
    team_changed: bool = False,
) -> float | None:
    games_played = len(current_season_games)
    season_avg = _average(current_season_games)
    recent_avg = _average(current_season_games[-RECENT_GAMES_WINDOW:])

    if season_avg is not None and recent_avg is not None:
        current_estimate = RECENT_WEIGHT * recent_avg + (1 - RECENT_WEIGHT) * season_avg
    else:
        current_estimate = recent_avg if recent_avg is not None else season_avg

    # A team change makes the prior team's volume an unreliable guide to this one.
    effective_prior = None if team_changed or not prior_season_games else _average(prior_season_games)

    if current_estimate is None:
        return effective_prior
    if effective_prior is None:
        return current_estimate

    weight = prior_season_weight(games_played)
    return weight * effective_prior + (1 - weight) * current_estimate
