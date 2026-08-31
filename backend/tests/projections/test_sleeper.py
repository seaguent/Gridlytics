import pytest

from app.models import League, ProjectionRecord
from app.projections.sleeper import SleeperProjectionProvider


@pytest.mark.asyncio
async def test_sleeper_projection_provider_reads_persisted_records(db_session):
    league = League(
        platform="sleeper",
        platform_league_id="1",
        season="2026",
        name="L",
        status="pre_draft",
        current_week=1,
    )
    db_session.add(league)
    await db_session.flush()

    db_session.add(
        ProjectionRecord(
            league_id=league.id,
            platform_player_id="7039",
            week=1,
            source="sleeper",
            name="Cody White",
            position="WR",
            projected_points=10.6,
        )
    )
    await db_session.commit()

    provider = SleeperProjectionProvider()
    projections = await provider.get_projections(db_session, league)

    assert len(projections) == 1
    assert projections[0].platform_player_id == "7039"
    assert projections[0].projected_points == 10.6
    assert projections[0].sources == ["sleeper"]


@pytest.mark.asyncio
async def test_sleeper_projection_provider_returns_nothing_for_espn_leagues(db_session):
    league = League(platform="espn", platform_league_id="1", season="2026", name="L", status="in_season")
    db_session.add(league)
    await db_session.flush()

    provider = SleeperProjectionProvider()
    projections = await provider.get_projections(db_session, league)

    assert projections == []
