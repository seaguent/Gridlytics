import logging

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.deps import get_session
from app.main import app
from app.models import Base


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
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_unhandled_exception_returns_generic_500_without_leaking_details(client, caplog):
    async def broken_get_session():
        raise RuntimeError("boom: something internal broke")
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = broken_get_session

    with caplog.at_level(logging.ERROR):
        response = client.get("/leagues/me", headers={"Authorization": "Bearer some-token"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "boom" not in response.text


def test_unhandled_exception_is_logged_with_traceback(client, caplog):
    async def broken_get_session():
        raise RuntimeError("boom: something internal broke")
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = broken_get_session

    with caplog.at_level(logging.ERROR):
        client.get("/leagues/me", headers={"Authorization": "Bearer some-token"})

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) == 1
    assert "/leagues/me" in error_records[0].message
    assert error_records[0].exc_info is not None


def test_expected_http_exceptions_are_unaffected(client):
    response = client.get("/leagues/me", headers={"Authorization": "Bearer no-such-token"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid access token"}
