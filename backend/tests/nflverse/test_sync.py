import gzip
import io

import httpx
import pandas as pd
import pytest
import respx
from sqlalchemy import select

from app.models import (
    League,
    Player,
    PlayerUsageStats,
    PositionVolatilityPrior,
    ProjectionRecord,
    RosterSlot,
    Team,
    TeamDefenseStrength,
    TeamMatchup,
)
from app.nflverse.client import DYNASTYPROCESS_IDS_URL, NFLVERSE_RELEASES_BASE_URL, NflverseClient
from app.nflverse.crosswalk import MANUAL_SLEEPER_OVERRIDES
from app.nflverse.sync import sync_matchup_context, sync_usage_stats

CROSSWALK_CSV = (
    "gsis_id,display_name,espn_id,pfr_id,position\n"
    "00-0039075,Puka Nacua,4426515,NacuPu00,WR\n"
    "00-0023459,Cody White,9999999,WhitCo00,WR\n"
    "00-0011111,Someone Elsewhere,8888888,SomeEl00,RB\n"
)

SLEEPER_CROSSWALK_CSV = "sleeper_id,gsis_id,name\n7039,00-0023459,Cody White\n"

WEEKLY_STATS_CSV = (
    "player_id,player_display_name,position,season,season_type,week,targets,target_share,carries,"
    "team,opponent_team,fantasy_points_ppr,receiving_yards,receiving_tds,receptions,rushing_yards,"
    "rushing_tds,attempts,passing_yards,passing_tds,passing_interceptions\n"
    "00-0039075,Puka Nacua,WR,2024,REG,1,10,0.28,1,LA,SF,20.0,120,1,7,5,0,0,0,0,0\n"
    "00-0039075,Puka Nacua,WR,2024,REG,2,12,0.31,0,LA,SEA,18.0,110,1,6,0,0,0,0,0,0\n"
    "00-0023459,Cody White,WR,2024,REG,1,3,0.05,0,SF,LA,10.0,30,0,2,0,0,0,0,0,0\n"
    "00-0011111,Someone Elsewhere,RB,2024,REG,1,6,0.10,4,SF,LA,15.0,20,0,2,25,1,0,0,0,0\n"
    "00-0039075,Puka Nacua,WR,2024,POST,19,15,0.4,2,LA,SF,30.0,150,2,10,10,0,0,0,0,0\n"
    # Real starting QBs on both teams -- not crosswalk-mapped/rostered by anyone, but needed so
    # each team's real total pass attempts (used by the validated team-volume prior/A+B model)
    # isn't artificially zero just because no rostered player happens to be the passer.
    "00-0088001,Team LA QB,QB,2024,REG,1,0,0.0,1,LA,SF,18.0,0,0,0,3,0,32,230,2,0\n"
    "00-0088001,Team LA QB,QB,2024,REG,2,0,0.0,2,LA,SEA,16.0,0,0,0,5,0,30,210,1,0\n"
    "00-0088002,Team SF QB,QB,2024,REG,1,0,0.0,2,SF,LA,14.0,0,0,0,4,0,28,190,1,0\n"
)

SNAP_COUNTS_CSV = "pfr_player_id,season,week,game_type,offense_pct\nNacuPu00,2024,1,REG,0.91\n"

PBP_CSV = (
    "season_type,week,yardline_100,pass_attempt,rush_attempt,receiver_player_id,rusher_player_id\n"
    "REG,1,12,1,0,00-0039075,\n"
)

SCHEDULE_CSV = (
    "season,week,home_team,away_team,gameday\n"
    "2024,1,LA,SF,2024-09-08\n"
    "2024,2,LA,SEA,2024-09-15\n"
)

DEPTH_CHARTS_CSV = (
    "dt,team,gsis_id,pos_abb,pos_rank\n"
    "2024-08-01T00:00:00Z,LA,00-0039075,WR,1\n"
    "2024-08-01T00:00:00Z,SF,00-0023459,WR,2\n"
    "2024-08-01T00:00:00Z,SF,00-0011111,RB,1\n"
)


async def _make_league(db_session, platform: str, season: str = "2024") -> League:
    league = League(platform=platform, platform_league_id="1", season=season, name="L", status="in_season")
    db_session.add(league)
    await db_session.flush()
    return league


