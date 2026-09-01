import pytest

from app.analytics.loader import load_power_ranking_inputs
from app.models import League, Matchup, Team, WeeklyScore


@pytest.mark.asyncio
async def test_load_power_ranking_inputs(db_session):
    league = League(platform="sleeper", platform_league_id="1", season="2026", name="L", status="in_season")
    db_session.add(league)
    await db_session.flush()

    team_a = Team(league_id=league.id, platform_roster_id="1", display_name="A", wins=2, losses=1, points_for=300)
    team_b = Team(league_id=league.id, platform_roster_id="2", display_name="B", wins=1, losses=2, points_for=270)
    db_session.add_all([team_a, team_b])
    await db_session.flush()

    matchups = [Matchup(league_id=league.id, week=w, platform_matchup_id=10) for w in (1, 2, 3)]
    db_session.add_all(matchups)
    await db_session.flush()

    scores = [
        (matchups[0], team_a, 100), (matchups[0], team_b, 90),
        (matchups[1], team_a, 110), (matchups[1], team_b, 80),
        (matchups[2], team_a, 90), (matchups[2], team_b, 100),
    ]
    db_session.add_all(
        [
            WeeklyScore(team_id=team.id, matchup_id=matchup.id, week=matchup.week, points=points)
            for matchup, team, points in scores
        ]
    )
    await db_session.commit()

    result = await load_power_ranking_inputs(db_session, league.id)

    a_row = result[result["team_id"] == team_a.id].iloc[0]
    b_row = result[result["team_id"] == team_b.id].iloc[0]

    assert a_row["win_pct"] == pytest.approx(2 / 3)
    assert a_row["points_per_game"] == pytest.approx(100.0)
    # Only 2 teams -> all-play expected wins equals actual wins each week.
    assert a_row["expected_win_pct"] == pytest.approx(2 / 3)
    assert a_row["recent_points_per_game"] == pytest.approx(100.0)

    assert b_row["win_pct"] == pytest.approx(1 / 3)
    assert b_row["points_per_game"] == pytest.approx(90.0)
