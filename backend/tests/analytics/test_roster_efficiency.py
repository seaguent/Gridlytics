import pytest

from app.analytics.roster import compute_roster_efficiency
from app.models import League, Matchup, Player, RosterSlot, Team, WeeklyScore


@pytest.mark.asyncio
async def test_compute_roster_efficiency_finds_a_better_lineup_than_what_was_started(db_session):
    league = League(
        platform="sleeper",
        platform_league_id="1",
        season="2026",
        name="L",
        status="in_season",
        roster_positions=["QB", "RB", "RB", "WR", "FLEX", "BN", "BN"],
    )
    db_session.add(league)
    await db_session.flush()

    team = Team(league_id=league.id, platform_roster_id="1", display_name="A")
    db_session.add(team)
    await db_session.flush()

    matchup = Matchup(league_id=league.id, week=1, platform_matchup_id=10)
    db_session.add(matchup)
    await db_session.flush()

    # Actual starters: QB1, RB1, RB2, WR1, TE1 (started in FLEX) = 20+15+10+12+8 = 65
    # WR2 (18 pts) sat on the bench all week -- worse than TE1 in the FLEX slot.
    db_session.add_all(
        [
            Player(platform="sleeper", platform_player_id="qb1", position="QB", name="QB1"),
            Player(platform="sleeper", platform_player_id="rb1", position="RB", name="RB1"),
            Player(platform="sleeper", platform_player_id="rb2", position="RB", name="RB2"),
            Player(platform="sleeper", platform_player_id="wr1", position="WR", name="WR1"),
            Player(platform="sleeper", platform_player_id="wr2", position="WR", name="WR2"),
            Player(platform="sleeper", platform_player_id="te1", position="TE", name="TE1"),
        ]
    )
    db_session.add_all(
        [
            RosterSlot(team_id=team.id, week=1, platform_player_id="qb1", is_starter=True, points=20),
            RosterSlot(team_id=team.id, week=1, platform_player_id="rb1", is_starter=True, points=15),
            RosterSlot(team_id=team.id, week=1, platform_player_id="rb2", is_starter=True, points=10),
            RosterSlot(team_id=team.id, week=1, platform_player_id="wr1", is_starter=True, points=12),
            RosterSlot(team_id=team.id, week=1, platform_player_id="te1", is_starter=True, points=8),
            RosterSlot(team_id=team.id, week=1, platform_player_id="wr2", is_starter=False, points=18),
        ]
    )
    db_session.add(WeeklyScore(team_id=team.id, matchup_id=matchup.id, week=1, points=65))
    await db_session.commit()

    result = await compute_roster_efficiency(db_session, league)

    row = result[(result["team_id"] == team.id) & (result["week"] == 1)].iloc[0]
    assert row["actual_points"] == 65
    # Optimal: QB1(20) + RB1(15) + RB2(10) + WR2(18) + FLEX=WR1(12) = 75
    assert row["optimal_points"] == 75
    assert row["efficiency"] == pytest.approx(65 / 75, abs=0.001)
