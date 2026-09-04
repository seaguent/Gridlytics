import httpx
import pandas as pd
import pytest
import respx

from app.analytics.lineup import find_optimal_lineup
from app.models import League, Player, ProjectionRecord, RosterSlot, Team
from app.nflverse.client import NFLVERSE_RELEASES_BASE_URL
from app.projections.trade_analysis import (
    InvalidTradeError,
    _teams_playing_by_week,
    compute_trade_analysis,
    simulate_trade,
)


def _mock_empty_schedule() -> None:
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/schedules/games.csv").mock(
        return_value=httpx.Response(200, text="season,week,home_team,away_team,gameday\n")
    )


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


def test_teams_playing_by_week_returns_home_and_away_teams_per_week():
    schedule = pd.DataFrame([
        {"season": 2026, "week": 1, "home_team": "SF", "away_team": "LA", "gameday": "2026-09-08"},
        {"season": 2026, "week": 1, "home_team": "KC", "away_team": "DEN", "gameday": "2026-09-08"},
        {"season": 2026, "week": 2, "home_team": "SF", "away_team": "KC", "gameday": "2026-09-15"},
    ])
    result = _teams_playing_by_week(schedule, [1, 2])
    assert result[1] == {"SF", "LA", "KC", "DEN"}
    assert result[2] == {"SF", "KC"}


def test_teams_playing_by_week_a_team_absent_that_week_is_on_bye():
    schedule = pd.DataFrame([
        {"season": 2026, "week": 5, "home_team": "SF", "away_team": "LA", "gameday": "2026-10-06"},
    ])
    result = _teams_playing_by_week(schedule, [5])
    assert "KC" not in result[5]  # KC has no game in week 5 -- on bye


def test_teams_playing_by_week_missing_week_returns_empty_set():
    schedule = pd.DataFrame([
        {"season": 2026, "week": 1, "home_team": "SF", "away_team": "LA", "gameday": "2026-09-08"},
    ])
    result = _teams_playing_by_week(schedule, [1, 99])
    assert result[99] == set()


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


async def _add_player(
    db_session, league, team, pid, position, name, points, is_starter=True,
    gridlytics_points=None, nfl_team=None,
):
    db_session.add(Player(platform=league.platform, platform_player_id=pid, position=position, name=name, team=nfl_team))
    db_session.add(
        RosterSlot(team_id=team.id, week=league.current_week, platform_player_id=pid, is_starter=is_starter, points=0)
    )
    db_session.add(
        ProjectionRecord(
            league_id=league.id, platform_player_id=pid, week=league.current_week, source=league.platform,
            name=name, position=position, projected_points=points,
        )
    )
    if gridlytics_points is not None:
        db_session.add(
            ProjectionRecord(
                league_id=league.id, platform_player_id=pid, week=league.current_week, source="gridlytics",
                name=name, position=position, projected_points=gridlytics_points,
            )
        )


@pytest.mark.asyncio
@respx.mock
async def test_compute_trade_analysis_computes_real_deltas_for_both_sides(db_session):
    league, my_team, other_team = await _make_league_with_two_teams(db_session)
    await _add_player(db_session, league, my_team, "my_weak_wr", "WR", "My Weak WR", 3.0)
    await _add_player(db_session, league, other_team, "their_star_wr", "WR", "Their Star WR", 18.0)
    await db_session.commit()
    _mock_empty_schedule()

    result = await compute_trade_analysis(
        db_session, league, my_team.id, other_team.id,
        give_player_ids=["my_weak_wr"], receive_player_ids=["their_star_wr"],
    )

    # No gridlytics_base seeded for either player -- neutral future-week candidates are empty,
    # so with an empty schedule (no bye data either) rest_of_season collapses to current_week
    # exactly, a legitimate degenerate case, not a bug.
    assert result["your_team"]["current_week_before"] == pytest.approx(3.0)
    assert result["your_team"]["current_week_after"] == pytest.approx(18.0)
    assert result["your_team"]["current_week_delta"] == pytest.approx(15.0)
    assert result["your_team"]["rest_of_season_before"] == pytest.approx(3.0)
    assert result["your_team"]["rest_of_season_after"] == pytest.approx(18.0)
    assert result["your_team"]["rest_of_season_delta"] == pytest.approx(15.0)
    assert result["other_team"]["current_week_before"] == pytest.approx(18.0)
    assert result["other_team"]["current_week_after"] == pytest.approx(3.0)
    assert result["other_team"]["current_week_delta"] == pytest.approx(-15.0)
    assert len(result["your_team"]["reasons"]) > 0
    assert len(result["other_team"]["reasons"]) > 0


