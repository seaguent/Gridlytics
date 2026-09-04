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
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/rosters").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/users").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(return_value=httpx.Response(200, json={}))
    for week in (1, 2):
        respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/{week}").mock(
            return_value=httpx.Response(200, json=[])
        )


@respx.mock
def test_unauthenticated_connections_endpoint_is_limited_to_5_per_minute(client):
    _mock_sleeper_league()

    responses = [
        client.post(
            "/connections",
            json={
                "platform": "sleeper",
                "platform_league_id": "123",
                "access_token_hash": hash_token(f"token-{i}"),
            },
        )
        for i in range(6)
    ]

    statuses = [r.status_code for r in responses]
    assert statuses[:5] == [200, 200, 200, 200, 200]
    assert statuses[5] == 429


@respx.mock
def test_authenticated_endpoint_default_limit_allows_normal_polling(client):
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

    response = client.get("/leagues/me", headers={"Authorization": "Bearer my-secret-token"})
    assert response.status_code == 200


@respx.mock
def test_authenticated_endpoint_is_limited_to_60_per_minute(client):
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

    headers = {"Authorization": "Bearer my-secret-token"}
    responses = [client.get("/leagues/me", headers=headers) for _ in range(61)]

    statuses = [r.status_code for r in responses]
    assert statuses[:60] == [200] * 60
    assert statuses[60] == 429


@respx.mock
def test_different_tokens_have_independent_rate_limit_buckets(client):
    _mock_sleeper_league()

    for token in ("token-a", "token-b"):
        connect_response = client.post(
            "/connections",
            json={
                "platform": "sleeper",
                "platform_league_id": "123",
                "access_token_hash": hash_token(token),
            },
        )
        assert connect_response.status_code == 200

    for _ in range(60):
        response = client.get("/leagues/me", headers={"Authorization": "Bearer token-a"})
        assert response.status_code == 200

    exhausted_response = client.get("/leagues/me", headers={"Authorization": "Bearer token-a"})
    assert exhausted_response.status_code == 429

    other_token_response = client.get("/leagues/me", headers={"Authorization": "Bearer token-b"})
    assert other_token_response.status_code == 200
