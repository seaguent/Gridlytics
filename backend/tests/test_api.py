import httpx
import pytest
import pytest_asyncio
import respx
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.deps import get_session
from app.main import app
from app.models import Base
from app.nflverse.client import NFLVERSE_RELEASES_BASE_URL
from app.sleeper.client import SLEEPER_BASE_URL
from app.tokens import hash_token


def _mock_nflverse_season_not_published(season: str) -> None:
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_{season}.csv").mock(
        return_value=httpx.Response(404)
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/players/players.csv").mock(
        return_value=httpx.Response(200, text="gsis_id,display_name,espn_id,pfr_id,position\n")
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/schedules/games.csv").mock(
        return_value=httpx.Response(200, text="season,week,home_team,away_team\n")
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_reg_{int(season) - 1}.csv").mock(
        return_value=httpx.Response(404)
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_{int(season) - 1}.csv").mock(
        return_value=httpx.Response(404)
    )


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def client(test_engine):
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    yield TestClient(app)
    app.dependency_overrides.clear()


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
                    "roster_id": 1,
                    "owner_id": "u1",
                    "league_id": league_id,
                    "players": [],
                    "starters": [],
                    "settings": {"wins": 1, "losses": 0, "ties": 0, "fpts": 100, "fpts_against": 90},
                },
                {
                    "roster_id": 2,
                    "owner_id": "u2",
                    "league_id": league_id,
                    "players": [],
                    "starters": [],
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
    for week in (1, 2):
        respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/{week}").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"roster_id": 1, "matchup_id": 10, "points": 100, "starters": [], "players": []},
                    {"roster_id": 2, "matchup_id": 10, "points": 90, "starters": [], "players": []},
                ],
            )
        )


@respx.mock
def test_create_connection_and_fetch_standings(client):
    _mock_sleeper_league()

    connect_response = client.post(
        "/connections",
        json={
            "platform": "sleeper",
            "platform_league_id": "123",
            "access_token_hash": hash_token("my-secret-token"),
        },
    )
    assert connect_response.status_code == 200
    assert connect_response.json()["name"] == "The League"

    standings_response = client.get(
        "/leagues/me/standings",
        headers={"Authorization": "Bearer my-secret-token"},
    )
    assert standings_response.status_code == 200
    standings = standings_response.json()
    assert len(standings) == 2
    assert {row["display_name"] for row in standings} == {"sean", "friend"}

    info_response = client.get(
        "/leagues/me", headers={"Authorization": "Bearer my-secret-token"}
    )
    assert info_response.status_code == 200
    assert info_response.json() == {
        "name": "The League",
        "season": "2026",
        "status": "in_season",
        "current_week": 1,
        "scoring_is_custom": False,
        "scoring_notes": [],
        "my_team_id": None,
    }

    sean_team_id = next(row["team_id"] for row in standings if row["display_name"] == "sean")
    set_team_response = client.post(
        "/leagues/me/my-team",
        json={"team_id": sean_team_id},
        headers={"Authorization": "Bearer my-secret-token"},
    )
    assert set_team_response.status_code == 200
    assert set_team_response.json() == {"status": "ok", "my_team_id": sean_team_id}

    info_response = client.get(
        "/leagues/me", headers={"Authorization": "Bearer my-secret-token"}
    )
    assert info_response.json()["my_team_id"] == sean_team_id


@respx.mock
def test_start_sit_requires_a_selected_team(client):
    _mock_sleeper_league()
    client.post(
        "/connections",
        json={
            "platform": "sleeper",
            "platform_league_id": "123",
            "access_token_hash": hash_token("no-team-token"),
        },
    )

    response = client.get(
        "/leagues/me/start-sit", headers={"Authorization": "Bearer no-team-token"}
    )
    assert response.status_code == 400


