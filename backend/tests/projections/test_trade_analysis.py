import pytest

from app.analytics.lineup import find_optimal_lineup
from app.models import League, Player, ProjectionRecord, RosterSlot, Team
from app.projections.trade_analysis import InvalidTradeError, compute_trade_analysis, simulate_trade


def test_simulate_trade_removes_given_players_and_adds_received_ones():
    roster = [
        {"player_id": "wr_starter", "position": "WR", "points": 15.0},
        {"player_id": "weak_bench_wr", "position": "WR", "points": 2.0},
        {"player_id": "ok_bench_rb", "position": "RB", "points": 6.0},
    ]
    slots = ["WR", "RB"]
    receive = [{"player_id": "new_wr", "position": "WR", "points": 18.0}]

    current, projected = simulate_trade(roster, slots, give_player_ids={"weak_bench_wr"}, receive_candidates=receive)

    _, expected_current = find_optimal_lineup(roster, slots)
    hypothetical = [p for p in roster if p["player_id"] != "weak_bench_wr"] + receive
    _, expected_projected = find_optimal_lineup(hypothetical, slots)
    assert current == expected_current
    assert projected == expected_projected
    assert projected > current  # new_wr (18.0) beats weak_bench_wr's own (unused) bench slot


def test_simulate_trade_supports_giving_up_multiple_players_for_one():
    roster = [
        {"player_id": "rb_starter", "position": "RB", "points": 12.0},
        {"player_id": "bench_rb", "position": "RB", "points": 4.0},
        {"player_id": "bench_wr", "position": "WR", "points": 3.0},
    ]
    slots = ["RB", "WR"]
    receive = [{"player_id": "star_wr", "position": "WR", "points": 20.0}]

    current, projected = simulate_trade(
        roster, slots, give_player_ids={"bench_rb", "bench_wr"}, receive_candidates=receive
    )

    assert current == 15.0  # rb_starter (12.0) + bench_wr (3.0), the only two starters possible
    assert projected == 32.0  # rb_starter (12.0) + star_wr (20.0)


def test_simulate_trade_supports_receiving_multiple_players_for_one():
    roster = [
        {"player_id": "rb_starter", "position": "RB", "points": 12.0},
        {"player_id": "wr_starter", "position": "WR", "points": 10.0},
    ]
    slots = ["RB", "WR"]
    receive = [
        {"player_id": "new_rb", "position": "RB", "points": 14.0},
        {"player_id": "new_te", "position": "TE", "points": 9.0},
    ]

    current, projected = simulate_trade(roster, slots, give_player_ids={"rb_starter"}, receive_candidates=receive)

    assert current == 22.0
    assert projected == 24.0  # new_rb (14.0) + wr_starter (10.0); new_te has no eligible slot here


def test_simulate_trade_with_no_players_given_just_adds():
    roster = [{"player_id": "wr_starter", "position": "WR", "points": 10.0}]
    slots = ["WR"]
    receive = [{"player_id": "new_wr", "position": "WR", "points": 15.0}]

    current, projected = simulate_trade(roster, slots, give_player_ids=set(), receive_candidates=receive)

    assert current == 10.0
    _, expected = find_optimal_lineup(roster + receive, slots)
    assert projected == expected


async def _make_league_with_two_teams(db_session) -> tuple[League, Team, Team]:
    league = League(
        platform="sleeper", platform_league_id="1", season="2026", name="L", status="in_season",
        current_week=2, roster_positions=["WR", "RB", "BN"],
    )
    db_session.add(league)
    await db_session.flush()
    my_team = Team(league_id=league.id, platform_roster_id="1", display_name="My Team")
    other_team = Team(league_id=league.id, platform_roster_id="2", display_name="Their Team")
    db_session.add_all([my_team, other_team])
    await db_session.flush()
    return league, my_team, other_team


async def _add_player(db_session, league, team, pid, position, name, points):
    db_session.add(Player(platform=league.platform, platform_player_id=pid, position=position, name=name))
    db_session.add(RosterSlot(team_id=team.id, week=league.current_week, platform_player_id=pid, is_starter=True, points=0))
    db_session.add(
        ProjectionRecord(
            league_id=league.id, platform_player_id=pid, week=league.current_week, source=league.platform,
            name=name, position=position, projected_points=points,
        )
    )


@pytest.mark.asyncio
async def test_compute_trade_analysis_computes_real_deltas_for_both_sides(db_session):
    league, my_team, other_team = await _make_league_with_two_teams(db_session)
    await _add_player(db_session, league, my_team, "my_weak_wr", "WR", "My Weak WR", 3.0)
    await _add_player(db_session, league, other_team, "their_star_wr", "WR", "Their Star WR", 18.0)
    await db_session.commit()

    result = await compute_trade_analysis(
        db_session, league, my_team.id, other_team.id,
        give_player_ids=["my_weak_wr"], receive_player_ids=["their_star_wr"],
    )

    assert result["your_team"]["current_points"] == pytest.approx(3.0)
    assert result["your_team"]["projected_points"] == pytest.approx(18.0)
    assert result["your_team"]["delta"] == pytest.approx(15.0)
    assert result["other_team"]["current_points"] == pytest.approx(18.0)
    assert result["other_team"]["projected_points"] == pytest.approx(3.0)
    assert result["other_team"]["delta"] == pytest.approx(-15.0)
    assert len(result["your_team"]["reasons"]) > 0
    assert len(result["other_team"]["reasons"]) > 0


@pytest.mark.asyncio
async def test_compute_trade_analysis_rejects_both_sides_empty(db_session):
    league, my_team, other_team = await _make_league_with_two_teams(db_session)
    await db_session.commit()

    with pytest.raises(InvalidTradeError):
        await compute_trade_analysis(db_session, league, my_team.id, other_team.id, [], [])


@pytest.mark.asyncio
async def test_compute_trade_analysis_rejects_trading_with_yourself(db_session):
    league, my_team, _ = await _make_league_with_two_teams(db_session)
    await db_session.commit()

    with pytest.raises(InvalidTradeError):
        await compute_trade_analysis(db_session, league, my_team.id, my_team.id, ["x"], ["y"])


@pytest.mark.asyncio
async def test_compute_trade_analysis_rejects_team_not_in_league(db_session):
    league, my_team, _ = await _make_league_with_two_teams(db_session)
    await db_session.commit()

    with pytest.raises(InvalidTradeError):
        await compute_trade_analysis(db_session, league, my_team.id, 999999, ["x"], ["y"])


@pytest.mark.asyncio
async def test_compute_trade_analysis_rejects_player_not_on_the_claimed_roster(db_session):
    league, my_team, other_team = await _make_league_with_two_teams(db_session)
    await _add_player(db_session, league, other_team, "their_star_wr", "WR", "Their Star WR", 18.0)
    await db_session.commit()

    with pytest.raises(InvalidTradeError):
        await compute_trade_analysis(
            db_session, league, my_team.id, other_team.id,
            give_player_ids=["player_i_dont_have"], receive_player_ids=["their_star_wr"],
        )
