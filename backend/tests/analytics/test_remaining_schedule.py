import pytest

from app.analytics.loader import load_remaining_schedule
from app.models import League, Matchup, Team, WeeklyScore


@pytest.mark.asyncio
async def test_load_remaining_schedule_dedupes_each_matchup_to_one_entry(db_session):
    league = League(
        platform="sleeper",
        platform_league_id="1",
        season="2026",
        name="L",
        status="in_season",
        current_week=1,
    )
    db_session.add(league)
    await db_session.flush()

    teams = {
        name: Team(league_id=league.id, platform_roster_id=str(i), display_name=name)
        for i, name in enumerate(["A", "B", "C", "D"], start=1)
    }
    db_session.add_all(teams.values())
    await db_session.flush()

    # Week 1 is already played (current_week=1) -- should be excluded.
    week1 = Matchup(league_id=league.id, week=1, platform_matchup_id=1)
    # Week 2 has not been played yet -- should be included, once per pairing.
    week2_ab = Matchup(league_id=league.id, week=2, platform_matchup_id=2)
    week2_cd = Matchup(league_id=league.id, week=2, platform_matchup_id=3)
    db_session.add_all([week1, week2_ab, week2_cd])
    await db_session.flush()

    db_session.add_all(
        [
            WeeklyScore(team_id=teams["A"].id, matchup_id=week1.id, week=1, points=100),
            WeeklyScore(team_id=teams["B"].id, matchup_id=week1.id, week=1, points=90),
            WeeklyScore(team_id=teams["A"].id, matchup_id=week2_ab.id, week=2, points=0),
            WeeklyScore(team_id=teams["B"].id, matchup_id=week2_ab.id, week=2, points=0),
            WeeklyScore(team_id=teams["C"].id, matchup_id=week2_cd.id, week=2, points=0),
            WeeklyScore(team_id=teams["D"].id, matchup_id=week2_cd.id, week=2, points=0),
        ]
    )
    await db_session.commit()

    remaining = await load_remaining_schedule(db_session, league)

    assert len(remaining) == 2
    pairings = {frozenset({a, b}) for _week, a, b in remaining}
    assert pairings == {
        frozenset({teams["A"].id, teams["B"].id}),
        frozenset({teams["C"].id, teams["D"].id}),
    }
    assert all(week == 2 for week, _a, _b in remaining)
