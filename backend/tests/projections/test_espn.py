import pytest
from sqlalchemy import select

from app.espn.adapter import sync_league
from app.models import ProjectionRecord
from app.projections.espn import ESPNProjectionProvider
from tests.espn.test_projections import _sample_with_stats


@pytest.mark.asyncio
async def test_espn_sync_persists_projections_and_provider_reads_them_back(db_session):
    raw = _sample_with_stats()

    league = await sync_league(db_session, raw)

    result = await db_session.execute(select(ProjectionRecord).where(ProjectionRecord.source == "espn"))
    records = result.scalars().all()
    assert len(records) == 1
    assert records[0].projected_points == 18.2

    provider = ESPNProjectionProvider()
    projections = await provider.get_projections(db_session, league)

    assert len(projections) == 1
    assert projections[0].platform_player_id == "111"
    assert projections[0].projected_points == 18.2
    assert projections[0].sources == ["espn"]


@pytest.mark.asyncio
async def test_espn_sync_is_idempotent_for_projections(db_session):
    raw = _sample_with_stats()

    await sync_league(db_session, raw)
    await sync_league(db_session, raw)

    result = await db_session.execute(select(ProjectionRecord).where(ProjectionRecord.source == "espn"))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_espn_projection_provider_returns_nothing_for_sleeper_leagues(db_session):
    from app.models import League

    league = League(platform="sleeper", platform_league_id="1", season="2026", name="L", status="in_season")
    db_session.add(league)
    await db_session.flush()

    provider = ESPNProjectionProvider()
    projections = await provider.get_projections(db_session, league)

    assert projections == []
