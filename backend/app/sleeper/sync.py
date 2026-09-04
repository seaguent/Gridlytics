from datetime import datetime, timedelta, UTC

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League, Matchup, Player
from app.nflverse.client import NflverseClient
from app.nflverse.sync import sync_usage_stats
from app.sleeper.adapter import sync_league, sync_projections, sync_week
from app.sleeper.client import SleeperClient
from app.sleeper.players import sync_players

PLAYER_CACHE_TTL = timedelta(hours=24)


async def _week_already_synced(session: AsyncSession, league: League, week: int) -> bool:
    # A Matchup row for this week only ever gets created by a real, previously-successful
    # sync_week call (each call commits once, at the end, so a crash mid-sync leaves nothing
    # behind for that week) -- existing tables already tell us what we need, no new state.
    result = await session.execute(
        select(Matchup.id).where(Matchup.league_id == league.id, Matchup.week == week).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def refresh_league(
    session: AsyncSession, client: SleeperClient, league_id: str, force_full_resync: bool = False
) -> League:
    league = await sync_league(session, client, league_id)

    result = await session.execute(
        select(func.max(Player.updated_at)).where(Player.platform == "sleeper")
    )
    last_player_sync = result.scalar_one_or_none()
    now = datetime.now(UTC).replace(tzinfo=None)
    if last_player_sync is None or now - last_player_sync > PLAYER_CACHE_TTL:
        await sync_players(session, client)

    for week in range(1, league.playoff_week_start):
        # Only completed PAST weeks are eligible to skip -- the current week can still have live
        # score/injury/role changes, and future weeks have no real data yet to check completeness
        # against (skipping them would also silently break the remaining-schedule pairings the
        # playoff-odds simulation depends on). A week with no existing Matchup row (a genuine gap,
        # or the league was just connected) is backfilled exactly as before.
        if not force_full_resync and week < league.current_week and await _week_already_synced(session, league, week):
            continue
        await sync_week(session, client, league, week)

    await sync_projections(session, client, league)

    nflverse_client = NflverseClient()
    try:
        await sync_usage_stats(session, nflverse_client, league)
    finally:
        await nflverse_client.aclose()

    return league
