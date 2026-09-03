import httpx
import pytest
import respx
from sqlalchemy import select

from app.analytics.lineup import find_optimal_lineup
from app.models import League, LeagueConnection, Player, ProjectionRecord, RosterSlot, Team
from app.nflverse.client import NFLVERSE_RELEASES_BASE_URL
from app.projections.available_players import AvailablePlayerCandidate, EspnAuthError
from app.projections.context_aware.depth_chart import RoleInfo
from app.projections.waivers import (
    TOP_N_PER_POSITION,
    compute_waiver_recommendations,
    rank_and_narrow_candidates,
    simulate_best_transaction,
)
from app.sleeper.client import SLEEPER_BASE_URL, SLEEPER_PROJECTIONS_BASE_URL

ESPN_FREE_AGENT_CROSSWALK_HEADER = "gsis_id,display_name,espn_id,pfr_id,position\n"


def _mock_empty_nflverse_history(season: str) -> None:
    for offset in range(0, 5):
        year = str(int(season) - offset)
        respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_{year}.csv").mock(
            return_value=httpx.Response(404)
        )
        respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_reg_{year}.csv").mock(
            return_value=httpx.Response(404)
        )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/depth_charts/depth_charts_{season}.csv").mock(
        return_value=httpx.Response(404)
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/schedules/games.csv").mock(
        return_value=httpx.Response(200, text="season,week,home_team,away_team,gameday\n")
    )


def _wr(pid, gsis, projection=None):
    return AvailablePlayerCandidate(
        platform_player_id=pid, gsis_id=gsis, name=pid, position="WR", team="KC",
        injury_status=None, platform_projection=projection,
    )


def test_rank_and_narrow_drops_candidates_with_no_real_signal():
    candidates = [_wr("no_signal", "g1")]
    result = rank_and_narrow_candidates(candidates, recent_usage_by_gsis={}, roles_by_gsis_position={})
    assert result == []


def test_rank_and_narrow_keeps_candidate_with_platform_projection_only():
    candidates = [_wr("has_proj", "g1", projection=7.0)]
    result = rank_and_narrow_candidates(candidates, recent_usage_by_gsis={}, roles_by_gsis_position={})
    assert [c.platform_player_id for c in result] == ["has_proj"]


def test_rank_and_narrow_keeps_zero_usage_rookie_with_real_depth_chart_role():
    candidates = [_wr("rookie_starter", "g1")]
    roles = {("g1", "WR"): RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)}
    result = rank_and_narrow_candidates(candidates, recent_usage_by_gsis={}, roles_by_gsis_position=roles)
    assert [c.platform_player_id for c in result] == ["rookie_starter"]


def test_rank_and_narrow_drops_deep_bench_depth_chart_role():
    candidates = [_wr("wr5", "g1")]
    roles = {("g1", "WR"): RoleInfo(pos_rank=5, role_confidence="high", role_changed_recently=False)}
    result = rank_and_narrow_candidates(candidates, recent_usage_by_gsis={}, roles_by_gsis_position=roles)
    assert result == []


def test_rank_and_narrow_gsis_id_alone_is_not_a_signal():
    candidates = [_wr("has_gsis_only", "g1")]
    result = rank_and_narrow_candidates(candidates, recent_usage_by_gsis={}, roles_by_gsis_position={})
    assert result == []


def test_rank_and_narrow_caps_at_top_n_per_position_by_platform_projection():
    candidates = [_wr(f"wr{i}", f"g{i}", projection=float(i)) for i in range(TOP_N_PER_POSITION + 5)]
    result = rank_and_narrow_candidates(candidates, recent_usage_by_gsis={}, roles_by_gsis_position={})
    assert len(result) == TOP_N_PER_POSITION
    kept_ids = {c.platform_player_id for c in result}
    assert "wr19" in kept_ids
    assert "wr0" not in kept_ids


def test_rank_and_narrow_uses_recent_usage_as_fallback_rank_key():
    candidates = [_wr("low_usage", "g1"), _wr("high_usage", "g2")]
    usage = {"g1": 1.0, "g2": 9.0}
    result = rank_and_narrow_candidates(candidates, recent_usage_by_gsis=usage, roles_by_gsis_position={})
    assert [c.platform_player_id for c in result] == ["high_usage", "low_usage"]


