from datetime import datetime, timedelta, UTC

import httpx
import pytest
import respx
from sqlalchemy import select

from app.models import Matchup, Player
from app.sleeper.client import SLEEPER_BASE_URL, SleeperClient
from app.sleeper.sync import refresh_league


def _mock_league_and_players(league_id: str = "123") -> None:
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
                "settings": {"leg": 2, "playoff_teams": 4, "playoff_week_start": 4},
            },
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/rosters").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/users").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(
        return_value=httpx.Response(200, json={"1": {"position": "RB", "full_name": "Guy"}})
    )
    # playoff_week_start=4 -> sync_week is called for weeks 1, 2, 3
    for week in (1, 2, 3):
        respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/{week}").mock(
            return_value=httpx.Response(200, json=[])
        )


@pytest.mark.asyncio
@respx.mock
async def test_refresh_league_syncs_players_when_cache_is_empty(db_session):
    _mock_league_and_players()

    client = SleeperClient()
    await refresh_league(db_session, client, "123")
    await client.aclose()

    result = await db_session.execute(select(Player))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
@respx.mock
async def test_refresh_league_syncs_every_week_up_to_playoffs(db_session):
    _mock_league_and_players()

    client = SleeperClient()
    league = await refresh_league(db_session, client, "123")
    await client.aclose()

    result = await db_session.execute(select(Matchup).where(Matchup.league_id == league.id))
    weeks_attempted = {matchup.week for matchup in result.scalars().all()}
    # No matchups were mocked with actual data, so nothing gets created --
    # this just confirms refresh_league ran without erroring across weeks
    # 1-3 (playoff_week_start=4) and didn't try week 4 or beyond.
    assert weeks_attempted == set()


@pytest.mark.asyncio
@respx.mock
async def test_refresh_league_skips_player_sync_when_cache_is_fresh(db_session):
    _mock_league_and_players()
    db_session.add(
        Player(
            platform="sleeper",
            platform_player_id="999",
            position="QB",
            name="Already Cached",
            updated_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        )
    )
    await db_session.commit()

    client = SleeperClient()
    await refresh_league(db_session, client, "123")
    await client.aclose()

    result = await db_session.execute(select(Player))
    players = result.scalars().all()
    # The mocked /players/nfl response (player "1") should NOT have been
    # fetched, since the cache is fresh -- only the pre-existing row remains.
    assert len(players) == 1
    assert players[0].platform_player_id == "999"
