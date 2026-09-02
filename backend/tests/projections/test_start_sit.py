import httpx
import pytest
import respx

from app.models import League, Player, PlayerUsageStats, ProjectionRecord, RosterSlot, Team
from app.projections.models import PlayerMetrics, PlayerProjection
from app.projections.start_sit import (
    build_explanation,
    compute_start_sit,
    get_current_roster,
    get_recent_performance_by_player,
)
from app.sleeper.client import SLEEPER_BASE_URL, SleeperClient


async def _make_league(db_session, platform: str, season: str = "2026", current_week: int = 1) -> League:
    league = League(
        platform=platform, platform_league_id="1", season=season, name="L", status="in_season",
        current_week=current_week, roster_positions=["QB", "RB", "RB", "WR", "WR", "FLEX", "BN", "BN"],
    )
    db_session.add(league)
    await db_session.flush()
    return league


async def _make_team(db_session, league: League, platform_roster_id: str = "1") -> Team:
    team = Team(league_id=league.id, platform_roster_id=platform_roster_id, display_name="My Team")
    db_session.add(team)
    await db_session.flush()
    return team


@pytest.mark.asyncio
async def test_get_current_roster_for_espn_reads_current_week_roster_slot(db_session):
    league = await _make_league(db_session, "espn", current_week=3)
    team = await _make_team(db_session, league)
    db_session.add_all(
        [
            RosterSlot(team_id=team.id, week=3, platform_player_id="100", is_starter=True, points=0),
            RosterSlot(team_id=team.id, week=3, platform_player_id="101", is_starter=False, points=0),
            # a stale prior-week row for the same team should not count
            RosterSlot(team_id=team.id, week=2, platform_player_id="999", is_starter=True, points=12),
        ]
    )
    await db_session.commit()

    roster = await get_current_roster(db_session, league, team)
    assert roster == {"100": True, "101": False}


@pytest.mark.asyncio
@respx.mock
async def test_get_current_roster_for_sleeper_fetches_live(db_session):
    league = await _make_league(db_session, "sleeper")
    team = await _make_team(db_session, league, platform_roster_id="7")
    respx.get(f"{SLEEPER_BASE_URL}/league/1/rosters").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "roster_id": 7,
                    "owner_id": "u1",
                    "league_id": "1",
                    "players": ["200", "201"],
                    "starters": ["200"],
                    "settings": {"wins": 0, "losses": 0, "ties": 0},
                },
                {
                    "roster_id": 8,
                    "owner_id": "u2",
                    "league_id": "1",
                    "players": ["999"],
                    "starters": [],
                    "settings": {"wins": 0, "losses": 0, "ties": 0},
                },
            ],
        )
    )

    client = SleeperClient()
    roster = await get_current_roster(db_session, league, team, sleeper_client=client)
    await client.aclose()

    assert roster == {"200": True, "201": False}


def test_build_explanation_states_projection_range():
    projection = PlayerProjection(
        "1", "P", "WR", 18.2, ["espn"],
        floor=14.0, ceiling=22.0, confidence=0.8, range_source="current_season", sample_size=8,
    )
    reasons = build_explanation(projection, None)
    assert reasons == ["Projected 18.2 points (14.0-22.0 range, based on 8 games this season)"]


def test_build_explanation_flags_limited_history_and_no_fabricated_range():
    projection = PlayerProjection("1", "P", "WR", 10.0, ["sleeper"])
    metrics = PlayerMetrics("1", experience_status="rookie_or_limited_history", games_played=1)
    reasons = build_explanation(projection, metrics)
    assert "Projected 10.0 points (range not available yet)" in reasons
    assert any("Limited NFL history" in r for r in reasons)
    assert any("Limited sample: 1 game" in r for r in reasons)


def test_build_explanation_flags_availability_risk():
    projection = PlayerProjection("1", "P", "RB", 12.0, ["espn"])
    for status, expected_substring in [
        ("doubtful", "Doubtful"),
        ("questionable", "Questionable"),
        ("unavailable", "Unavailable"),
    ]:
        metrics = PlayerMetrics("1", availability=status)
        reasons = build_explanation(projection, metrics)
        assert any(expected_substring in r for r in reasons)


def test_build_explanation_describes_matchup_difficulty():
    projection = PlayerProjection("1", "P", "WR", 15.0, ["espn"])
    easy = PlayerMetrics("1", opponent="SF", matchup_rating=80.0)
    tough = PlayerMetrics("1", opponent="NE", matchup_rating=10.0)
    assert any("Easy matchup vs SF" in r for r in build_explanation(projection, easy))
    assert any("Tough matchup vs NE" in r for r in build_explanation(projection, tough))


