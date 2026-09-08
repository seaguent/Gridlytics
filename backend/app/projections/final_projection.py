from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League
from app.projections.espn import ESPNProjectionProvider
from app.projections.sleeper import SleeperProjectionProvider

# Weight on gridlytics_base; (1 - this) on platform_projection. A named constant so it can be swept later.
GRIDLYTICS_BLEND_WEIGHT = 0.5


def compute_final_projection(
    gridlytics_base: float | None,
    platform_projection: float | None,
    availability_status: str | None,
    weight: float = GRIDLYTICS_BLEND_WEIGHT,
) -> float | None:
    if availability_status == "unavailable":
        return 0.0

    if gridlytics_base is None:
        return platform_projection
    if platform_projection is None:
        return gridlytics_base
    if platform_projection == 0.0:
        # A platform-reported 0 with no confirmed-unavailable status is unreliable, not a real zero.
        return gridlytics_base

    return weight * gridlytics_base + (1 - weight) * platform_projection


async def fetch_platform_only_projections(session: AsyncSession, league: League) -> dict[str, float]:
    """The platform's own projection, not the multi-source ensemble -- the blend needs this number specifically."""
    provider = ESPNProjectionProvider() if league.platform == "espn" else SleeperProjectionProvider()
    projections = await provider.get_projections(session, league)
    return {p.platform_player_id: p.projected_points for p in projections}