def test_simulate_best_transaction_picks_the_drop_with_the_highest_improvement():
    roster = [
        {"player_id": "wr_starter", "position": "WR", "points": 15.0},
        {"player_id": "weak_bench_wr", "position": "WR", "points": 2.0},
        {"player_id": "ok_bench_rb", "position": "RB", "points": 6.0},
    ]
    slots = ["WR"]
    assignment, current_points = find_optimal_lineup(roster, slots)
    candidate = {"player_id": "new_wr", "position": "WR", "points": 18.0}
    names = {"weak_bench_wr": "Weak Bench WR", "ok_bench_rb": "OK Bench RB"}

    result = simulate_best_transaction(roster, current_points, assignment, slots, candidate, names)

    assert result is not None
    assert result.candidate_player_id == "new_wr"
    assert result.improvement == pytest.approx(3.0)
    assert result.drop_player_id in {"weak_bench_wr", "ok_bench_rb"}


def test_simulate_best_transaction_returns_none_when_roster_has_no_bench():
    roster = [{"player_id": "only_wr", "position": "WR", "points": 15.0}]
    slots = ["WR"]
    assignment, current_points = find_optimal_lineup(roster, slots)
    candidate = {"player_id": "new_wr", "position": "WR", "points": 18.0}

    result = simulate_best_transaction(roster, current_points, assignment, slots, candidate, {})

    assert result is None


def test_simulate_best_transaction_prefers_same_position_bench_when_improvement_ties():
    roster = [
        {"player_id": "wr_starter", "position": "WR", "points": 15.0},
        {"player_id": "bench_wr", "position": "WR", "points": 5.0},
        {"player_id": "bench_te", "position": "TE", "points": 5.0},
    ]
    slots = ["WR"]
    assignment, current_points = find_optimal_lineup(roster, slots)
    candidate = {"player_id": "new_wr", "position": "WR", "points": 10.0}
    names = {"bench_wr": "Bench WR", "bench_te": "Bench TE"}

    result = simulate_best_transaction(roster, current_points, assignment, slots, candidate, names)

    assert result.drop_player_id == "bench_wr"


@pytest.mark.asyncio
async def test_compute_waiver_recommendations_returns_unsupported_for_unknown_platform(db_session):
    league = League(
        platform="yahoo", platform_league_id="1", season="2026", name="L", status="in_season",
        current_week=2, roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN"],
    )
    connection = LeagueConnection(league_id=0, access_token_hash="x", my_team_id=None)

    result = await compute_waiver_recommendations(db_session, league, connection)

    assert result == {"mode": "unsupported_platform", "recommendations": []}


@pytest.mark.asyncio
async def test_compute_waiver_recommendations_raises_auth_error_for_espn_without_raw_data(db_session):
    league = League(
        platform="espn", platform_league_id="1", season="2026", name="L", status="in_season",
        current_week=2, roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN"],
    )
    connection = LeagueConnection(league_id=0, access_token_hash="x", my_team_id=None)

    with pytest.raises(EspnAuthError):
        await compute_waiver_recommendations(db_session, league, connection, raw_free_agents_data=None)


