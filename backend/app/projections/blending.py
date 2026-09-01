FULL_TRANSITION_GAMES = 8


def prior_season_weight(games_played_this_season: int) -> float:
    # Sample-size based, not calendar-week based -- byes/injuries mean weeks elapsed != games played.
    return max(0.0, min(1.0, 1 - games_played_this_season / FULL_TRANSITION_GAMES))