@pytest.mark.asyncio
async def test_compute_start_sit_fills_optimal_lineup_and_benches_the_rest(db_session):
    league = await _make_league(db_session, "espn", current_week=1)
    team = await _make_team(db_session, league)
    db_session.add_all(
        [
            Player(platform="espn", platform_player_id="qb1", position="QB", name="QB One"),
            Player(platform="espn", platform_player_id="rb1", position="RB", name="RB One"),
            Player(platform="espn", platform_player_id="rb2", position="RB", name="RB Two"),
            Player(platform="espn", platform_player_id="rb3", position="RB", name="RB Three"),
            Player(platform="espn", platform_player_id="wr1", position="WR", name="WR One"),
            Player(platform="espn", platform_player_id="wr2", position="WR", name="WR Two"),
            Player(platform="espn", platform_player_id="wr3", position="WR", name="WR Three"),
        ]
    )
    db_session.add_all(
        [
            RosterSlot(team_id=team.id, week=1, platform_player_id=pid, is_starter=False, points=0)
            for pid in ("qb1", "rb1", "rb2", "rb3", "wr1", "wr2", "wr3")
        ]
    )
    db_session.add_all(
        [
            ProjectionRecord(league_id=league.id, platform_player_id="qb1", week=1, source="espn", name="QB One", position="QB", projected_points=20.0),
            ProjectionRecord(league_id=league.id, platform_player_id="rb1", week=1, source="espn", name="RB One", position="RB", projected_points=18.0),
            ProjectionRecord(league_id=league.id, platform_player_id="rb2", week=1, source="espn", name="RB Two", position="RB", projected_points=14.0),
            ProjectionRecord(league_id=league.id, platform_player_id="rb3", week=1, source="espn", name="RB Three", position="RB", projected_points=11.0),
            ProjectionRecord(league_id=league.id, platform_player_id="wr1", week=1, source="espn", name="WR One", position="WR", projected_points=16.0),
            ProjectionRecord(league_id=league.id, platform_player_id="wr2", week=1, source="espn", name="WR Two", position="WR", projected_points=13.0),
            ProjectionRecord(league_id=league.id, platform_player_id="wr3", week=1, source="espn", name="WR Three", position="WR", projected_points=2.0),
        ]
    )
    await db_session.commit()

    result = await compute_start_sit(db_session, league, team)

    starter_ids = {row["platform_player_id"] for row in result["starters"]}
    bench_ids = {row["platform_player_id"] for row in result["bench"]}
    # roster_positions: QB, RB, RB, WR, WR, FLEX -- rb3 (11) should win FLEX over wr3 (2)
    assert starter_ids == {"qb1", "rb1", "rb2", "wr1", "wr2", "rb3"}
    assert bench_ids == {"wr3"}
    assert result["unavailable"] == []
    flex_row = next(r for r in result["starters"] if r["platform_player_id"] == "rb3")
    assert flex_row["recommended_slot"] == "FLEX"


@pytest.mark.asyncio
async def test_compute_start_sit_excludes_unavailable_players_from_optimizer(db_session):
    league = await _make_league(db_session, "espn", current_week=1)
    team = await _make_team(db_session, league)
    db_session.add_all(
        [
            Player(platform="espn", platform_player_id="hurt", position="WR", name="Hurt Guy", injury_status="Out"),
            Player(platform="espn", platform_player_id="healthy", position="WR", name="Healthy Guy"),
        ]
    )
    db_session.add_all(
        [
            RosterSlot(team_id=team.id, week=1, platform_player_id="hurt", is_starter=False, points=0),
            RosterSlot(team_id=team.id, week=1, platform_player_id="healthy", is_starter=False, points=0),
        ]
    )
    db_session.add_all(
        [
            ProjectionRecord(league_id=league.id, platform_player_id="hurt", week=1, source="espn", name="Hurt Guy", position="WR", projected_points=25.0),
            ProjectionRecord(league_id=league.id, platform_player_id="healthy", week=1, source="espn", name="Healthy Guy", position="WR", projected_points=5.0),
        ]
    )
    db_session.add(
        PlayerUsageStats(platform="espn", platform_player_id="hurt", season="2026", week=1, target_share=0.3)
    )
    await db_session.commit()

    league.roster_positions = ["WR"]
    result = await compute_start_sit(db_session, league, team)

    # Even though "hurt" projects far higher, OUT means they must not be started.
    starter_ids = {row["platform_player_id"] for row in result["starters"]}
    unavailable_ids = {row["platform_player_id"] for row in result["unavailable"]}
    assert starter_ids == {"healthy"}
    assert unavailable_ids == {"hurt"}


