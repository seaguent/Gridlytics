from datetime import datetime, timedelta, UTC

import httpx
import pytest
import respx
from sqlalchemy import select

from app.models import Matchup, Player, ProjectionRecord
from app.sleeper.client import SLEEPER_BASE_URL, SLEEPER_PROJECTIONS_BASE_URL, SleeperClient
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
    # rosters are empty, so sync_projections returns early without calling the projections endpoint


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
    # Confirms refresh_league ran weeks 1-3 (playoff_week_start=4) without erroring and stopped there.
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
    # Cache is fresh, so /players/nfl should not have been fetched -- only the pre-existing row remains.
    assert len(players) == 1
    assert players[0].platform_player_id == "999"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_league_syncs_projections_for_rostered_players(db_session):
    league_id = "123"
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
                "total_rosters": 1,
                "settings": {"leg": 1, "playoff_teams": 4, "playoff_week_start": 1},
                "scoring_settings": {"rec": 1.0},
            },
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/rosters").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "roster_id": 1,
                    "owner_id": "u1",
                    "league_id": league_id,
                    "players": ["7039"],
                    "starters": [],
                    "settings": {"wins": 0, "losses": 0, "ties": 0},
                }
            ],
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/users").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(
        return_value=httpx.Response(200, json={"1": {"position": "RB", "full_name": "Guy"}})
    )
    # playoff_week_start=1 -> sync_week's range(1, 1) is empty, no matchup calls
    respx.get(f"{SLEEPER_PROJECTIONS_BASE_URL}/2026/1").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "player_id": "7039",
                    "week": 1,
                    "stats": {"pts_std": 8.5, "pts_half_ppr": 10.6, "pts_ppr": 12.7},
                    "player": {"first_name": "Cody", "last_name": "White", "position": "WR"},
                }
            ],
        )
    )

    client = SleeperClient()
    await refresh_league(db_session, client, league_id)
    await client.aclose()

    result = await db_session.execute(
        select(ProjectionRecord).where(ProjectionRecord.source == "sleeper")
    )
    records = result.scalars().all()
    assert len(records) == 1
    assert records[0].platform_player_id == "7039"
    # rec=1.0 -> full PPR
    assert records[0].projected_points == 12.7
