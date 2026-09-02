import pytest

from app.models import League, ProjectionRecord, RosterSlot, Team
from app.projections.accuracy_pipeline import load_projection_accuracy


async def _make_league(db_session, current_week: int = 3) -> League:
    league = League(
        platform="espn", platform_league_id="1", season="2026", name="L",
        status="in_season", current_week=current_week,
    )
    db_session.add(league)
    await db_session.flush()
    return league


async def _make_team(db_session, league: League) -> Team:
    team = Team(league_id=league.id, platform_roster_id="1", display_name="A")
    db_session.add(team)
    await db_session.flush()
    return team


@pytest.mark.asyncio
async def test_real_zero_actual_counts_as_eligible(db_session):
    league = await _make_league(db_session)
    team = await _make_team(db_session, league)
    db_session.add(RosterSlot(team_id=team.id, week=1, platform_player_id="p1", is_starter=True, points=0.0))
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="p1", week=1, source="espn",
                          name="P", position="WR", projected_points=8.0)
    )
    await db_session.commit()

    report = await load_projection_accuracy(db_session, league)
    assert report.all_available[0].sample_size == 1
    assert report.all_available[0].mae == pytest.approx(8.0)


@pytest.mark.asyncio
async def test_missing_roster_slot_is_excluded_not_defaulted_to_zero(db_session):
    league = await _make_league(db_session)
    # No RosterSlot row at all for (p1, week 1) -- a bye or unconfirmed week.
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="p1", week=1, source="espn",
                          name="P", position="WR", projected_points=8.0)
    )
    await db_session.commit()

    report = await load_projection_accuracy(db_session, league)
    assert report.all_available == []


@pytest.mark.asyncio
async def test_current_and_future_weeks_excluded(db_session):
    league = await _make_league(db_session, current_week=3)
    team = await _make_team(db_session, league)
    db_session.add(RosterSlot(team_id=team.id, week=3, platform_player_id="p1", is_starter=True, points=10.0))
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="p1", week=3, source="espn",
                          name="P", position="WR", projected_points=9.0)
    )
    await db_session.commit()

    report = await load_projection_accuracy(db_session, league)
    assert report.all_available == []