async def _run_trade_with_lineup(db_session, suffix: str, suboptimal: bool) -> dict:
    """Same-shaped roster, same trade -- only which player is actually marked as_starter changes.
    current_starter (10.0) is the real optimal WR; bench_player (6.0) is worse. suboptimal=True
    marks the WORSE player as the actual starter (a real lineup-setting mistake); suboptimal=False
    marks the better one, matching what the optimizer would have picked anyway. suffix keeps
    player/team ids unique so both scenarios can run against the same db_session."""
    league, my_team, other_team = await _make_league_with_two_teams(db_session)
    league.roster_positions = ["WR", "BN"]
    await _add_player(
        db_session, league, my_team, f"current_starter_{suffix}", "WR", "Current Starter", 10.0,
        is_starter=not suboptimal,
    )
    await _add_player(
        db_session, league, my_team, f"bench_player_{suffix}", "WR", "Bench Player", 6.0,
        is_starter=suboptimal,
    )
    await _add_player(db_session, league, other_team, f"their_wr_{suffix}", "WR", "Their WR", 15.0)
    await db_session.commit()

    return await compute_trade_analysis(
        db_session, league, my_team.id, other_team.id,
        give_player_ids=[f"current_starter_{suffix}"], receive_player_ids=[f"their_wr_{suffix}"],
    )


@pytest.mark.asyncio
@respx.mock
async def test_compute_trade_analysis_delta_is_invariant_to_a_suboptimal_actual_lineup(db_session):
    """The core regression case: the trade delta must isolate the trade's own value. Whether the
    manager actually started their best player or not is a separate, real problem (Start/Sit
    already surfaces it) -- it must never change the reported trade delta."""
    _mock_empty_schedule()
    optimal_actual_lineup = await _run_trade_with_lineup(db_session, "a", suboptimal=False)
    suboptimal_actual_lineup = await _run_trade_with_lineup(db_session, "b", suboptimal=True)

    # Both before/after/delta are optimal-vs-optimal -- identical regardless of which player the
    # manager actually started.
    assert optimal_actual_lineup["your_team"]["current_week_before"] == pytest.approx(10.0)
    assert suboptimal_actual_lineup["your_team"]["current_week_before"] == pytest.approx(10.0)
    assert optimal_actual_lineup["your_team"]["current_week_after"] == pytest.approx(15.0)
    assert suboptimal_actual_lineup["your_team"]["current_week_after"] == pytest.approx(15.0)
    assert optimal_actual_lineup["your_team"]["current_week_delta"] == pytest.approx(5.0)
    assert suboptimal_actual_lineup["your_team"]["current_week_delta"] == pytest.approx(5.0)
    assert (
        optimal_actual_lineup["your_team"]["rest_of_season_delta"]
        == suboptimal_actual_lineup["your_team"]["rest_of_season_delta"]
    )

    # actual_current_starters_points IS allowed to differ -- it's real, separate context, never
    # fed into the delta above. This proves the two scenarios really were different (10.0 started
    # vs. 6.0 started), so the identical deltas above aren't a coincidence of a degenerate test.
    assert optimal_actual_lineup["your_team"]["actual_current_starters_points"] == pytest.approx(10.0)
    assert suboptimal_actual_lineup["your_team"]["actual_current_starters_points"] == pytest.approx(6.0)



