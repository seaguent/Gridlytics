import httpx
import pytest
import pytest_asyncio
import respx
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.deps import get_session
from app.main import app
from app.models import Base
from app.sleeper.client import SLEEPER_BASE_URL
from app.tokens import hash_token


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
    }


def test_missing_authorization_header_returns_401(client):
    response = client.get("/leagues/me/standings")
    assert response.status_code == 401


def test_invalid_token_returns_401(client):
    response = client.get(
        "/leagues/me/standings", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401
