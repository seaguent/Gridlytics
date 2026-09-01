import pytest

from app.analytics.loader import load_simulation_inputs
from app.models import League, Matchup, Team, WeeklyScore


@pytest.mark.asyncio
async def test_load_simulation_inputs_computes_records_and_score_distributions(db_session):
    league = League(
        platform="sleeper",
        platform_league_id="1",
        season="2026",
        name="L",
        status="in_season",
    )
    db_session.add(league)
    await db_session.flush()

    team_a = Team(league_id=league.id, platform_roster_id="1", display_name="A", wins=5, losses=3, points_for=500)
    team_b = Team(league_id=league.id, platform_roster_id="2", display_name="B", wins=2, losses=6, points_for=300)
    team_c = Team(league_id=league.id, platform_roster_id="3", display_name="C", wins=4, losses=4, points_for=400)
    db_session.add_all([team_a, team_b, team_c])
    await db_session.flush()

    matchup = Matchup(league_id=league.id, week=1, platform_matchup_id=10)
    db_session.add(matchup)
    await db_session.flush()

    db_session.add_all(
        [
            WeeklyScore(team_id=team_a.id, matchup_id=matchup.id, week=1, points=110),
            WeeklyScore(team_id=team_a.id, matchup_id=matchup.id, week=2, points=90),
            WeeklyScore(team_id=team_a.id, matchup_id=matchup.id, week=3, points=100),
            WeeklyScore(team_id=team_b.id, matchup_id=matchup.id, week=1, points=95),
        ]
    )
    await db_session.commit()

    current_records, team_score_dist = await load_simulation_inputs(db_session, league.id)

    assert current_records[team_a.id] == {"wins": 5, "losses": 3, "points_for": 500}

    # Team A has 3 real scores -> its own mean/std, not the league fallback.
    assert team_score_dist[team_a.id]["mean"] == pytest.approx(100.0)
    assert team_score_dist[team_a.id]["std"] == pytest.approx(10.0)

    # Team B has only 1 score -> std falls back to the league-wide std.
    assert team_score_dist[team_b.id]["mean"] == pytest.approx(95.0)
    assert team_score_dist[team_b.id]["std"] == pytest.approx(8.539, abs=0.01)

    # Team C has zero scores -> both mean and std fall back to league-wide values.
    assert team_score_dist[team_c.id]["mean"] == pytest.approx(98.75, abs=0.01)
    assert team_score_dist[team_c.id]["std"] == pytest.approx(8.539, abs=0.01)
