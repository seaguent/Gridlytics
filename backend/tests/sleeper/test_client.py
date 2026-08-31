import httpx
import pytest
import respx

from app.sleeper.client import SLEEPER_BASE_URL, SLEEPER_PROJECTIONS_BASE_URL, SleeperClient


@pytest.mark.asyncio
@respx.mock
async def test_get_league_parses_response():
    respx.get(f"{SLEEPER_BASE_URL}/league/123").mock(
        return_value=httpx.Response(
            200,
            json={
                "league_id": "123",
                "name": "The League",
                "season": "2026",
                "season_type": "regular",
                "sport": "nfl",
                "status": "in_season",
                "total_rosters": 12,
            },
        )
    )

    client = SleeperClient()
    league = await client.get_league("123")
    await client.aclose()

    assert league.league_id == "123"
    assert league.name == "The League"


@pytest.mark.asyncio
@respx.mock
async def test_get_rosters_parses_list():
    respx.get(f"{SLEEPER_BASE_URL}/league/123/rosters").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "roster_id": 1,
                    "owner_id": "user_1",
                    "league_id": "123",
                    "players": ["1001"],
                    "starters": ["1001"],
                    "settings": {"wins": 5, "losses": 3, "ties": 0},
                },
                {
                    "roster_id": 2,
                    "owner_id": "user_2",
                    "league_id": "123",
                    "players": [],
                    "starters": [],
                    "settings": {"wins": 3, "losses": 5, "ties": 0},
                },
            ],
        )
    )

    client = SleeperClient()
    rosters = await client.get_rosters("123")
    await client.aclose()

    assert len(rosters) == 2
    assert rosters[0].settings.wins == 5


@pytest.mark.asyncio
@respx.mock
async def test_get_matchups_parses_list():
    respx.get(f"{SLEEPER_BASE_URL}/league/123/matchups/1").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "roster_id": 1,
                    "matchup_id": 4,
                    "points": 123.45,
                    "starters": ["1001"],
                    "players": ["1001", "1002"],
                },
                {
                    "roster_id": 2,
                    "matchup_id": 4,
                    "points": 110.2,
                    "starters": [],
                    "players": [],
                },
            ],
        )
    )

    client = SleeperClient()
    matchups = await client.get_matchups("123", week=1)
    await client.aclose()

    assert len(matchups) == 2
    assert matchups[0].points == 123.45


@pytest.mark.asyncio
@respx.mock
async def test_get_users_parses_list():
    respx.get(f"{SLEEPER_BASE_URL}/league/123/users").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "user_id": "user_1",
                    "display_name": "sean",
                    "metadata": {"team_name": "The Bench Warmers"},
                },
                {
                    "user_id": "user_2",
                    "display_name": "friend",
                    "metadata": {},
                },
            ],
        )
    )

    client = SleeperClient()
    users = await client.get_users("123")
    await client.aclose()

    assert len(users) == 2
    assert users[0].metadata["team_name"] == "The Bench Warmers"


@pytest.mark.asyncio
@respx.mock
async def test_get_all_players_parses_dict_keyed_by_player_id():
    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(
        return_value=httpx.Response(
            200,
            json={
                "100": {"position": "RB", "full_name": "Some Runningback"},
                "200": {"position": "DEF", "full_name": "San Francisco 49ers"},
            },
        )
    )

    client = SleeperClient()
    players = await client.get_all_players()
    await client.aclose()

    assert len(players) == 2
    assert players["100"].position == "RB"
    assert players["200"].full_name == "San Francisco 49ers"


@pytest.mark.asyncio
@respx.mock
async def test_get_projections_parses_list():
    respx.get(f"{SLEEPER_PROJECTIONS_BASE_URL}/2026/1").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "player_id": "7039",
                    "week": 1,
                    "stats": {"pts_std": 8.5, "pts_half_ppr": 10.6, "pts_ppr": 12.7},
                    "player": {"first_name": "Cody", "last_name": "White", "position": "WR"},
                },
                {
                    "player_id": "KC",
                    "week": 1,
                    "stats": {"pts_std": 8.12, "pts_half_ppr": 8.12, "pts_ppr": 8.12},
                    "player": {"first_name": "Kansas City", "last_name": "Chiefs", "position": "DEF"},
                },
            ],
        )
    )

    client = SleeperClient()
    projections = await client.get_projections("2026", 1)
    await client.aclose()

    assert len(projections) == 2
    assert projections[0].player_id == "7039"
    assert projections[0].stats.pts_half_ppr == 10.6
    assert projections[0].player.position == "WR"