@respx.mock
def test_start_sit_returns_lineup_once_team_is_selected(client):
    _mock_sleeper_league()
    connect_response = client.post(
        "/connections",
        json={
            "platform": "sleeper",
            "platform_league_id": "123",
            "access_token_hash": hash_token("start-sit-token"),
        },
    )
    assert connect_response.status_code == 200

    standings = client.get(
        "/leagues/me/standings", headers={"Authorization": "Bearer start-sit-token"}
    ).json()
    sean_team_id = next(row["team_id"] for row in standings if row["display_name"] == "sean")
    client.post(
        "/leagues/me/my-team",
        json={"team_id": sean_team_id},
        headers={"Authorization": "Bearer start-sit-token"},
    )

    respx.get(f"{SLEEPER_BASE_URL}/league/123/rosters").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "roster_id": 1, "owner_id": "u1", "league_id": "123",
                    "players": [], "starters": [], "settings": {"wins": 1, "losses": 0, "ties": 0},
                },
                {
                    "roster_id": 2, "owner_id": "u2", "league_id": "123",
                    "players": [], "starters": [], "settings": {"wins": 0, "losses": 1, "ties": 0},
                },
            ],
        )
    )

    response = client.get(
        "/leagues/me/start-sit", headers={"Authorization": "Bearer start-sit-token"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "starters": [],
        "bench": [],
        "unavailable": [],
        "optimal_points": 0.0,
        "summary": {"changes_count": 0, "current_lineup_points": 0.0, "projected_points_change": 0.0},
    }


@respx.mock
def test_set_my_team_rejects_team_from_another_league(client):
    _mock_sleeper_league()
    client.post(
        "/connections",
        json={
            "platform": "sleeper",
            "platform_league_id": "123",
            "access_token_hash": hash_token("wrong-team-token"),
        },
    )

    response = client.post(
        "/leagues/me/my-team",
        json={"team_id": 999999},
        headers={"Authorization": "Bearer wrong-team-token"},
    )
    assert response.status_code == 400


@respx.mock
def test_league_info_flags_custom_sleeper_scoring(client):
    league_id = "custom1"
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "league_id": league_id,
                "name": "6pt Passing League",
                "season": "2026",
                "season_type": "regular",
                "sport": "nfl",
                "status": "in_season",
                "total_rosters": 1,
                "settings": {"leg": 1, "playoff_teams": 1, "playoff_week_start": 1},
                "scoring_settings": {"pass_td": 6.0, "rec": 1.0},
            },
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/rosters").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/users").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(return_value=httpx.Response(200, json={}))

    connect_response = client.post(
        "/connections",
        json={
            "platform": "sleeper",
            "platform_league_id": league_id,
            "access_token_hash": hash_token("custom-scoring-token"),
        },
    )
    assert connect_response.status_code == 200

    info_response = client.get(
        "/leagues/me", headers={"Authorization": "Bearer custom-scoring-token"}
    )
    body = info_response.json()
    assert body["scoring_is_custom"] is True
    assert any("pass_td" in note for note in body["scoring_notes"])


@respx.mock
def test_rankings_does_not_label_a_defense_as_rookie_for_lacking_usage_stats(client):
    import copy

    from tests.espn.test_parser import SAMPLE_RAW

    _mock_nflverse_season_not_published("2026")

    raw = copy.deepcopy(SAMPLE_RAW)
    starter_qb = raw["teams"][0]["roster"]["entries"][0]
    starter_qb["playerPoolEntry"]["player"]["stats"] = [
        {"scoringPeriodId": 3, "statSourceId": 1, "appliedTotal": 18.2}
    ]
    raw["teams"][0]["roster"]["entries"].append(
        {
            "playerId": 999,
            "lineupSlotId": 16,
            "playerPoolEntry": {
                "player": {
                    "fullName": "Test Defense",
                    "defaultPositionId": 16,
                    "proTeamId": 12,
                    "stats": [{"scoringPeriodId": 3, "statSourceId": 1, "appliedTotal": 8.0}],
                }
            },
        }
    )

    connect_response = client.post(
        "/connections/espn",
        json={"raw_league_data": raw, "access_token_hash": hash_token("def-test-token")},
    )
    assert connect_response.status_code == 200

    rankings_response = client.get(
        "/leagues/me/rankings", headers={"Authorization": "Bearer def-test-token"}
    )
    assert rankings_response.status_code == 200
    rows = {row["platform_player_id"]: row for row in rankings_response.json()}

    assert rows["999"]["position"] == "DEF"
    assert rows["999"]["experience_status"] == "not_applicable"
    assert rows["111"]["experience_status"] == "rookie_or_limited_history"
    # No source="gridlytics" ProjectionRecord seeded in this flow -- fields must be null, not
    # fabricated as zero.
    assert rows["111"]["gridlytics_projected_points"] is None
    assert rows["111"]["gridlytics_dominant_category"] is None
    assert rows["111"]["gridlytics_lower_confidence"] is False


