import pytest

from app.analytics.loader import load_weekly_scores
from app.models import League, Matchup, Team, WeeklyScore


@pytest.mark.asyncio
async def test_load_weekly_scores_includes_opponent(db_session):
    league = League(
        platform="sleeper",
        platform_league_id="1",
        season="2026",
        name="L",
        status="in_season",
    )
    db_session.add(league)
    await db_session.flush()

    team_a = Team(league_id=league.id, platform_roster_id="1", display_name="A")
    team_b = Team(league_id=league.id, platform_roster_id="2", display_name="B")
    db_session.add_all([team_a, team_b])
    await db_session.flush()

    matchup = Matchup(league_id=league.id, week=1, platform_matchup_id=10)
    db_session.add(matchup)
    await db_session.flush()

    db_session.add_all(
        [
            WeeklyScore(team_id=team_a.id, matchup_id=matchup.id, week=1, points=100),
            WeeklyScore(team_id=team_b.id, matchup_id=matchup.id, week=1, points=90),
        ]
    )
    await db_session.commit()

    df = await load_weekly_scores(db_session, league.id)

    assert len(df) == 2
    a_row = df[df["team_id"] == team_a.id].iloc[0]
    assert a_row["opponent_team_id"] == team_b.id
    assert a_row["points"] == 100
