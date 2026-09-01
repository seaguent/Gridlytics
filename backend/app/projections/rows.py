from app.projections.models import PlayerMetrics

NO_USAGE_TRACKING_POSITIONS = {"DEF", "K"}


def metrics_to_dict(position: str, metrics: PlayerMetrics | None) -> dict:
    no_usage_data_default = "not_applicable" if position in NO_USAGE_TRACKING_POSITIONS else "rookie_or_limited_history"
    return {
        "target_share": metrics.target_share if metrics else None,
        "targets": metrics.targets if metrics else None,
        "carries": metrics.carries if metrics else None,
        "usage_trend": metrics.usage_trend if metrics else None,
        "snap_share": metrics.snap_share if metrics else None,
        "red_zone_opportunities": metrics.red_zone_opportunities if metrics else None,
        "injury_status": metrics.injury_status if metrics else None,
        "opponent": metrics.opponent if metrics else None,
        "matchup_rating": metrics.matchup_rating if metrics else None,
        "experience_status": metrics.experience_status if metrics else no_usage_data_default,
        "games_played": metrics.games_played if metrics else 0,
        "season_target_share": metrics.season_target_share if metrics else None,
        "recent_target_share": metrics.recent_target_share if metrics else None,
        "availability": metrics.availability if metrics else None,
    }