@pytest.mark.asyncio
@respx.mock
async def test_compute_waiver_recommendations_falls_back_to_projection_only_with_no_team(db_session):
    league = League(
        platform="sleeper", platform_league_id="123", season="2026", name="L", status="in_season",
        current_week=2, roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN"],
        scoring_settings={"rec": 1.0},
    )
    connection = LeagueConnection(league_id=0, access_token_hash="x", my_team_id=None)

    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(
        return_value=httpx.Response(
            200,
            json={"fa1": {"position": "WR", "full_name": "Free Agent WR", "gsis_id": "00-100", "team": "KC"}},
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/123/rosters").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{SLEEPER_PROJECTIONS_BASE_URL}/2026/2").mock(
        return_value=httpx.Response(
            200,
            json=[{"player_id": "fa1", "week": 2, "stats": {"pts_ppr": 9.5},
                   "player": {"first_name": "Free", "last_name": "Agent", "position": "WR"}}],
        )
    )
    _mock_empty_nflverse_history("2026")

    result = await compute_waiver_recommendations(db_session, league, connection)

    assert result["mode"] == "projection_only"
    assert len(result["recommendations"]) == 1
    row = result["recommendations"][0]
    assert row["platform_player_id"] == "fa1"
    assert row["projected_lineup_improvement"] is None
    assert row["replaces_player_id"] is None
    assert row["platform_projection"] == pytest.approx(9.5)


@pytest.mark.asyncio
@respx.mock
async def test_compute_waiver_recommendations_runs_lineup_comparison_when_team_selected(db_session):
    league = League(
        platform="sleeper", platform_league_id="123", season="2026", name="L", status="in_season",
        current_week=2, roster_positions=["WR", "BN"], scoring_settings={"rec": 1.0},
    )
    db_session.add(league)
    await db_session.flush()
    team = Team(league_id=league.id, platform_roster_id="1", display_name="My Team")
    db_session.add(team)
    await db_session.flush()
    connection = LeagueConnection(league_id=league.id, access_token_hash="x", my_team_id=team.id)

    # A real roster needs a genuine bench player for the "no legal drop exists" edge case not
    # to swallow this test -- weak_wr starts (the only WR-eligible candidate), bench_filler is a
    # real RB who can never win the WR-only slot, so they're always bench, giving the simulation
    # a real player to drop.
    db_session.add_all([
        Player(platform="sleeper", platform_player_id="weak_wr", position="WR", name="Weak WR"),
        Player(platform="sleeper", platform_player_id="bench_filler", position="RB", name="Bench Filler"),
    ])
    db_session.add_all([
        RosterSlot(team_id=team.id, week=2, platform_player_id="weak_wr", is_starter=True, points=0),
        RosterSlot(team_id=team.id, week=2, platform_player_id="bench_filler", is_starter=False, points=0),
    ])
    db_session.add_all([
        ProjectionRecord(league_id=league.id, platform_player_id="weak_wr", week=2, source="sleeper",
                          name="Weak WR", position="WR", projected_points=3.0),
        ProjectionRecord(league_id=league.id, platform_player_id="bench_filler", week=2, source="sleeper",
                          name="Bench Filler", position="RB", projected_points=1.0),
    ])
    await db_session.commit()

    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(
        return_value=httpx.Response(
            200,
            json={"fa1": {"position": "WR", "full_name": "Better WR", "gsis_id": "00-100", "team": "KC"}},
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/123/rosters").mock(
        return_value=httpx.Response(
            200,
            json=[{"roster_id": 1, "league_id": "123", "players": ["weak_wr", "bench_filler"], "settings": {}}],
        )
    )
    respx.get(f"{SLEEPER_PROJECTIONS_BASE_URL}/2026/2").mock(
        return_value=httpx.Response(
            200,
            json=[{"player_id": "fa1", "week": 2, "stats": {"pts_ppr": 18.0},
                   "player": {"first_name": "Better", "last_name": "WR", "position": "WR"}}],
        )
    )
    _mock_empty_nflverse_history("2026")

    result = await compute_waiver_recommendations(db_session, league, connection)

    assert result["mode"] == "lineup_comparison"
    assert len(result["recommendations"]) == 1
    row = result["recommendations"][0]
    assert row["platform_player_id"] == "fa1"
    # fa1 (18.0) beats weak_wr (3.0) for the sole WR slot -- current_optimal_points=3.0,
    # new_optimal_points=18.0. bench_filler (an RB, never WR-slot-eligible here) is the real
    # roster cut that makes room; weak_wr is naturally bumped to bench by the optimizer as a
    # side effect, not because weak_wr itself was the chosen drop.
    assert row["projected_lineup_improvement"] == pytest.approx(15.0)
    assert row["replaces_player_id"] == "bench_filler"
    assert row["replaces_name"] == "Bench Filler"


@pytest.mark.asyncio
@respx.mock
async def test_compute_waiver_recommendations_runs_lineup_comparison_for_espn_league(db_session):
    """Proves the ESPN free-agent pool flows through the exact same rank/score/simulate engine
    Sleeper uses -- only the candidate source (EspnAvailablePlayerProvider vs.
    SleeperAvailablePlayerProvider) differs."""
    league = League(
        platform="espn", platform_league_id="1", season="2026", name="L", status="in_season",
        current_week=2, roster_positions=["WR", "BN"],
    )
    db_session.add(league)
    await db_session.flush()
    team = Team(league_id=league.id, platform_roster_id="1", display_name="My Team")
    db_session.add(team)
    await db_session.flush()
    connection = LeagueConnection(league_id=league.id, access_token_hash="x", my_team_id=team.id)

    db_session.add_all([
        Player(platform="espn", platform_player_id="weak_wr", position="WR", name="Weak WR"),
        Player(platform="espn", platform_player_id="bench_filler", position="RB", name="Bench Filler"),
    ])
    db_session.add_all([
        RosterSlot(team_id=team.id, week=2, platform_player_id="weak_wr", is_starter=True, points=0),
        RosterSlot(team_id=team.id, week=2, platform_player_id="bench_filler", is_starter=False, points=0),
    ])
    db_session.add_all([
        ProjectionRecord(league_id=league.id, platform_player_id="weak_wr", week=2, source="espn",
                          name="Weak WR", position="WR", projected_points=3.0),
        ProjectionRecord(league_id=league.id, platform_player_id="bench_filler", week=2, source="espn",
                          name="Bench Filler", position="RB", projected_points=1.0),
    ])
    await db_session.commit()

    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/players/players.csv").mock(
        return_value=httpx.Response(200, text=ESPN_FREE_AGENT_CROSSWALK_HEADER)
    )
    _mock_empty_nflverse_history("2026")

    raw_free_agents_data = {
        "players": [
            {
                "id": 555,
                "onTeamId": 0,
                "player": {
                    "fullName": "Better WR",
                    "defaultPositionId": 3,
                    "proTeamId": 12,
                    "injuryStatus": None,
                    "stats": [{"scoringPeriodId": 2, "statSourceId": 1, "appliedTotal": 18.0}],
                },
            }
        ]
    }

    result = await compute_waiver_recommendations(db_session, league, connection, raw_free_agents_data)

    assert result["mode"] == "lineup_comparison"
    assert len(result["recommendations"]) == 1
    row = result["recommendations"][0]
    assert row["platform_player_id"] == "555"
    assert row["name"] == "Better WR"
    assert row["projected_lineup_improvement"] == pytest.approx(15.0)
    assert row["replaces_player_id"] == "bench_filler"
    assert row["replaces_name"] == "Bench Filler"


@pytest.mark.asyncio
@respx.mock
async def test_waiver_recommendation_shape_matches_between_sleeper_and_espn(db_session):
    sleeper_league = League(
        platform="sleeper", platform_league_id="123", season="2026", name="L", status="in_season",
        current_week=2, roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN"],
        scoring_settings={"rec": 1.0},
    )
    sleeper_connection = LeagueConnection(league_id=0, access_token_hash="x", my_team_id=None)

    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(
        return_value=httpx.Response(
            200,
            json={"fa1": {"position": "WR", "full_name": "Free Agent WR", "gsis_id": "00-100", "team": "KC"}},
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/123/rosters").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{SLEEPER_PROJECTIONS_BASE_URL}/2026/2").mock(
        return_value=httpx.Response(
            200,
            json=[{"player_id": "fa1", "week": 2, "stats": {"pts_ppr": 9.5},
                   "player": {"first_name": "Free", "last_name": "Agent", "position": "WR"}}],
        )
    )
    _mock_empty_nflverse_history("2026")

    sleeper_result = await compute_waiver_recommendations(db_session, sleeper_league, sleeper_connection)

    espn_league = League(
        platform="espn", platform_league_id="1", season="2026", name="L", status="in_season",
        current_week=2, roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN"],
    )
    espn_connection = LeagueConnection(league_id=0, access_token_hash="y", my_team_id=None)

    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/players/players.csv").mock(
        return_value=httpx.Response(200, text=ESPN_FREE_AGENT_CROSSWALK_HEADER)
    )
    _mock_empty_nflverse_history("2026")

    raw_free_agents_data = {
        "players": [
            {
                "id": 555,
                "onTeamId": 0,
                "player": {
                    "fullName": "Free Agent WR",
                    "defaultPositionId": 3,
                    "proTeamId": 12,
                    "injuryStatus": None,
                    "stats": [{"scoringPeriodId": 2, "statSourceId": 1, "appliedTotal": 9.5}],
                },
            }
        ]
    }
    espn_result = await compute_waiver_recommendations(
        db_session, espn_league, espn_connection, raw_free_agents_data
    )

    assert sleeper_result["mode"] == espn_result["mode"] == "projection_only"
    assert len(sleeper_result["recommendations"]) == 1
    assert len(espn_result["recommendations"]) == 1
    assert set(sleeper_result["recommendations"][0].keys()) == set(espn_result["recommendations"][0].keys())


@pytest.mark.asyncio
@respx.mock
async def test_free_agent_rb2_effective_role_promotion_when_rostered_rb1_ruled_out(db_session):
    """Real, DB-backed proof the effective-role mechanism reuses cleanly for Waivers free-agent
    candidates: RB2 is a free agent (not rostered by anyone), SF's real depth-chart rank-2 back.
    RB1 is SF's rostered rank-1 starter. A KC backup exists purely to seed a real (diluted) rank-2
    share prior so both runs resolve through the context-aware model. Only RB1's injury_status
    changes between the two calls."""
    league = League(
        platform="sleeper", platform_league_id="123", season="2026", name="L", status="in_season",
        current_week=2, roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN"],
        scoring_settings={"rec": 1.0},
    )
    connection = LeagueConnection(league_id=0, access_token_hash="x", my_team_id=None)

    db_session.add(
        Player(platform="sleeper", platform_player_id="rb1_sleeper_id", position="RB", name="RB One",
               gsis_id="00-1111", team="SF", injury_status=None)
    )
    await db_session.commit()

    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(
        return_value=httpx.Response(
            200,
            json={
                "rb1_sleeper_id": {"position": "RB", "full_name": "RB One", "gsis_id": "00-1111", "team": "SF"},
                "rb2_sleeper_id": {"position": "RB", "full_name": "RB Two", "gsis_id": "00-2222", "team": "SF"},
            },
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/123/rosters").mock(
        return_value=httpx.Response(
            200,
            json=[{"roster_id": 1, "league_id": "123", "players": ["rb1_sleeper_id"], "settings": {}}],
        )
    )
    respx.get(f"{SLEEPER_PROJECTIONS_BASE_URL}/2026/2").mock(return_value=httpx.Response(200, json=[]))

    # KC starter dilutes the KC backup's own share down to a realistic ~10%, well below RB1's
    # real ~67% share -- otherwise the backup would be KC's only ball-carrier that week (share=1.0),
    # an artificially high "rank 2" prior that would invert the direction of this whole test
    # (see the identical fix applied to the rostered-player sync.py integration test).
    weekly_stats_csv = (
        "player_id,player_display_name,position,season,season_type,week,targets,target_share,carries,"
        "team,opponent_team,fantasy_points_ppr,receiving_yards,receiving_tds,receptions,rushing_yards,"
        "rushing_tds,attempts,passing_yards,passing_tds,passing_interceptions\n"
        "00-1111,RB One,RB,2026,REG,1,0,0.0,4,SF,LA,15.0,0,0,0,25,1,0,0,0,0\n"
        "00-9998,SF QB,QB,2026,REG,1,0,0.0,2,SF,LA,14.0,0,0,0,4,0,28,190,1,0\n"
        "00-8888,KC Backup RB,RB,2026,REG,1,0,0.0,2,KC,DEN,3.0,0,0,0,8,0,0,0,0,0\n"
        "00-8889,KC Starter RB,RB,2026,REG,1,0,0.0,18,KC,DEN,20.0,0,0,0,90,1,0,0,0,0\n"
    )
    depth_charts_csv = (
        "dt,team,gsis_id,pos_abb,pos_rank\n"
        "2026-08-01T00:00:00Z,SF,00-1111,RB,1\n"
        "2026-08-01T00:00:00Z,SF,00-2222,RB,2\n"
        "2026-08-01T00:00:00Z,KC,00-8888,RB,2\n"
    )
    schedule_csv = "season,week,home_team,away_team,gameday\n2026,1,LA,SF,2026-09-08\n2026,2,LA,SEA,2026-09-15\n"

    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_2026.csv").mock(
        return_value=httpx.Response(200, text=weekly_stats_csv)
    )
    for offset in range(1, 5):
        year = str(2026 - offset)
        respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_{year}.csv").mock(
            return_value=httpx.Response(404)
        )
        respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_reg_{year}.csv").mock(
            return_value=httpx.Response(404)
        )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/depth_charts/depth_charts_2026.csv").mock(
        return_value=httpx.Response(200, text=depth_charts_csv)
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/schedules/games.csv").mock(
        return_value=httpx.Response(200, text=schedule_csv)
    )

    # Scenario A: RB1 healthy.
    result_healthy = await compute_waiver_recommendations(db_session, league, connection)
    row_healthy = next(r for r in result_healthy["recommendations"] if r["platform_player_id"] == "rb2_sleeper_id")
    assert row_healthy["gridlytics_base_projection"] is not None  # context-aware resolved, not skipped

    # Scenario B: RB1 ruled OUT. Nothing else changes -- same weekly stats, same depth chart.
    result = await db_session.execute(
        select(Player).where(Player.platform == "sleeper", Player.platform_player_id == "rb1_sleeper_id")
    )
    rb1 = result.scalar_one()
    rb1.injury_status = "OUT"
    await db_session.commit()

    result_out = await compute_waiver_recommendations(db_session, league, connection)
    row_out = next(r for r in result_out["recommendations"] if r["platform_player_id"] == "rb2_sleeper_id")
    assert row_out["gridlytics_base_projection"] is not None

    # The only real-world fact that changed between the two calls is RB1's injury_status.
    assert row_out["gridlytics_base_projection"] > row_healthy["gridlytics_base_projection"]


