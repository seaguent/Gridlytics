import gzip

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
    "opponent_team,fantasy_points_ppr\n"
    "00-0039075,Puka Nacua,WR,2024,REG,1,10,0.28,1,SF,20.0\n"
    "00-0039075,Puka Nacua,WR,2024,REG,2,12,0.31,0,SEA,18.0\n"
    "00-0023459,Cody White,WR,2024,REG,1,3,0.05,0,SF,10.0\n"
    "00-0011111,Someone Elsewhere,RB,2024,REG,1,6,0.10,4,SF,15.0\n"
    "00-0039075,Puka Nacua,WR,2024,POST,19,15,0.4,2,SF,30.0\n"
)

SNAP_COUNTS_CSV = "pfr_player_id,season,week,game_type,offense_pct\nNacuPu00,2024,1,REG,0.91\n"

PBP_CSV = (
    "season_type,week,yardline_100,pass_attempt,rush_attempt,receiver_player_id,rusher_player_id\n"
    "REG,1,12,1,0,00-0039075,\n"
)

SCHEDULE_CSV = "season,week,home_team,away_team\n2024,1,LA,SF\n"


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
    prior_season = str(int(season) - 1)
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_reg_{prior_season}.csv").mock(
        return_value=httpx.Response(404)
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_{prior_season}.csv").mock(
        return_value=httpx.Response(404)
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/pbp/play_by_play_{season}.csv.gz").mock(
        return_value=httpx.Response(200, content=gzip.compress(PBP_CSV.encode()))
    )
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/schedules/games.csv").mock(
        return_value=httpx.Response(200, text=SCHEDULE_CSV)
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
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/schedules/games.csv").mock(
        return_value=httpx.Response(200, text=SCHEDULE_CSV)
    )

    weekly_stats_df = pd.DataFrame(
        [
            {"season_type": "REG", "opponent_team": "SF", "position": "WR", "fantasy_points_ppr": 20.0},
            {"season_type": "REG", "opponent_team": "SF", "position": "WR", "fantasy_points_ppr": 10.0},
        ]
    )

    client = NflverseClient()
    await sync_matchup_context(db_session, client, league, weekly_stats_df)
    await client.aclose()

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
                "player_id,player_display_name,position,season_type,week,targets,target_share,carries,"
                "fantasy_points_ppr\n"
                "00-0039075,Puka Nacua,WR,REG,1,9,0.25,0,17.5\n"
                "00-0039075,Puka Nacua,WR,POST,19,5,0.2,0,9.0\n"
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

    rows = ["player_id,player_display_name,position,season_type,week,fantasy_points_ppr"]
    for player_id, scores in [
        ("rb-1", [8.0, 12.0, 4.0, 16.0]),
        ("rb-2", [16.0, 24.0, 8.0, 32.0]),
        ("rb-3", [6.0, 9.0, 3.0, 12.0]),
    ]:
        for week, score in enumerate(scores, start=1):
            rows.append(f"{player_id},Someone,RB,REG,{week},{score}")
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