@pytest.mark.asyncio
async def test_compute_start_sit_handles_rookie_with_no_usage_data_cleanly(db_session):
    league = await _make_league(db_session, "espn", current_week=1)
    league.roster_positions = ["WR"]
    team = await _make_team(db_session, league)
    db_session.add(Player(platform="espn", platform_player_id="rookie", position="WR", name="Rookie WR"))
    db_session.add(RosterSlot(team_id=team.id, week=1, platform_player_id="rookie", is_starter=False, points=0))
    db_session.add(
        ProjectionRecord(
            league_id=league.id, platform_player_id="rookie", week=1, source="espn",
            name="Rookie WR", position="WR", projected_points=8.5,
        )
    )
    await db_session.commit()

    result = await compute_start_sit(db_session, league, team)

    assert len(result["starters"]) == 1
    row = result["starters"][0]
    assert row["target_share"] is None
    assert row["snap_share"] is None
    assert row["experience_status"] == "rookie_or_limited_history"
    assert row["projected_points"] == 8.5


@pytest.mark.asyncio
async def test_get_recent_performance_by_player_matches_actual_to_the_same_week_projection(db_session):
    league = await _make_league(db_session, "espn", current_week=3)
    team = await _make_team(db_session, league)
    db_session.add_all(
        [
            RosterSlot(team_id=team.id, week=1, platform_player_id="1", is_starter=True, points=14.0),
            RosterSlot(team_id=team.id, week=2, platform_player_id="1", is_starter=True, points=22.5),
        ]
    )
    db_session.add_all(
        [
            ProjectionRecord(league_id=league.id, platform_player_id="1", week=1, source="espn", name="P", position="WR", projected_points=16.0),
            ProjectionRecord(league_id=league.id, platform_player_id="1", week=2, source="espn", name="P", position="WR", projected_points=18.0),
        ]
    )
    await db_session.commit()

    performance = await get_recent_performance_by_player(db_session, league, {"1"})

    # week 2 is the most recent PAST week (current_week=3) -- should use week 2's actual/projected pair.
    assert performance["1"] == (22.5, 18.0, 2)


def test_build_explanation_reports_over_and_under_performance():
    projection = PlayerProjection("1", "P", "WR", 15.0, ["espn"])
    over = build_explanation(projection, None, recent_performance=(22.5, 18.0, 2))
    under = build_explanation(projection, None, recent_performance=(9.0, 16.0, 2))

    assert any("Outperformed week 2" in r and "4.5" in r for r in over)
    assert any("Underperformed week 2" in r and "7.0" in r for r in under)


@pytest.mark.asyncio
async def test_compute_start_sit_pairs_a_real_swap_with_head_to_head_comparison(db_session):
    league = await _make_league(db_session, "espn", current_week=1)
    league.roster_positions = ["WR"]
    team = await _make_team(db_session, league)
    db_session.add_all(
        [
            Player(platform="espn", platform_player_id="better", position="WR", name="Better WR"),
            Player(platform="espn", platform_player_id="currently_started", position="WR", name="Currently Started WR"),
        ]
    )
    db_session.add_all(
        [
            # "better" is on the bench in real life; "currently_started" is really in the lineup right now.
            RosterSlot(team_id=team.id, week=1, platform_player_id="better", is_starter=False, points=0),
            RosterSlot(team_id=team.id, week=1, platform_player_id="currently_started", is_starter=True, points=0),
        ]
    )
    db_session.add_all(
        [
            ProjectionRecord(league_id=league.id, platform_player_id="better", week=1, source="espn", name="Better WR", position="WR", projected_points=18.0),
            ProjectionRecord(league_id=league.id, platform_player_id="currently_started", week=1, source="espn", name="Currently Started WR", position="WR", projected_points=16.7),
        ]
    )
    await db_session.commit()

    result = await compute_start_sit(db_session, league, team)

    starter = result["starters"][0]
    bencher = result["bench"][0]
    assert starter["platform_player_id"] == "better"
    assert starter["action"] == "swap_in"
    assert bencher["platform_player_id"] == "currently_started"
    assert bencher["action"] == "swap_out"

    assert starter["swap_out_player_id"] == "currently_started"
    assert starter["swap_out_name"] == "Currently Started WR"
    comparison = starter["comparison"]
    assert comparison is not None
    assert comparison["opponent_player_id"] == "currently_started"
    assert comparison["is_close_call"] is True
    assert any("1.3" in r for r in comparison["favors_this_player"])

    assert result["summary"]["changes_count"] == 1
    assert result["summary"]["current_lineup_points"] == pytest.approx(16.7)
    assert result["summary"]["projected_points_change"] == pytest.approx(18.0 - 16.7)