@respx.mock
def test_rankings_projected_points_is_the_blended_final_gridlytics_projection(client, test_engine):
    import copy

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models import League, ProjectionRecord
    from tests.espn.test_parser import SAMPLE_RAW

    _mock_nflverse_season_not_published("2026")

    raw = copy.deepcopy(SAMPLE_RAW)
    starter_qb = raw["teams"][0]["roster"]["entries"][0]
    starter_qb["playerPoolEntry"]["player"]["stats"] = [
        {"scoringPeriodId": 3, "statSourceId": 1, "appliedTotal": 12.0}
    ]

    connect_response = client.post(
        "/connections/espn",
        json={"raw_league_data": raw, "access_token_hash": hash_token("blend-test-token")},
    )
    assert connect_response.status_code == 200

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def _seed_gridlytics_projection():
        async with session_factory() as session:
            result = await session.execute(select(League))
            league = result.scalars().one()
            session.add(
                ProjectionRecord(
                    league_id=league.id, platform_player_id="111", week=league.current_week,
                    source="gridlytics", name="QB Starter", position="QB", projected_points=16.0,
                )
            )
            await session.commit()

    import asyncio
    asyncio.run(_seed_gridlytics_projection())

    rankings_response = client.get(
        "/leagues/me/rankings", headers={"Authorization": "Bearer blend-test-token"}
    )
    assert rankings_response.status_code == 200
    rows = {row["platform_player_id"]: row for row in rankings_response.json()}

    row = rows["111"]
    assert row["gridlytics_base_projection"] == pytest.approx(16.0)
    assert row["platform_projection"] == pytest.approx(12.0)
    assert row["final_gridlytics_projection"] == pytest.approx(14.0)
    assert row["projected_points"] == pytest.approx(14.0)


@respx.mock
def test_espn_connection_and_resync_flow(client):
    from tests.espn.test_parser import SAMPLE_RAW

    _mock_nflverse_season_not_published("2026")

    connect_response = client.post(
        "/connections/espn",
        json={
            "raw_league_data": SAMPLE_RAW,
            "access_token_hash": hash_token("espn-secret-token"),
        },
    )
    assert connect_response.status_code == 200
    assert connect_response.json()["name"] == "Test League"

    # no respx mock set up here -- would hang if get_fresh_league tried a Sleeper refresh for this ESPN league
    standings_response = client.get(
        "/leagues/me/standings",
        headers={"Authorization": "Bearer espn-secret-token"},
    )
    assert standings_response.status_code == 200
    assert len(standings_response.json()) == 2

    updated_raw = {**SAMPLE_RAW}
    updated_raw["teams"] = [
        {**SAMPLE_RAW["teams"][0], "record": {"overall": {"wins": 3, "losses": 1, "ties": 0, "pointsFor": 400.0, "pointsAgainst": 300.0}}},
        SAMPLE_RAW["teams"][1],
    ]
    resync_response = client.post(
        "/leagues/me/resync-espn",
        json={"raw_league_data": updated_raw},
        headers={"Authorization": "Bearer espn-secret-token"},
    )
    assert resync_response.status_code == 200

    standings_response = client.get(
        "/leagues/me/standings",
        headers={"Authorization": "Bearer espn-secret-token"},
    )
    team_one = next(row for row in standings_response.json() if row["display_name"] == "Team One")
    assert team_one["wins"] == 3


@respx.mock
def test_projection_accuracy_endpoint_returns_expected_shape(client):
    _mock_sleeper_league()

    connect_response = client.post(
        "/connections",
        json={
            "platform": "sleeper",
            "platform_league_id": "123",
            "access_token_hash": hash_token("my-secret-token"),
        },
    )
    assert connect_response.status_code == 200

    response = client.get(
        "/leagues/me/projection-accuracy", headers={"Authorization": "Bearer my-secret-token"}
    )
    assert response.status_code == 200
    body = response.json()
    # No ProjectionRecord/RosterSlot data seeded in this test -- correctly empty, not fabricated.
    assert body == {"all_available": [], "common_sample": []}


def test_missing_authorization_header_returns_401(client):
    response = client.get("/leagues/me/standings")
    assert response.status_code == 401


def test_invalid_token_returns_401(client):
    response = client.get(
        "/leagues/me/standings", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401
