from app.projections.models import PlayerMetrics, PlayerProjection

CLOSE_CALL_THRESHOLD = 2.0
FAVORABLE_MATCHUP_THRESHOLD = 65
TOUGH_MATCHUP_THRESHOLD = 35
LIMITED_SAMPLE_GAMES = 3
RISKY_AVAILABILITY = {"doubtful", "questionable", "unavailable"}


def _compare_numeric(favors_a: list[str], favors_b: list[str], value_a, value_b, label) -> None:
    if value_a is None or value_b is None or value_a == value_b:
        return
    winner = favors_a if value_a > value_b else favors_b
    winner.append(label(value_a, value_b))


def _labels_for(metrics: PlayerMetrics | None) -> list[str]:
    if metrics is None:
        return []
    labels = []
    if metrics.usage_trend == "rising":
        labels.append("Usage rising")
    elif metrics.usage_trend == "falling":
        labels.append("Role declining")
    if metrics.matchup_rating is not None:
        if metrics.matchup_rating >= FAVORABLE_MATCHUP_THRESHOLD:
            labels.append("Favorable matchup")
        elif metrics.matchup_rating <= TOUGH_MATCHUP_THRESHOLD:
            labels.append("Tough matchup")
    if metrics.experience_status == "rookie_or_limited_history" or 0 < metrics.games_played < LIMITED_SAMPLE_GAMES:
        labels.append("Limited history")
    return labels


def _risks_for(metrics: PlayerMetrics | None) -> list[str]:
    if metrics is None or metrics.availability not in RISKY_AVAILABILITY:
        return []
    return [metrics.availability.capitalize()]


def compare_players(
    proj_a: PlayerProjection,
    metrics_a: PlayerMetrics | None,
    proj_b: PlayerProjection,
    metrics_b: PlayerMetrics | None,
) -> dict:
    gap = proj_a.projected_points - proj_b.projected_points
    favors_a: list[str] = []
    favors_b: list[str] = []

    if abs(gap) >= 0.05:
        (favors_a if gap > 0 else favors_b).append(f"+{abs(gap):.1f} projected points")

    _compare_numeric(
        favors_a, favors_b,
        metrics_a.recent_target_share if metrics_a else None,
        metrics_b.recent_target_share if metrics_b else None,
        lambda a, b: f"{a * 100:.0f}% recent target share vs {b * 100:.0f}%",
    )
    _compare_numeric(
        favors_a, favors_b,
        metrics_a.snap_share if metrics_a else None,
        metrics_b.snap_share if metrics_b else None,
        lambda a, b: f"{a * 100:.0f}% snap share vs {b * 100:.0f}%",
    )
    _compare_numeric(
        favors_a, favors_b,
        metrics_a.red_zone_opportunities if metrics_a else None,
        metrics_b.red_zone_opportunities if metrics_b else None,
        lambda a, b: f"{a} red zone opportunities vs {b}",
    )

    labels_a = _labels_for(metrics_a)
    labels_b = _labels_for(metrics_b)
    if proj_a.floor is not None and proj_b.floor is not None and proj_a.floor != proj_b.floor:
        (labels_a if proj_a.floor > proj_b.floor else labels_b).append("Safer floor")
    if proj_a.ceiling is not None and proj_b.ceiling is not None and proj_a.ceiling != proj_b.ceiling:
        (labels_a if proj_a.ceiling > proj_b.ceiling else labels_b).append("Higher upside")

    return {
        "opponent_player_id": proj_b.platform_player_id,
        "opponent_name": proj_b.name,
        "projection_gap": gap,
        "is_close_call": abs(gap) <= CLOSE_CALL_THRESHOLD,
        "favors_this_player": favors_a,
        "favors_opponent": favors_b,
        "this_player_risks": _risks_for(metrics_a),
        "opponent_risks": _risks_for(metrics_b),
        "this_player_labels": labels_a,
        "opponent_labels": labels_b,
    }