@pytest.mark.asyncio
async def test_compute_start_sit_reports_no_changes_when_lineup_already_optimal(db_session):
    league = await _make_league(db_session, "espn", current_week=1)
    league.roster_positions = ["WR"]
    team = await _make_team(db_session, league)
    db_session.add(Player(platform="espn", platform_player_id="only", position="WR", name="Only WR"))
    # already the real starter, and also the optimizer's pick -- nothing to change.
    db_session.add(RosterSlot(team_id=team.id, week=1, platform_player_id="only", is_starter=True, points=0))
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="only", week=1, source="espn", name="Only WR", position="WR", projected_points=12.0)
    )
    await db_session.commit()

    result = await compute_start_sit(db_session, league, team)

    assert result["starters"][0]["action"] == "start"
    assert result["starters"][0]["comparison"] is None
    assert result["summary"]["changes_count"] == 0
    assert result["summary"]["projected_points_change"] == 0.0


@pytest.mark.asyncio
async def test_compute_start_sit_comparison_is_none_with_no_swap_partner(db_session):
    league = await _make_league(db_session, "espn", current_week=1)
    league.roster_positions = ["WR"]
    team = await _make_team(db_session, league)
    db_session.add(Player(platform="espn", platform_player_id="only", position="WR", name="Only WR"))
    db_session.add(RosterSlot(team_id=team.id, week=1, platform_player_id="only", is_starter=False, points=0))
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="only", week=1, source="espn", name="Only WR", position="WR", projected_points=12.0)
    )
    await db_session.commit()

    result = await compute_start_sit(db_session, league, team)

    assert result["starters"][0]["action"] == "swap_in"
    assert result["starters"][0]["comparison"] is None


@pytest.mark.asyncio
async def test_compute_start_sit_includes_gridlytics_projection_when_available(db_session):
    league = await _make_league(db_session, "espn", current_week=1)
    league.roster_positions = ["WR"]
    team = await _make_team(db_session, league)
    db_session.add(Player(platform="espn", platform_player_id="wr1", position="WR", name="WR One"))
    db_session.add(RosterSlot(team_id=team.id, week=1, platform_player_id="wr1", is_starter=False, points=0))
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="wr1", week=1, source="espn",
                          name="WR One", position="WR", projected_points=12.0)
    )
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="wr1", week=1, source="gridlytics",
                          name="WR One", position="WR", projected_points=15.5,
                          expected_opportunities=6.2, prior_season_weight=0.3, dominant_category="receiving")
    )
    await db_session.commit()

    result = await compute_start_sit(db_session, league, team)

    row = result["starters"][0]
    assert row["gridlytics_projected_points"] == pytest.approx(15.5)
    assert row["gridlytics_expected_opportunities"] == pytest.approx(6.2)
    assert row["gridlytics_prior_season_weight"] == pytest.approx(0.3)
    assert row["gridlytics_dominant_category"] == "receiving"
    assert row["gridlytics_lower_confidence"] is False


@pytest.mark.asyncio
async def test_compute_start_sit_gridlytics_fields_null_when_no_native_projection(db_session):
    league = await _make_league(db_session, "espn", current_week=1)
    league.roster_positions = ["WR"]
    team = await _make_team(db_session, league)
    db_session.add(Player(platform="espn", platform_player_id="wr1", position="WR", name="WR One"))
    db_session.add(RosterSlot(team_id=team.id, week=1, platform_player_id="wr1", is_starter=False, points=0))
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="wr1", week=1, source="espn",
                          name="WR One", position="WR", projected_points=12.0)
    )
    await db_session.commit()

    result = await compute_start_sit(db_session, league, team)

    row = result["starters"][0]
    assert row["gridlytics_projected_points"] is None
    assert row["gridlytics_dominant_category"] is None


