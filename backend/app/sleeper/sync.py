from datetime import datetime, timedelta, UTC

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League, Player
from app.nflverse.client import NflverseClient
from app.nflverse.sync import sync_usage_stats
from app.sleeper.adapter import sync_league, sync_projections, sync_week
from app.sleeper.client import SleeperClient
from app.sleeper.players import sync_players

PLAYER_CACHE_TTL = timedelta(hours=24)


async def refresh_league(session: AsyncSession, client: SleeperClient, league_id: str) -> League:
    league = await sync_league(session, client, league_id)

    result = await session.execute(
        select(func.max(Player.updated_at)).where(Player.platform == "sleeper")
    )
    last_player_sync = result.scalar_one_or_none()
    now = datetime.now(UTC).replace(tzinfo=None)
    if last_player_sync is None or now - last_player_sync > PLAYER_CACHE_TTL:
        await sync_players(session, client)

    for week in range(1, league.playoff_week_start):
        await sync_week(session, client, league, week)

    await sync_projections(session, client, league)

    nflverse_client = NflverseClient()
    try:
        await sync_usage_stats(session, nflverse_client, league)
    finally:
        await nflverse_client.aclose()

    return league