async def _add_rostered_player(db_session, league: League, platform_player_id: str) -> None:
    team = Team(league_id=league.id, platform_roster_id="1", display_name="A")
    db_session.add(team)
    await db_session.flush()
    db_session.add(
        RosterSlot(team_id=team.id, week=1, platform_player_id=platform_player_id, is_starter=True, points=0)
    )
    await db_session.commit()


def _mock_nflverse(season: str = "2024") -> None:
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/players/players.csv").mock(
        return_value=httpx.Response(200, text=CROSSWALK_CSV)
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_{season}.csv").mock(
        return_value=httpx.Response(200, text=WEEKLY_STATS_CSV)
    )
    respx.get(DYNASTYPROCESS_IDS_URL).mock(return_value=httpx.Response(200, text=SLEEPER_CROSSWALK_CSV))
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/snap_counts/snap_counts_{season}.csv").mock(
        return_value=httpx.Response(200, text=SNAP_COUNTS_CSV)
    )
    # season-1 (offset 1) through season-4 (offset 4): season-1 is the "prior season" (fetched
    # for baseline sync, mocked as not-yet-published/404 here) and season-2..4 are the extra
    # real history the validated multi-year team prior and career prior both look back over.
    for offset in range(1, 5):
        year = str(int(season) - offset)
        respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_reg_{year}.csv").mock(
            return_value=httpx.Response(404)
        )
        respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_{year}.csv").mock(
            return_value=httpx.Response(404)
        )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/pbp/play_by_play_{season}.csv.gz").mock(
        return_value=httpx.Response(200, content=gzip.compress(PBP_CSV.encode()))
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/schedules/games.csv").mock(
        return_value=httpx.Response(200, text=SCHEDULE_CSV)
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/depth_charts/depth_charts_{season}.csv").mock(
        return_value=httpx.Response(200, text=DEPTH_CHARTS_CSV)
    )


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_matches_espn_players_by_espn_id(db_session):
    league = await _make_league(db_session, "espn")
    await _add_rostered_player(db_session, league, "4426515")
    _mock_nflverse()

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(select(PlayerUsageStats))
    records = {r.week: r for r in result.scalars().all()}

    assert len(records) == 2
    assert records[1].target_share == 0.28
    assert records[2].targets == 12
    assert records[1].snap_share == 0.91
    assert records[1].red_zone_opportunities == 1
    # week 2 has no snap_counts/pbp row mocked for it
    assert records[2].snap_share is None
    assert records[2].red_zone_opportunities is None
    # POST week should be excluded
    assert 19 not in records


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_persists_prior_season_baseline(db_session):
    from app.models import PlayerSeasonBaseline

    league = await _make_league(db_session, "espn")
    await _add_rostered_player(db_session, league, "4426515")
    _mock_nflverse()
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_reg_2023.csv").mock(
        return_value=httpx.Response(
            200,
            text=(
                "player_id,player_display_name,position,recent_team,target_share\n"
                "00-0039075,Puka Nacua,WR,LA,0.27\n"
            ),
        )
    )

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(select(PlayerSeasonBaseline))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].platform_player_id == "4426515"
    assert rows[0].season == "2023"
    assert rows[0].team == "LA"
    assert rows[0].target_share == 0.27


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_matches_sleeper_player_by_own_gsis_id_first(db_session):
    league = await _make_league(db_session, "sleeper")
    await _add_rostered_player(db_session, league, "9075")
    # Sleeper's own gsis_id must win even though the crosswalk below maps this sleeper_id to a different player.
    db_session.add(
        Player(
            platform="sleeper", platform_player_id="9075", position="WR", name="Puka Nacua",
            gsis_id="00-0039075",
        )
    )
    await db_session.commit()
    _mock_nflverse()
    respx.get(DYNASTYPROCESS_IDS_URL).mock(
        return_value=httpx.Response(200, text="sleeper_id,gsis_id,name\n9075,00-0011111,Wrong Player\n")
    )

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(
        select(PlayerUsageStats).where(PlayerUsageStats.platform_player_id == "9075")
    )
    records = result.scalars().all()
    assert len(records) == 2
    assert {r.targets for r in records} == {10, 12}


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_matches_sleeper_player_via_dynastyprocess_crosswalk(db_session):
    league = await _make_league(db_session, "sleeper")
    await _add_rostered_player(db_session, league, "7039")
    # No gsis_id known to Sleeper -- must fall through to the sleeper_id crosswalk, not name+position.
    db_session.add(Player(platform="sleeper", platform_player_id="7039", position="WR", name="Somebody Else"))
    await db_session.commit()
    _mock_nflverse()

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(
        select(PlayerUsageStats).where(PlayerUsageStats.platform_player_id == "7039")
    )
    records = result.scalars().all()
    assert len(records) == 1
    assert records[0].targets == 3


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_matches_sleeper_player_by_name_and_position_fallback(db_session):
    league = await _make_league(db_session, "sleeper")
    await _add_rostered_player(db_session, league, "abc")
    # No gsis_id or sleeper_id crosswalk entry for "abc" -- must fall through to normalized name+position.
    db_session.add(Player(platform="sleeper", platform_player_id="abc", position="RB", name="Someone Elsewhere"))
    await db_session.commit()
    _mock_nflverse()

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(
        select(PlayerUsageStats).where(PlayerUsageStats.platform_player_id == "abc")
    )
    records = result.scalars().all()
    assert len(records) == 1
    assert records[0].targets == 6


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_manual_override_wins_over_every_other_tier(db_session):
    league = await _make_league(db_session, "sleeper")
    await _add_rostered_player(db_session, league, "9075")
    db_session.add(
        Player(
            platform="sleeper", platform_player_id="9075", position="WR", name="Puka Nacua",
            gsis_id="00-0011111",
        )
    )
    await db_session.commit()
    _mock_nflverse()

    MANUAL_SLEEPER_OVERRIDES["9075"] = "00-0039075"
    try:
        client = NflverseClient()
        await sync_usage_stats(db_session, client, league)
        await client.aclose()
    finally:
        MANUAL_SLEEPER_OVERRIDES.clear()

    result = await db_session.execute(
        select(PlayerUsageStats).where(PlayerUsageStats.platform_player_id == "9075")
    )
    records = result.scalars().all()
    assert len(records) == 2
    assert {r.targets for r in records} == {10, 12}


