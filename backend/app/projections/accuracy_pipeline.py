from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League, ProjectionRecord, RosterSlot, Team
from app.projections.accuracy import ProjectionAccuracyReport, compute_projection_accuracy


async def load_projection_accuracy(session: AsyncSession, league: League) -> ProjectionAccuracyReport:
    result = await session.execute(
        select(
            ProjectionRecord.source,
            ProjectionRecord.platform_player_id,
            ProjectionRecord.week,
            ProjectionRecord.projected_points,
            RosterSlot.points,
        )
        .select_from(ProjectionRecord)
        .join(
            RosterSlot,
            (RosterSlot.platform_player_id == ProjectionRecord.platform_player_id)
            & (RosterSlot.week == ProjectionRecord.week),
        )
        .join(Team, RosterSlot.team_id == Team.id)
        .where(
            ProjectionRecord.league_id == league.id,
            Team.league_id == league.id,
            ProjectionRecord.week < league.current_week,
        )
    )
    records = [
        {
            "source": source,
            "platform_player_id": platform_player_id,
            "week": week,
            "projected_points": projected_points,
            "actual_points": actual_points,
        }
        for source, platform_player_id, week, projected_points, actual_points in result.all()
    ]
    return compute_projection_accuracy(records)
