import pytest

from app.analytics.loader import load_roster_slots
from app.models import League, RosterSlot, Team


@pytest.mark.asyncio
async def test_load_roster_slots(db_session):
    league = League(
        platform="sleeper",
        platform_league_id="1",
        season="2026",
        name="L",
        status="in_season",
    )
    db_session.add(league)
    await db_session.flush()

    team = Team(league_id=league.id, platform_roster_id="1", display_name="A")
    db_session.add(team)
    await db_session.flush()

    db_session.add_all(
        [
            RosterSlot(team_id=team.id, week=1, platform_player_id="100", is_starter=True, points=60.5),
            RosterSlot(team_id=team.id, week=1, platform_player_id="102", is_starter=False, points=20.0),
        ]
    )
    await db_session.commit()

    df = await load_roster_slots(db_session, league.id)

    assert len(df) == 2
    bench_row = df[df["is_starter"] == False].iloc[0]  # noqa: E712
    assert bench_row["points"] == 20.0
    assert bench_row["team_id"] == team.id
