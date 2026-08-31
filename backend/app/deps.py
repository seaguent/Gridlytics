from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, UTC

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import League, LeagueConnection
from app.sleeper.client import SleeperClient
from app.sleeper.sync import refresh_league
from app.tokens import hash_token

REFRESH_TTL = timedelta(minutes=30)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def get_current_league(
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
) -> League:
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

    result = await session.execute(select(League).where(League.id == connection.league_id))
    return result.scalar_one()


async def get_fresh_league(
    league: League = Depends(get_current_league),
    session: AsyncSession = Depends(get_session),
) -> League:
    now = datetime.now(UTC).replace(tzinfo=None)
    if league.last_synced_at is None or now - league.last_synced_at > REFRESH_TTL:
        client = SleeperClient()
        try:
            league = await refresh_league(session, client, league.platform_league_id)
        finally:
            await client.aclose()
    return league