@pytest.mark.asyncio
@respx.mock
async def test_sync_matchup_context_persists_defense_strength_and_schedule(db_session):
    league = await _make_league(db_session, "espn")
    schedule_df = pd.read_csv(io.StringIO(SCHEDULE_CSV))

    weekly_stats_df = pd.DataFrame(
        [
            {"season_type": "REG", "opponent_team": "SF", "position": "WR", "fantasy_points_ppr": 20.0},
            {"season_type": "REG", "opponent_team": "SF", "position": "WR", "fantasy_points_ppr": 10.0},
        ]
    )

    await sync_matchup_context(db_session, league, weekly_stats_df, schedule_df)

    result = await db_session.execute(select(TeamDefenseStrength))
    strength_rows = result.scalars().all()
    assert len(strength_rows) == 1
    assert strength_rows[0].team == "SF"
    assert strength_rows[0].points_allowed_avg == 15.0

    result = await db_session.execute(select(TeamMatchup).where(TeamMatchup.week == 1))
    matchups = {row.team: row.opponent for row in result.scalars().all()}
    assert matchups == {"LA": "SF", "SF": "LA"}


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_is_idempotent(db_session):
    league = await _make_league(db_session, "espn")
    await _add_rostered_player(db_session, league, "4426515")
    _mock_nflverse()

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(select(PlayerUsageStats))
    assert len(result.scalars().all()) == 2


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_still_syncs_prior_season_baseline_when_current_season_not_published(db_session):
    from app.models import PlayerSeasonBaseline

    league = await _make_league(db_session, "espn", season="2099")
    await _add_rostered_player(db_session, league, "4426515")
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_2099.csv").mock(
        return_value=httpx.Response(404)
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/players/players.csv").mock(
        return_value=httpx.Response(200, text=CROSSWALK_CSV)
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/schedules/games.csv").mock(
        return_value=httpx.Response(200, text="season,week,home_team,away_team\n2099,1,LA,SF\n")
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_reg_2098.csv").mock(
        return_value=httpx.Response(
            200,
            text=(
                "player_id,player_display_name,position,recent_team,target_share\n"
                "00-0039075,Puka Nacua,WR,LA,0.27\n"
            ),
        )
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_2098.csv").mock(
        return_value=httpx.Response(404)
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/depth_charts/depth_charts_2099.csv").mock(
        return_value=httpx.Response(404)
    )
    # Career-prior/team-prior lookback reaches back 4 seasons (2098-2095) -- 2098 is mocked with
    # real data above, the other 3 have none published (real preseason scenario: even 2098's
    # season-aggregate file might be all that's out yet).
    for year in (2097, 2096, 2095):
        respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_reg_{year}.csv").mock(
            return_value=httpx.Response(404)
        )
        respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_{year}.csv").mock(
            return_value=httpx.Response(404)
        )

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    # No current-season usage data exists yet -- must not be fabricated.
    result = await db_session.execute(select(PlayerUsageStats))
    assert result.scalars().all() == []

    # But the prior-season baseline should still sync -- this is exactly the preseason case where
    # it matters most, and used to get silently skipped because it was gated behind the (unrelated)
    # current-season file existing.
    result = await db_session.execute(select(PlayerSeasonBaseline))
    baselines = result.scalars().all()
    assert len(baselines) == 1
    assert baselines[0].platform_player_id == "4426515"
    assert baselines[0].season == "2098"
    assert baselines[0].target_share == 0.27


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_persists_prior_season_weekly_scores(db_session):
    league = await _make_league(db_session, "espn")
    await _add_rostered_player(db_session, league, "4426515")
    _mock_nflverse()
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_2023.csv").mock(
        return_value=httpx.Response(
            200,
            text=(
                "player_id,player_display_name,position,team,season,season_type,week,targets,target_share,carries,"
                "attempts,fantasy_points_ppr\n"
                "00-0039075,Puka Nacua,WR,LA,2023,REG,1,9,0.25,0,0,17.5\n"
                "00-0039075,Puka Nacua,WR,LA,2023,POST,19,5,0.2,0,0,9.0\n"
            ),
        )
    )

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(
        select(PlayerUsageStats).where(
            PlayerUsageStats.platform_player_id == "4426515", PlayerUsageStats.season == "2023"
        )
    )
    records = result.scalars().all()
    assert len(records) == 1
    assert records[0].fantasy_points_ppr == 17.5
    assert records[0].target_share == 0.25


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_persists_position_volatility_priors_from_prior_season(db_session):
    league = await _make_league(db_session, "espn")
    await _add_rostered_player(db_session, league, "4426515")
    _mock_nflverse()

    rows = ["player_id,player_display_name,position,team,season,season_type,week,carries,attempts,fantasy_points_ppr"]
    for player_id, scores in [
        ("rb-1", [8.0, 12.0, 4.0, 16.0]),
        ("rb-2", [16.0, 24.0, 8.0, 32.0]),
        ("rb-3", [6.0, 9.0, 3.0, 12.0]),
    ]:
        for week, score in enumerate(scores, start=1):
            rows.append(f"{player_id},Someone,RB,SF,2023,REG,{week},0,0,{score}")
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_2023.csv").mock(
        return_value=httpx.Response(200, text="\n".join(rows) + "\n")
    )

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(
        select(PositionVolatilityPrior).where(
            PositionVolatilityPrior.season == "2023", PositionVolatilityPrior.position == "RB"
        )
    )
    prior = result.scalar_one_or_none()
    assert prior is not None
    assert prior.sample_size == 12
    assert prior.low_ratio < 1.0 < prior.high_ratio


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_noop_when_no_rostered_players(db_session):
    league = await _make_league(db_session, "espn")

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(select(PlayerUsageStats))
    assert result.scalars().all() == []


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_writes_gridlytics_projection_for_rostered_player(db_session):
    # current_week=2 so week-1 real data (both for this player's own history and for pooling
    # position priors) is actually eligible -- before_week=1 (the default current_week) would
    # exclude all of season 2024's own real rows from the leakage-safe priors entirely.
    league = await _make_league(db_session, "espn")
    league.current_week = 2
    await _add_rostered_player(db_session, league, "4426515")
    db_session.add(
        Player(platform="espn", platform_player_id="4426515", position="WR", name="Puka Nacua", team="LA")
    )
    await db_session.commit()
    _mock_nflverse()

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(
        select(ProjectionRecord).where(
            ProjectionRecord.platform_player_id == "4426515", ProjectionRecord.source == "gridlytics"
        )
    )
    record = result.scalar_one_or_none()
    assert record is not None
    assert record.projected_points >= 0
    assert record.dominant_category == "receiving"
    assert record.prior_season_weight is not None


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_skips_def_and_k_for_gridlytics_projection(db_session):
    league = await _make_league(db_session, "espn")
    league.current_week = 2
    await _add_rostered_player(db_session, league, "def-1")
    db_session.add(Player(platform="espn", platform_player_id="def-1", position="DEF", name="Some Defense"))
    await db_session.commit()
    _mock_nflverse()

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(
        select(ProjectionRecord).where(
            ProjectionRecord.platform_player_id == "def-1", ProjectionRecord.source == "gridlytics"
        )
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_writes_gridlytics_projection_for_zero_history_rookie(db_session):
    # This player is rostered and has a real Player row (with a real position), but appears
    # nowhere in CROSSWALK_CSV or WEEKLY_STATS_CSV -- no nflverse history at all. Must still get
    # a position-prior-based projection, never silently skipped. Direct regression test for the
    # position-source bug caught during spec self-review.
    # A second, crosswalk-mapped rostered player is included alongside the rookie -- a real
    # league always has some well-known players, and sync_usage_stats's own player_to_gsis
    # early-return would otherwise bail before ever reaching the native-projection step if the
    # rookie were the *only* rostered player (a scenario that doesn't occur in practice).
    league = await _make_league(db_session, "espn")
    league.current_week = 2
    await _add_rostered_player(db_session, league, "rookie-1")
    db_session.add(Player(platform="espn", platform_player_id="rookie-1", position="RB", name="Rookie RB"))
    team_result = await db_session.execute(select(Team).where(Team.league_id == league.id))
    team = team_result.scalar_one()
    db_session.add(
        RosterSlot(team_id=team.id, week=1, platform_player_id="4426515", is_starter=True, points=0)
    )
    db_session.add(
        Player(platform="espn", platform_player_id="4426515", position="WR", name="Puka Nacua", team="LA")
    )
    await db_session.commit()
    _mock_nflverse()

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(
        select(ProjectionRecord).where(
            ProjectionRecord.platform_player_id == "rookie-1", ProjectionRecord.source == "gridlytics"
        )
    )
    record = result.scalar_one_or_none()
    assert record is not None
    assert record.projected_points is not None


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_gridlytics_projection_uses_real_league_scoring_settings(db_session):
    # Same real player, same real nflverse data -- the only difference is league scoring settings.
    # A half-PPR + softer (-1.0) interception-penalty Sleeper league must NOT produce the same
    # projected_points as a league with no scoring_settings captured at all (which must fall back
    # to standard PPR, not silently claim league-specific accuracy it doesn't have).
    ppr_league = await _make_league(db_session, "espn")
    ppr_league.current_week = 2
    await _add_rostered_player(db_session, ppr_league, "4426515")
    db_session.add(
        Player(platform="espn", platform_player_id="4426515", position="WR", name="Puka Nacua", team="LA")
    )

    half_ppr_league = await _make_league(db_session, "sleeper")
    half_ppr_league.current_week = 2
    half_ppr_league.scoring_settings = {"rec": 0.5, "pass_int": -1.0}
    await _add_rostered_player(db_session, half_ppr_league, "4426515")
    db_session.add(
        Player(platform="sleeper", platform_player_id="4426515", position="WR", name="Puka Nacua", team="LA")
    )
    await db_session.commit()
    _mock_nflverse()

    client = NflverseClient()
    await sync_usage_stats(db_session, client, ppr_league)
    await sync_usage_stats(db_session, client, half_ppr_league)
    await client.aclose()

    ppr_result = await db_session.execute(
        select(ProjectionRecord).where(
            ProjectionRecord.league_id == ppr_league.id,
            ProjectionRecord.platform_player_id == "4426515",
            ProjectionRecord.source == "gridlytics",
        )
    )
    half_ppr_result = await db_session.execute(
        select(ProjectionRecord).where(
            ProjectionRecord.league_id == half_ppr_league.id,
            ProjectionRecord.platform_player_id == "4426515",
            ProjectionRecord.source == "gridlytics",
        )
    )
    ppr_record = ppr_result.scalar_one()
    half_ppr_record = half_ppr_result.scalar_one()
    assert ppr_record.projected_points != pytest.approx(half_ppr_record.projected_points)
    # Half-credit receptions dominate this WR's real profile -- the half-PPR total must be lower.
    assert half_ppr_record.projected_points < ppr_record.projected_points


@pytest.mark.asyncio
@respx.mock
async def test_sync_usage_stats_gridlytics_projection_is_idempotent(db_session):
    league = await _make_league(db_session, "espn")
    league.current_week = 2
    await _add_rostered_player(db_session, league, "4426515")
    db_session.add(
        Player(platform="espn", platform_player_id="4426515", position="WR", name="Puka Nacua", team="LA")
    )
    await db_session.commit()
    _mock_nflverse()

    client = NflverseClient()
    await sync_usage_stats(db_session, client, league)
    await sync_usage_stats(db_session, client, league)
    await client.aclose()

    result = await db_session.execute(
        select(ProjectionRecord).where(
            ProjectionRecord.platform_player_id == "4426515", ProjectionRecord.source == "gridlytics"
        )
    )
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
@respx.mock
async def test_effective_role_promotes_backup_rb_when_starter_ruled_out(db_session):
    """Real, DB-backed proof that the effective-role mechanism fires through the actual
    production entrypoint (sync_usage_stats), not just in isolated unit tests. RB1
    (00-0011111) is SF's real depth-chart rank-1 RB with real week-1 rushing stats already in
    the shared fixtures. RB2 (00-0022222) is added here as SF's rank-2 backup with zero own
    history. A third player (00-0044444, KC) is added purely to seed a real rank-2 share prior,
    so both scenarios resolve through the context-aware model -- never native fallback -- making
    this an apples-to-apples comparison of the SAME model, differing only by which rank RB2 is
    evaluated at."""
    league = await _make_league(db_session, "sleeper")
    league.current_week = 2
    await _add_rostered_player(db_session, league, "00-0011111")
    await _add_rostered_player(db_session, league, "00-0022222")
    db_session.add_all([
        Player(platform="sleeper", platform_player_id="00-0011111", position="RB", name="RB1",
               gsis_id="00-0011111", team="SF"),
        Player(platform="sleeper", platform_player_id="00-0022222", position="RB", name="RB2",
               gsis_id="00-0022222", team="SF"),
    ])
    await db_session.commit()

    _mock_nflverse()
    # KC starter (00-0055555, not rostered, not depth-chart-tracked -- exists purely to give KC a
    # real team-carries total) dilutes the KC backup's own share down to a realistic ~10%, well
    # below RB1's real ~67% share -- otherwise the backup would be KC's only ball-carrier that
    # week (share=1.0), an artificially high "rank 2" prior that would invert the direction of
    # this whole test.
    extended_weekly_stats = WEEKLY_STATS_CSV + (
        "00-0044444,KC Backup RB,RB,2024,REG,1,0,0.0,2,KC,DEN,3.0,0,0,0,8,0,0,0,0,0\n"
        "00-0055555,KC Starter RB,RB,2024,REG,1,0,0.0,18,KC,DEN,20.0,0,0,0,90,1,0,0,0,0\n"
    )
    extended_depth_charts = DEPTH_CHARTS_CSV + (
        "2024-08-01T00:00:00Z,SF,00-0022222,RB,2\n"
        "2024-08-01T00:00:00Z,KC,00-0044444,RB,2\n"
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_2024.csv").mock(
        return_value=httpx.Response(200, text=extended_weekly_stats)
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/depth_charts/depth_charts_2024.csv").mock(
        return_value=httpx.Response(200, text=extended_depth_charts)
    )

    async def rb2_projection() -> ProjectionRecord:
        result = await db_session.execute(
            select(ProjectionRecord).where(
                ProjectionRecord.platform_player_id == "00-0022222", ProjectionRecord.source == "gridlytics"
            )
        )
        return result.scalar_one()

    client = NflverseClient()

    # Scenario A: RB1 healthy. RB2 stays at its real depth-chart rank (2).
    await sync_usage_stats(db_session, client, league)
    record = await rb2_projection()
    assert record.dominant_category is not None  # context-aware model resolved, not native fallback
    # Snapshot as a plain float -- record is a SQLAlchemy identity-mapped object, and the second
    # sync below mutates this SAME row in place, so holding onto `record` itself across the
    # mutation would silently read the post-mutation value back for "healthy" too.
    rb2_healthy_points = record.projected_points

    # Scenario B: RB1 ruled OUT. Nothing else changes -- same weekly stats, same depth chart.
    result = await db_session.execute(
        select(Player).where(Player.platform == "sleeper", Player.platform_player_id == "00-0011111")
    )
    rb1 = result.scalar_one()
    rb1.injury_status = "OUT"
    await db_session.commit()

    await sync_usage_stats(db_session, client, league)
    await client.aclose()
    record = await rb2_projection()
    assert record.dominant_category is not None
    rb2_out_points = record.projected_points

    # The only real-world fact that changed between the two runs is RB1's injury_status --
    # RB2's own weekly stats and the underlying depth chart are byte-for-byte identical.
    assert rb2_out_points > rb2_healthy_points