@pytest.mark.asyncio
@respx.mock
async def test_compute_trade_analysis_rest_of_season_uses_neutral_rate_and_respects_byes(db_session):
    """The core fix: a player having a bad-matchup/low current-week number must NOT have that
    low number carried forward into future weeks -- future weeks use the matchup-neutral
    gridlytics_base rate instead, and exclude a player entirely in a week his real team is on
    bye (derived from the real schedule, not guessed)."""
    league = League(
        platform="sleeper", platform_league_id="1", season="2026", name="L", status="in_season",
        current_week=2, playoff_week_start=4, roster_positions=["RB", "BN"],
    )
    db_session.add(league)
    await db_session.flush()
    my_team = Team(league_id=league.id, platform_roster_id="1", display_name="My Team")
    other_team = Team(league_id=league.id, platform_roster_id="2", display_name="Their Team")
    db_session.add_all([my_team, other_team])
    await db_session.flush()

    # star_rb: a genuinely great player having a bad-matchup week (current-week blended = 5.0)
    # but a real neutral season-long rate of 15.0/week -- the fix must NOT carry the 5.0 forward.
    await _add_player(
        db_session, league, my_team, "star_rb", "RB", "Star RB", 5.0,
        is_starter=True, gridlytics_points=15.0, nfl_team="SF",
    )
    # their_rb: a plain, roughly-neutral player, same rate every week.
    await _add_player(
        db_session, league, other_team, "their_rb", "RB", "Their RB", 6.0,
        is_starter=True, gridlytics_points=6.0, nfl_team="KC",
    )
    await db_session.commit()

    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/schedules/games.csv").mock(
        return_value=httpx.Response(200, text=(
            "season,week,home_team,away_team,gameday\n"
            "2026,2,SF,LA,2026-09-15\n"
            "2026,2,KC,DEN,2026-09-15\n"
            "2026,3,KC,DEN,2026-09-22\n"  # SF has no game in week 3 -- SF is on bye
        ))
    )

    result = await compute_trade_analysis(
        db_session, league, my_team.id, other_team.id,
        give_player_ids=["star_rb"], receive_player_ids=["their_rb"],
    )

    # weeks = [2, 3] -- current_week=2, playoff_week_start=4 (exclusive) -> 2 weeks remaining
    assert result["weeks_remaining"] == 2

    your = result["your_team"]
    # Current week (week 2): real blend of platform (5.0) and gridlytics (15.0) = 10.0 -- "current
    # week" is still the normal 50/50 blend, exactly as it's always been. Losing that blended
    # 10.0 for a flat 6.0 looks like a bad trade THIS WEEK.
    assert your["current_week_before"] == pytest.approx(10.0)
    assert your["current_week_after"] == pytest.approx(6.0)  # their_rb (6.0) replaces star_rb
    assert your["current_week_delta"] == pytest.approx(-4.0)

    # Week 3 (future, neutral rate): star_rb's own bye zeroes his contribution to the BEFORE
    # total (proving byes are respected) -- his neutral 15.0 rate never even needs to apply that
    # week. their_rb (6.0 neutral, KC plays week 3) drives AFTER. The season-long picture (+2.0)
    # is the opposite sign of the current-week-alone picture (-4.0) -- exactly the failure mode
    # this fix exists to prevent.
    assert your["rest_of_season_before"] == pytest.approx(10.0)  # 10.0 (wk2) + 0.0 (wk3, star_rb bye)
    assert your["rest_of_season_after"] == pytest.approx(12.0)  # 6.0 (wk2) + 6.0 (wk3)
    assert your["rest_of_season_delta"] == pytest.approx(2.0)

    their = result["other_team"]
    assert their["current_week_before"] == pytest.approx(6.0)
    assert their["current_week_after"] == pytest.approx(10.0)  # star_rb (10.0 blended) replaces their_rb
    assert their["rest_of_season_before"] == pytest.approx(12.0)  # 6.0 (wk2) + 6.0 (wk3)
    # Week 3 after: they'd have star_rb, but he's on bye that week too -- 0 contribution.
    assert their["rest_of_season_after"] == pytest.approx(10.0)  # 10.0 (wk2) + 0.0 (wk3, star_rb bye)
    assert their["rest_of_season_delta"] == pytest.approx(-2.0)


@pytest.mark.asyncio
@respx.mock
async def test_compute_trade_analysis_includes_kicker_and_defense_in_roster_totals(db_session):
    """POSITION_CATEGORIES (QB/RB/WR/TE only) governs whether a context-aware gridlytics_base
    gets attempted -- it must never gate whether a player counts toward the roster at all. K/DEF
    have no rate model, but still contribute their real platform projection, exactly like
    Start/Sit and Rankings already treat them."""
    league, my_team, other_team = await _make_league_with_two_teams(db_session)
    league.roster_positions = ["WR", "K", "DEF", "BN"]
    await _add_player(db_session, league, my_team, "my_wr", "WR", "My WR", 10.0)
    await _add_player(db_session, league, my_team, "my_k", "K", "My Kicker", 8.0)
    await _add_player(db_session, league, my_team, "my_def", "DEF", "My Defense", 7.0)
    await _add_player(db_session, league, other_team, "their_wr", "WR", "Their WR", 5.0)
    await db_session.commit()
    _mock_empty_schedule()

    result = await compute_trade_analysis(
        db_session, league, my_team.id, other_team.id,
        give_player_ids=[], receive_player_ids=["their_wr"],
    )

    # 10.0 (WR) + 8.0 (K) + 7.0 (DEF) = 25.0 -- K/DEF must not be silently dropped.
    assert result["your_team"]["current_week_before"] == pytest.approx(25.0)


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