def _espn_effective_role_league() -> League:
    return League(
        platform="espn", platform_league_id="1", season="2026", name="L", status="in_season",
        current_week=2, roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN"],
    )


def _espn_effective_role_crosswalk_csv() -> str:
    return (
        "gsis_id,display_name,espn_id,pfr_id,position\n"
        "00-3111,RB One,111,RBOne00,RB\n"
        "00-3222,RB Two,222,RBTwo00,RB\n"
    )


def _espn_effective_role_weekly_stats_csv() -> str:
    # KC starter dilutes the KC backup's own share down to a realistic ~10% -- the same fix
    # applied to the Sleeper and sync.py effective-role fixtures, for the same reason: an
    # undiluted lone ball-carrier would give "rank 2" an artificially high share prior.
    return (
        "player_id,player_display_name,position,season,season_type,week,targets,target_share,carries,"
        "team,opponent_team,fantasy_points_ppr,receiving_yards,receiving_tds,receptions,rushing_yards,"
        "rushing_tds,attempts,passing_yards,passing_tds,passing_interceptions\n"
        "00-3111,RB One,RB,2026,REG,1,0,0.0,4,SF,LA,15.0,0,0,0,25,1,0,0,0,0\n"
        "00-9997,SF QB,QB,2026,REG,1,0,0.0,2,SF,LA,14.0,0,0,0,4,0,28,190,1,0\n"
        "00-3888,KC Backup RB,RB,2026,REG,1,0,0.0,2,KC,DEN,3.0,0,0,0,8,0,0,0,0,0\n"
        "00-3889,KC Starter RB,RB,2026,REG,1,0,0.0,18,KC,DEN,20.0,0,0,0,90,1,0,0,0,0\n"
    )


