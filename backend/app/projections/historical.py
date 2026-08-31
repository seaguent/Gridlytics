import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League, Player, RosterSlot, Team
from app.projections.models import PlayerProjection
from app.projections.uncertainty import compute_floor_ceiling_confidence
from app.projections.weighting import compute_weighted_recent_form


async def load_player_history(session: AsyncSession, league_id: int) -> pd.DataFrame:
    result = await session.execute(
        select(RosterSlot.platform_player_id, RosterSlot.week, RosterSlot.points)
        .join(Team, RosterSlot.team_id == Team.id)
        .where(Team.league_id == league_id)
    )
    records = [
        {"platform_player_id": platform_player_id, "week": week, "points": points}
        for platform_player_id, week, points in result.all()
    ]
    return pd.DataFrame(records, columns=["platform_player_id", "week", "points"])


class HistoricalAverageProjectionProvider:
    def __init__(self, num_weeks: int = 5, decay: float = 0.75) -> None:
        self.num_weeks = num_weeks
        self.decay = decay

    async def get_projections(self, session: AsyncSession, league: League) -> list[PlayerProjection]:
        if league.platform != "sleeper":
            # RosterSlot.points isn't real per-player data on other platforms
            # yet -- e.g. the ESPN adapter hardcodes it to 0 as a placeholder
            # (per-player weekly points aren't wired up for ESPN yet). Averaging
            # against that would be actively wrong, not just less accurate.
            return []

        history = await load_player_history(session, league.id)
        if not len(history):
            return []

        averages = compute_weighted_recent_form(
            history,
            num_weeks=self.num_weeks,
            decay=self.decay,
            group_by="platform_player_id",
        )

        recent_weeks = sorted(history["week"].unique())[-self.num_weeks :]
        recent_history = history[history["week"].isin(recent_weeks)]

        result = await session.execute(select(Player).where(Player.platform == league.platform))
        players_by_id = {player.platform_player_id: player for player in result.scalars()}

        projections = []
        for platform_player_id, avg_points in averages.items():
            player = players_by_id.get(platform_player_id)
            player_scores = recent_history.loc[
                recent_history["platform_player_id"] == platform_player_id, "points"
            ]
            floor, ceiling, confidence = compute_floor_ceiling_confidence(player_scores)

            projections.append(
                PlayerProjection(
                    platform_player_id=platform_player_id,
                    name=player.name if player else platform_player_id,
                    position=player.position if player else "UNKNOWN",
                    projected_points=avg_points,
                    sources=["historical_weighted_average"],
                    floor=floor,
                    ceiling=ceiling,
                    confidence=confidence,
                )
            )
        return projections
