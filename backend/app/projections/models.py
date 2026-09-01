from dataclasses import dataclass


@dataclass
class PlayerProjection:
    platform_player_id: str
    name: str
    position: str
    projected_points: float
    sources: list[str]
    floor: float | None = None
    ceiling: float | None = None
    confidence: float | None = None
    range_source: str | None = None
    sample_size: int = 0


@dataclass
class PlayerMetrics:
    platform_player_id: str
    snap_share: float | None = None
    targets: int | None = None
    target_share: float | None = None
    carries: int | None = None
    red_zone_opportunities: int | None = None
    usage_trend: str | None = None
    injury_status: str | None = None
    opponent: str | None = None
    matchup_rating: float | None = None
    experience_status: str | None = None
    games_played: int = 0
    season_target_share: float | None = None
    recent_target_share: float | None = None
    availability: str | None = None