def _espn_effective_role_depth_charts_csv() -> str:
    return (
        "dt,team,gsis_id,pos_abb,pos_rank\n"
        "2026-08-01T00:00:00Z,SF,00-3111,RB,1\n"
        "2026-08-01T00:00:00Z,SF,00-3222,RB,2\n"
        "2026-08-01T00:00:00Z,KC,00-3888,RB,2\n"
    )


def _espn_effective_role_schedule_csv() -> str:
    return "season,week,home_team,away_team,gameday\n2026,1,LA,SF,2026-09-08\n2026,2,LA,SEA,2026-09-15\n"


def _mock_espn_effective_role_nflverse():
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_2026.csv").mock(
        return_value=httpx.Response(200, text=_espn_effective_role_weekly_stats_csv())
    )
    for offset in range(1, 5):
        year = str(2026 - offset)
        respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_{year}.csv").mock(
            return_value=httpx.Response(404)
        )
        respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_reg_{year}.csv").mock(
            return_value=httpx.Response(404)
        )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/depth_charts/depth_charts_2026.csv").mock(
        return_value=httpx.Response(200, text=_espn_effective_role_depth_charts_csv())
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/schedules/games.csv").mock(
        return_value=httpx.Response(200, text=_espn_effective_role_schedule_csv())
    )


