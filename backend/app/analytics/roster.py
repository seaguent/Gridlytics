import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.lineup import find_optimal_lineup
from app.models import League, Player, RosterSlot, Team, WeeklyScore

NON_STARTING_SLOTS = {"BN", "IR", "TAXI"}


def compute_bench_points(roster: pd.DataFrame) -> pd.DataFrame:
    bench_only = roster[~roster["is_starter"]]
    return (
        bench_only.groupby(["team_id", "week"])["points"]
        .sum()
        .reset_index(name="bench_points")
    )


async def compute_roster_efficiency(session: AsyncSession, league: League) -> pd.DataFrame:
    starting_slots = [slot for slot in league.roster_positions if slot not in NON_STARTING_SLOTS]

    result = await session.execute(
        select(RosterSlot, Player.position)
        .join(Team, RosterSlot.team_id == Team.id)
        .join(
            Player,
            (Player.platform == league.platform)
            & (Player.platform_player_id == RosterSlot.platform_player_id),
            isouter=True,
        )
        .where(Team.league_id == league.id)
    )

    by_team_week: dict[tuple[int, int], list[dict]] = {}
    for slot, position in result.all():
        if position is None:
            continue
        by_team_week.setdefault((slot.team_id, slot.week), []).append(
            {"player_id": slot.platform_player_id, "position": position, "points": slot.points}
        )

    result = await session.execute(
        select(WeeklyScore).join(Team, WeeklyScore.team_id == Team.id).where(Team.league_id == league.id)
    )
    actual_by_team_week = {(ws.team_id, ws.week): ws.points for ws in result.scalars()}

    records = []
    for (team_id, week), roster in by_team_week.items():
        _, optimal_points = find_optimal_lineup(roster, starting_slots)
        actual_points = actual_by_team_week.get((team_id, week), 0.0)
        efficiency = actual_points / optimal_points if optimal_points else None
        records.append(
            {
                "team_id": team_id,
                "week": week,
                "actual_points": actual_points,
                "optimal_points": optimal_points,
                "efficiency": efficiency,
            }
        )

    return pd.DataFrame(
        records, columns=["team_id", "week", "actual_points", "optimal_points", "efficiency"]
    )
