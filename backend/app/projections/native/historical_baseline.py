def project_historical_recency(
    current_season_points: list[float],
    num_weeks: int = 5,
    decay: float = 0.75,
    min_weeks: int = 2,
) -> float | None:
    if len(current_season_points) < min_weeks:
        return None

    recent = current_season_points[-num_weeks:]
    weeks_newest_first = list(reversed(recent))

    weighted_sum = 0.0
    weight_total = 0.0
    for rank, points in enumerate(weeks_newest_first):
        weight = decay**rank
        weighted_sum += points * weight
        weight_total += weight

    return weighted_sum / weight_total