@pytest.mark.asyncio
async def test_compute_start_sit_headline_projected_points_is_the_blended_final(db_session):
    # The row's primary "projected_points" (what the optimizer maximizes and the card headline
    # shows) must be the 50/50 blend, not the raw multi-source ensemble average and not the
    # unblended Gridlytics base alone.
    league = await _make_league(db_session, "espn", current_week=1)
    league.roster_positions = ["WR"]
    team = await _make_team(db_session, league)
    db_session.add(Player(platform="espn", platform_player_id="wr1", position="WR", name="WR One"))
    db_session.add(RosterSlot(team_id=team.id, week=1, platform_player_id="wr1", is_starter=False, points=0))
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="wr1", week=1, source="espn",
                          name="WR One", position="WR", projected_points=12.0)
    )
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="wr1", week=1, source="gridlytics",
                          name="WR One", position="WR", projected_points=15.5)
    )
    await db_session.commit()

    result = await compute_start_sit(db_session, league, team)

    row = result["starters"][0]
    assert row["gridlytics_base_projection"] == pytest.approx(15.5)
    assert row["platform_projection"] == pytest.approx(12.0)
    assert row["final_gridlytics_projection"] == pytest.approx(13.75)
    assert row["projected_points"] == pytest.approx(13.75)


@pytest.mark.asyncio
async def test_compute_start_sit_missing_platform_projection_uses_gridlytics_base_only(db_session):
    league = await _make_league(db_session, "espn", current_week=1)
    league.roster_positions = ["WR"]
    team = await _make_team(db_session, league)
    db_session.add(Player(platform="espn", platform_player_id="wr1", position="WR", name="WR One"))
    db_session.add(RosterSlot(team_id=team.id, week=1, platform_player_id="wr1", is_starter=False, points=0))
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="wr1", week=1, source="gridlytics",
                          name="WR One", position="WR", projected_points=15.5)
    )
    await db_session.commit()

    result = await compute_start_sit(db_session, league, team)

    row = result["starters"][0]
    assert row["platform_projection"] is None
    assert row["final_gridlytics_projection"] == pytest.approx(15.5)
    assert row["projected_points"] == pytest.approx(15.5)


@pytest.mark.asyncio
async def test_compute_start_sit_legitimate_zero_for_confirmed_unavailable_player(db_session):
    league = await _make_league(db_session, "espn", current_week=1)
    league.roster_positions = ["WR"]
    team = await _make_team(db_session, league)
    db_session.add(
        Player(platform="espn", platform_player_id="wr1", position="WR", name="WR One", injury_status="Out")
    )
    db_session.add(RosterSlot(team_id=team.id, week=1, platform_player_id="wr1", is_starter=False, points=0))
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="wr1", week=1, source="espn",
                          name="WR One", position="WR", projected_points=0.0)
    )
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="wr1", week=1, source="gridlytics",
                          name="WR One", position="WR", projected_points=15.5)
    )
    # Needed for NflverseMetricsProvider to include this player at all (it only considers
    # players with real usage-stats or baseline rows) -- matches the pattern the existing
    # unavailable-player test already relies on.
    db_session.add(
        PlayerUsageStats(platform="espn", platform_player_id="wr1", season="2026", week=1, target_share=0.2)
    )
    await db_session.commit()

    result = await compute_start_sit(db_session, league, team)

    row = result["unavailable"][0]
    assert row["final_gridlytics_projection"] == pytest.approx(0.0)
    assert row["projected_points"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_compute_start_sit_suspicious_zero_without_unavailable_status_uses_base_only(db_session):
    # Platform reports 0 but nothing confirms this player is actually out/IR/bye -- must not be
    # averaged toward a fabricated zero.
    league = await _make_league(db_session, "espn", current_week=1)
    league.roster_positions = ["WR"]
    team = await _make_team(db_session, league)
    db_session.add(Player(platform="espn", platform_player_id="wr1", position="WR", name="WR One"))
    db_session.add(RosterSlot(team_id=team.id, week=1, platform_player_id="wr1", is_starter=False, points=0))
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="wr1", week=1, source="espn",
                          name="WR One", position="WR", projected_points=0.0)
    )
    db_session.add(
        ProjectionRecord(league_id=league.id, platform_player_id="wr1", week=1, source="gridlytics",
                          name="WR One", position="WR", projected_points=15.5)
    )
    await db_session.commit()

    result = await compute_start_sit(db_session, league, team)

    row = result["starters"][0]
    assert row["final_gridlytics_projection"] == pytest.approx(15.5)
    assert row["projected_points"] == pytest.approx(15.5)
    assert row["gridlytics_lower_confidence"] is False
