import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, UTC

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import League, LeagueConnection, Team
from app.sleeper.client import SleeperClient
from app.sleeper.sync import refresh_league
from app.tokens import hash_token

REFRESH_TTL = timedelta(minutes=30)

_league_refresh_locks: dict[int, asyncio.Lock] = {}


def _get_league_refresh_lock(league_id: int) -> asyncio.Lock:
    lock = _league_refresh_locks.get(league_id)
    if lock is None:
        lock = asyncio.Lock()
        _league_refresh_locks[league_id] = lock
    return lock


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def get_current_connection(
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
) -> LeagueConnection:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ")
    token_hash = hash_token(token)

    result = await session.execute(
        select(LeagueConnection).where(LeagueConnection.access_token_hash == token_hash)
    )
    connection = result.scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=401, detail="Invalid access token")
    return connection


async def get_current_league(
    connection: LeagueConnection = Depends(get_current_connection),
    session: AsyncSession = Depends(get_session),
) -> League:
    result = await session.execute(select(League).where(League.id == connection.league_id))
    return result.scalar_one()


async def get_my_team(
    connection: LeagueConnection = Depends(get_current_connection),
    session: AsyncSession = Depends(get_session),
) -> Team:
    if connection.my_team_id is None:
        raise HTTPException(status_code=400, detail="No team selected for this league yet")
    result = await session.execute(select(Team).where(Team.id == connection.my_team_id))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=400, detail="Selected team no longer exists")
    return team


async def get_fresh_league(
    league: League = Depends(get_current_league),
    session: AsyncSession = Depends(get_session),
) -> League:
    if league.platform != "sleeper":
        # Non-Sleeper platforms only update via an authenticated client POST, not a server-side refresh.
        return league

    async with _get_league_refresh_lock(league.id):
        # Re-check inside the lock -- another request may have already refreshed while we waited.
        result = await session.execute(select(League).where(League.id == league.id))
        league = result.scalar_one()

        now = datetime.now(UTC).replace(tzinfo=None)
        if league.last_synced_at is None or now - league.last_synced_at > REFRESH_TTL:
            client = SleeperClient()
            try:
                league = await refresh_league(session, client, league.platform_league_id)
            finally:
                await client.aclose()
    return league
