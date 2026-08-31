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


@dataclass
class PlayerMetrics:
    """Forward-looking contract for usage/availability data.

    Nothing populates this yet -- no verified data source exists for these
    fields on either platform. Defined now so the shape is settled before
    any provider starts filling it in.
    """

    platform_player_id: str
    snap_share: float | None = None
    targets: int | None = None
    target_share: float | None = None
    carries: int | None = None
    red_zone_opportunities: int | None = None
    usage_trend: str | None = None
    injury_status: str | None = None
