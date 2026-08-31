from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League, ProjectionRecord
from app.projections.models import PlayerProjection


class ESPNProjectionProvider:
    async def get_projections(self, session: AsyncSession, league: League) -> list[PlayerProjection]:
        if league.platform != "espn":
            return []

        result = await session.execute(
            select(ProjectionRecord).where(
                ProjectionRecord.league_id == league.id,
                ProjectionRecord.week == league.current_week,
                ProjectionRecord.source == "espn",
            )
        )

        return [
            PlayerProjection(
                platform_player_id=record.platform_player_id,
                name=record.name,
                position=record.position,
                projected_points=record.projected_points,
                sources=["espn"],
            )
            for record in result.scalars()
        ]
