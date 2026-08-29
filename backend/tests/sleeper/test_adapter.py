import httpx
import pytest
import respx
from sqlalchemy import select

from app.models import Matchup, RosterSlot, Team, WeeklyScore
from app.sleeper.adapter import sync_league, sync_week
from app.sleeper.client import SLEEPER_BASE_URL, SleeperClient


def _mock_sleeper_league(league_id: str) -> None:
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
                    "players": [],
                    "starters": [],
                    "settings": {"wins": 5, "losses": 3, "ties": 0, "fpts": 800, "fpts_against": 700},
                },
                {
                    "roster_id": 2,
                    "owner_id": "u2",
                    "league_id": league_id,
                    "players": [],
                    "starters": [],
                    "settings": {"wins": 3, "losses": 5, "ties": 0, "fpts": 700, "fpts_against": 800},
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


def _mock_sleeper_week1_matchups(league_id: str) -> None:
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/1").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"roster_id": 1, "matchup_id": 10, "points": 105.5, "starters": [], "players": []},
                {"roster_id": 2, "matchup_id": 10, "points": 98.2, "starters": [], "players": []},
            ],
        )
    )


@pytest.mark.asyncio
@respx.mock
async def test_sync_league_creates_league_and_teams(db_session):
    _mock_sleeper_league("123")

    client = SleeperClient()
    league = await sync_league(db_session, client, "123")
    await client.aclose()

    assert league.name == "The League"
    assert league.platform == "sleeper"

    result = await db_session.execute(select(Team).where(Team.league_id == league.id))
    teams = result.scalars().all()
    assert len(teams) == 2
    assert {team.display_name for team in teams} == {"sean", "friend"}
    assert {team.wins for team in teams} == {5, 3}


@pytest.mark.asyncio
@respx.mock
async def test_sync_league_is_idempotent(db_session):
    _mock_sleeper_league("123")

    client = SleeperClient()
    await sync_league(db_session, client, "123")
    league = await sync_league(db_session, client, "123")
    await client.aclose()

    result = await db_session.execute(select(Team).where(Team.league_id == league.id))
    teams = result.scalars().all()
    assert len(teams) == 2


@pytest.mark.asyncio
@respx.mock
async def test_sync_week_creates_matchups_and_weekly_scores(db_session):
    _mock_sleeper_league("123")
    _mock_sleeper_week1_matchups("123")

    client = SleeperClient()
    league = await sync_league(db_session, client, "123")
    await sync_week(db_session, client, league, week=1)
    await client.aclose()

    result = await db_session.execute(select(Matchup).where(Matchup.league_id == league.id))
    matchups = result.scalars().all()
    assert len(matchups) == 1
    assert matchups[0].platform_matchup_id == 10

    result = await db_session.execute(
        select(WeeklyScore).where(WeeklyScore.matchup_id == matchups[0].id)
    )
    scores = result.scalars().all()
    assert len(scores) == 2
    assert {score.points for score in scores} == {105.5, 98.2}


@pytest.mark.asyncio
@respx.mock
async def test_sync_week_is_idempotent(db_session):
    _mock_sleeper_league("123")
    _mock_sleeper_week1_matchups("123")

    client = SleeperClient()
    league = await sync_league(db_session, client, "123")
    await sync_week(db_session, client, league, week=1)
    await sync_week(db_session, client, league, week=1)
    await client.aclose()

    result = await db_session.execute(select(Matchup).where(Matchup.league_id == league.id))
    assert len(result.scalars().all()) == 1

    result = await db_session.execute(select(WeeklyScore))
    assert len(result.scalars().all()) == 2


@pytest.mark.asyncio
@respx.mock
async def test_sync_week_creates_roster_slots(db_session):
    _mock_sleeper_league("123")
    respx.get(f"{SLEEPER_BASE_URL}/league/123/matchups/1").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "roster_id": 1,
                    "matchup_id": 10,
                    "points": 105.5,
                    "starters": ["100", "101"],
                    "players": ["100", "101", "102"],
                    "players_points": {"100": 60.5, "101": 45.0, "102": 20.0},
                },
                {
                    "roster_id": 2,
                    "matchup_id": 10,
                    "points": 98.2,
                    "starters": ["200"],
                    "players": ["200", "201"],
                    "players_points": {"200": 98.2, "201": 15.0},
                },
            ],
        )
    )

    client = SleeperClient()
    league = await sync_league(db_session, client, "123")
    await sync_week(db_session, client, league, week=1)
    await client.aclose()

    result = await db_session.execute(select(Team).where(Team.platform_roster_id == "1"))
    team_1 = result.scalar_one()

    result = await db_session.execute(select(RosterSlot).where(RosterSlot.team_id == team_1.id))
    slots = {slot.platform_player_id: slot for slot in result.scalars().all()}

    assert len(slots) == 3
    assert slots["100"].is_starter is True
    assert slots["100"].points == 60.5
    assert slots["102"].is_starter is False
    assert slots["102"].points == 20.0


@pytest.mark.asyncio
@respx.mock
async def test_sync_week_roster_slots_is_idempotent(db_session):
    _mock_sleeper_league("123")
    respx.get(f"{SLEEPER_BASE_URL}/league/123/matchups/1").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "roster_id": 1,
                    "matchup_id": 10,
                    "points": 105.5,
                    "starters": ["100"],
                    "players": ["100", "102"],
                    "players_points": {"100": 60.5, "102": 20.0},
                },
                {
                    "roster_id": 2,
                    "matchup_id": 10,
                    "points": 98.2,
                    "starters": ["200"],
                    "players": ["200"],
                    "players_points": {"200": 98.2},
                },
            ],
        )
    )

    client = SleeperClient()
    league = await sync_league(db_session, client, "123")
    await sync_week(db_session, client, league, week=1)
    await sync_week(db_session, client, league, week=1)
    await client.aclose()

    result = await db_session.execute(select(RosterSlot))
    assert len(result.scalars().all()) == 3
