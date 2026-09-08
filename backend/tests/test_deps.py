import asyncio
from datetime import datetime, timedelta, UTC

import httpx
import pytest
import pytest_asyncio
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.deps import get_fresh_league
from app.models import Base, League, Matchup
from app.sleeper.adapter import sync_league
from app.sleeper.client import SLEEPER_BASE_URL, SleeperClient


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


def _mock_sleeper_league(league_id: str = "123") -> None:
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "league_id": league_id,
                "name": "The League",
                "season": "2026",
                "season_type": "regular",
                "sport": "nfl",
                "status": "in_season",
                "total_rosters": 2,
                "settings": {"leg": 1, "playoff_teams": 2, "playoff_week_start": 3},
            },
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/rosters").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "roster_id": 1, "owner_id": "u1", "league_id": league_id,
                    "players": [], "starters": [],
                    "settings": {"wins": 1, "losses": 0, "ties": 0, "fpts": 100, "fpts_against": 90},
                },
                {
                    "roster_id": 2, "owner_id": "u2", "league_id": league_id,
                    "players": [], "starters": [],
                    "settings": {"wins": 0, "losses": 1, "ties": 0, "fpts": 90, "fpts_against": 100},
                },
            ],
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/users").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"user_id": "u1", "display_name": "sean", "metadata": {}},
                {"user_id": "u2", "display_name": "friend", "metadata": {}},
            ],
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/1").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"roster_id": 1, "matchup_id": 10, "points": 100, "starters": [], "players": []},
                {"roster_id": 2, "matchup_id": 10, "points": 90, "starters": [], "players": []},
            ],
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/2").mock(
        return_value=httpx.Response(200, json=[])
    )


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_get_fresh_league_calls_do_not_create_duplicate_matchups(test_engine):
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    _mock_sleeper_league("123")

    async with session_factory() as setup_session:
        client = SleeperClient()
        league = await sync_league(setup_session, client, "123")
        await client.aclose()
        league.last_synced_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        setup_session.add(league)
        await setup_session.commit()
        league_id = league.id

    async def call_get_fresh_league():
        async with session_factory() as session:
            result = await session.execute(select(League).where(League.id == league_id))
            stale_league = result.scalar_one()
            return await get_fresh_league(league=stale_league, session=session)

    await asyncio.gather(call_get_fresh_league(), call_get_fresh_league())

    async with session_factory() as check_session:
        result = await check_session.execute(
            select(Matchup).where(Matchup.league_id == league_id, Matchup.week == 1)
        )
        matchups = result.scalars().all()
        assert len(matchups) == 1
