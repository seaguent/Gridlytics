import httpx
import pytest
import respx
from sqlalchemy import select

from app.models import Player
from app.sleeper.client import SLEEPER_BASE_URL, SleeperClient
from app.sleeper.players import sync_players


def _mock_players() -> None:
    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(
        return_value=httpx.Response(
            200,
            json={
                "100": {
                    "position": "RB",
                    "full_name": "Some Runningback",
                    "gsis_id": "00-0012345",
                    "team": "SF",
                    "injury_status": "Questionable",
                },
                "999": {"position": None, "full_name": "Retired Guy"},
            },
        )
    )


@pytest.mark.asyncio
@respx.mock
async def test_sync_players_stores_only_players_with_a_position(db_session):
    _mock_players()

    client = SleeperClient()
    await sync_players(db_session, client)
    await client.aclose()

    result = await db_session.execute(select(Player))
    players = result.scalars().all()

    assert len(players) == 1
    assert players[0].platform_player_id == "100"
    assert players[0].position == "RB"
    assert players[0].gsis_id == "00-0012345"
    assert players[0].team == "SF"
    assert players[0].injury_status == "Questionable"


@pytest.mark.asyncio
@respx.mock
async def test_sync_players_is_idempotent(db_session):
    _mock_players()

    client = SleeperClient()
    await sync_players(db_session, client)
    await sync_players(db_session, client)
    await client.aclose()

    result = await db_session.execute(select(Player))
    assert len(result.scalars().all()) == 1