def _espn_rb2_free_agent_payload() -> dict:
    return {
        "players": [
            {
                "id": 222,
                "onTeamId": 0,
                "player": {
                    "fullName": "RB Two",
                    "defaultPositionId": 2,
                    "proTeamId": 25,
                    "injuryStatus": None,
                    "stats": [],
                },
            }
        ]
    }


@pytest.mark.asyncio
@respx.mock
async def test_espn_free_agent_rb2_effective_role_promotion_when_rostered_rb1_ruled_out(db_session):
    """ESPN equivalent of the Sleeper injury-aware effective-role waiver test above. RB1 (ESPN id
    111) is SF's rostered rank-1 starter -- a real Player row from this league's normal roster
    sync, no gsis_id column (ESPN never persists one). RB2 (ESPN id 222) is a free agent, SF's
    real rank-2 backup. The crosswalk compute_waiver_recommendations now builds once is what lets
    it resolve both RB2's own identity AND RB1's gsis_id for the teammate-availability lookup --
    this is the exact gap that was closed."""
    league = _espn_effective_role_league()
    connection = LeagueConnection(league_id=0, access_token_hash="x", my_team_id=None)

    db_session.add(
        Player(platform="espn", platform_player_id="111", position="RB", name="RB One",
               team="SF", injury_status=None)
    )
    await db_session.commit()

    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/players/players.csv").mock(
        return_value=httpx.Response(200, text=_espn_effective_role_crosswalk_csv())
    )
    _mock_espn_effective_role_nflverse()
    raw_free_agents_data = _espn_rb2_free_agent_payload()

    # Scenario A: RB1 healthy. RB2 stays at its real depth-chart rank (2).
    result_healthy = await compute_waiver_recommendations(db_session, league, connection, raw_free_agents_data)
    row_healthy = next(r for r in result_healthy["recommendations"] if r["platform_player_id"] == "222")
    assert row_healthy["gridlytics_base_projection"] is not None  # context-aware resolved, not skipped

    # Scenario B: RB1 ruled OUT. Nothing else changes -- same weekly stats, same depth chart.
    result = await db_session.execute(
        select(Player).where(Player.platform == "espn", Player.platform_player_id == "111")
    )
    rb1 = result.scalar_one()
    rb1.injury_status = "OUT"
    await db_session.commit()

    result_out = await compute_waiver_recommendations(db_session, league, connection, raw_free_agents_data)
    row_out = next(r for r in result_out["recommendations"] if r["platform_player_id"] == "222")
    assert row_out["gridlytics_base_projection"] is not None

    # The only real-world fact that changed between the two calls is RB1's injury_status.
    assert row_out["gridlytics_base_projection"] > row_healthy["gridlytics_base_projection"]


@pytest.mark.asyncio
@respx.mock
async def test_espn_waiver_request_loads_the_crosswalk_exactly_once(db_session):
    """Regression test for the refactor itself: compute_waiver_recommendations must reuse the
    SAME crosswalk load for both the free-agent provider and the teammate-availability lookup,
    never fetching /players.csv a second time in the same request."""
    league = _espn_effective_role_league()
    connection = LeagueConnection(league_id=0, access_token_hash="x", my_team_id=None)

    db_session.add(
        Player(platform="espn", platform_player_id="111", position="RB", name="RB One",
               team="SF", injury_status="OUT")
    )
    await db_session.commit()

    crosswalk_route = respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/players/players.csv").mock(
        return_value=httpx.Response(200, text=_espn_effective_role_crosswalk_csv())
    )
    _mock_espn_effective_role_nflverse()

    await compute_waiver_recommendations(db_session, league, connection, _espn_rb2_free_agent_payload())

    assert crosswalk_route.call_count == 1
