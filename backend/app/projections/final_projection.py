from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League
from app.projections.espn import ESPNProjectionProvider
from app.projections.sleeper import SleeperProjectionProvider

# Weight on gridlytics_base; (1 - this) on platform_projection. Kept as a named constant,
# not an inline literal, so it can be swept (100/0, 75/25, 50/50, 25/75, platform-only) on a
# common sample once real 2026 outcomes accumulate.
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
        # A real zero requires a confirmed-unavailable status (handled above). Reaching here
        # means the platform reports 0 for a player not flagged out/IR/bye -- treat that as a
        # missing/unreliable platform number rather than averaging toward a fabricated zero.
        return gridlytics_base

    return weight * gridlytics_base + (1 - weight) * platform_projection


async def fetch_platform_only_projections(session: AsyncSession, league: League) -> dict[str, float]:
    """The single real platform's own projection (ESPN's or Sleeper's, whichever this league
    is) -- deliberately not the multi-source ensemble, since the blend needs the platform's own
    number specifically, not one already averaged with our historical-average provider."""
    provider = ESPNProjectionProvider() if league.platform == "espn" else SleeperProjectionProvider()
    projections = await provider.get_projections(session, league)
    return {p.platform_player_id: p.projected_points for p in projections}
