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


@pytest.mark.asyncio
async def test_load_weekly_scores_dedupes_a_team_with_two_matchups_in_the_same_week(db_session):
    # A leftover duplicate Matchup row for the same real week (e.g. from the concurrency bug
    # that existed before the per-league sync lock) must not double-count a team's score.
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

    matchup_1 = Matchup(league_id=league.id, week=1, platform_matchup_id=10)
    matchup_2 = Matchup(league_id=league.id, week=1, platform_matchup_id=10)
    db_session.add_all([matchup_1, matchup_2])
    await db_session.flush()

    db_session.add_all(
        [
            WeeklyScore(team_id=team_a.id, matchup_id=matchup_1.id, week=1, points=100),
            WeeklyScore(team_id=team_b.id, matchup_id=matchup_1.id, week=1, points=90),
            WeeklyScore(team_id=team_a.id, matchup_id=matchup_2.id, week=1, points=100),
            WeeklyScore(team_id=team_b.id, matchup_id=matchup_2.id, week=1, points=90),
        ]
    )
    await db_session.commit()

    df = await load_weekly_scores(db_session, league.id)

    # One row per team per real week, not one per (team, matchup) row.
    assert len(df) == 2
    assert sorted(df["team_id"].tolist()) == sorted([team_a.id, team_b.id])


@pytest.mark.asyncio
async def test_load_weekly_scores_excludes_weeks_not_yet_played(db_session):
    # A league has WeeklyScore rows synced for its full scheduled season up front, including
    # weeks that haven't happened yet -- before_week must exclude those.
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

    matchup_week1 = Matchup(league_id=league.id, week=1, platform_matchup_id=10)
    matchup_week6 = Matchup(league_id=league.id, week=6, platform_matchup_id=11)
    db_session.add_all([matchup_week1, matchup_week6])
    await db_session.flush()

    db_session.add_all(
        [
            WeeklyScore(team_id=team_a.id, matchup_id=matchup_week1.id, week=1, points=100),
            WeeklyScore(team_id=team_b.id, matchup_id=matchup_week1.id, week=1, points=90),
            # Week 6 hasn't been played yet (league is currently on week 6) but already has rows.
            WeeklyScore(team_id=team_a.id, matchup_id=matchup_week6.id, week=6, points=0),
            WeeklyScore(team_id=team_b.id, matchup_id=matchup_week6.id, week=6, points=0),
        ]
    )
    await db_session.commit()

    df = await load_weekly_scores(db_session, league.id, before_week=6)

    assert sorted(df["week"].unique().tolist()) == [1]
