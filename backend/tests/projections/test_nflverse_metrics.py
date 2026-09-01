import pytest

from app.models import League, Player, PlayerSeasonBaseline, PlayerUsageStats, TeamDefenseStrength, TeamMatchup
from app.projections.nflverse_metrics import NflverseMetricsProvider, prior_season_weight


async def _make_league(db_session, platform: str = "espn", season: str = "2024") -> League:
    league = League(platform=platform, platform_league_id="1", season=season, name="L", status="in_season")
    db_session.add(league)
    await db_session.flush()
    return league


@pytest.mark.asyncio
async def test_provider_returns_latest_week_counts_and_recent_form_share(db_session):
    league = await _make_league(db_session)
    db_session.add_all(
        [
            PlayerUsageStats(
                platform="espn", platform_player_id="1", season="2024", week=1, targets=8, target_share=0.2, carries=0
            ),
            PlayerUsageStats(
                platform="espn", platform_player_id="1", season="2024", week=2, targets=10, target_share=0.25, carries=0
            ),
        ]
    )
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = await provider.get_metrics(db_session, league)

    assert len(metrics) == 1
    assert metrics[0].platform_player_id == "1"
    assert metrics[0].targets == 10
    # No prior-season baseline -> target_share is pure recent-form (avg of the last up-to-3 games).
    assert metrics[0].target_share == pytest.approx((0.2 + 0.25) / 2)
    assert metrics[0].season_target_share == pytest.approx((0.2 + 0.25) / 2)
    assert metrics[0].games_played == 2


@pytest.mark.asyncio
async def test_provider_computes_rising_trend(db_session):
    league = await _make_league(db_session)
    db_session.add_all(
        [
            PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=1, target_share=0.10),
            PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=2, target_share=0.30),
        ]
    )
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = await provider.get_metrics(db_session, league)

    assert metrics[0].usage_trend == "rising"


@pytest.mark.asyncio
async def test_provider_computes_falling_trend(db_session):
    league = await _make_league(db_session)
    db_session.add_all(
        [
            PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=1, target_share=0.30),
            PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=2, target_share=0.10),
        ]
    )
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = await provider.get_metrics(db_session, league)

    assert metrics[0].usage_trend == "falling"


@pytest.mark.asyncio
async def test_provider_returns_none_trend_with_only_one_week(db_session):
    league = await _make_league(db_session)
    db_session.add(
        PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=1, target_share=0.20)
    )
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = await provider.get_metrics(db_session, league)

    assert metrics[0].usage_trend is None


@pytest.mark.asyncio
async def test_provider_scopes_by_platform_and_season(db_session):
    league = await _make_league(db_session, platform="espn", season="2024")
    db_session.add_all(
        [
            PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=1, target_share=0.2),
            PlayerUsageStats(platform="sleeper", platform_player_id="1", season="2024", week=1, target_share=0.9),
            PlayerUsageStats(platform="espn", platform_player_id="1", season="2023", week=1, target_share=0.9),
        ]
    )
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = await provider.get_metrics(db_session, league)

    assert len(metrics) == 1
    assert metrics[0].target_share == 0.2


@pytest.mark.asyncio
async def test_provider_passes_through_snap_share_and_red_zone_and_injury_status(db_session):
    league = await _make_league(db_session)
    db_session.add(Player(platform="espn", platform_player_id="1", position="WR", name="P", injury_status="OUT"))
    db_session.add(
        PlayerUsageStats(
            platform="espn", platform_player_id="1", season="2024", week=1,
            snap_share=0.75, red_zone_opportunities=3,
        )
    )
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = await provider.get_metrics(db_session, league)

    assert metrics[0].snap_share == 0.75
    assert metrics[0].red_zone_opportunities == 3
    assert metrics[0].injury_status == "OUT"


@pytest.mark.asyncio
async def test_provider_computes_opponent_and_matchup_rating(db_session):
    league = await _make_league(db_session)
    league.current_week = 2
    db_session.add(Player(platform="espn", platform_player_id="1", position="WR", name="P", team="LA"))
    db_session.add(PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=1, targets=5))
    db_session.add(TeamMatchup(season="2024", week=2, team="LA", opponent="SF"))
    db_session.add_all(
        [
            TeamDefenseStrength(season="2024", team="SF", position="WR", points_allowed_avg=25.0),
            TeamDefenseStrength(season="2024", team="KC", position="WR", points_allowed_avg=5.0),
        ]
    )
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = await provider.get_metrics(db_session, league)

    assert metrics[0].opponent == "SF"
    # SF allows the most points to WRs of the two teams on record -> easiest matchup -> 100
    assert metrics[0].matchup_rating == 100.0


@pytest.mark.asyncio
async def test_provider_normalizes_sleeper_team_alias_for_matchup_lookup(db_session):
    league = await _make_league(db_session, platform="sleeper")
    league.current_week = 1
    # Sleeper reports "LAR"; the matchup/defense-strength tables use nflverse's "LA"
    db_session.add(Player(platform="sleeper", platform_player_id="1", position="WR", name="P", team="LAR"))
    db_session.add(PlayerUsageStats(platform="sleeper", platform_player_id="1", season="2024", week=1, targets=5))
    db_session.add(TeamMatchup(season="2024", week=1, team="LA", opponent="SF"))
    db_session.add(TeamDefenseStrength(season="2024", team="SF", position="WR", points_allowed_avg=25.0))
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = await provider.get_metrics(db_session, league)

    assert metrics[0].opponent == "SF"


def test_prior_season_weight_decays_by_games_played_not_calendar_weeks():
    assert prior_season_weight(0) == 1.0
    assert prior_season_weight(4) == pytest.approx(0.5)
    assert prior_season_weight(8) == 0.0
    assert prior_season_weight(12) == 0.0


@pytest.mark.asyncio
async def test_veteran_blend_shifts_from_prior_season_toward_current_as_games_accumulate(db_session):
    league = await _make_league(db_session, season="2024")
    db_session.add(Player(platform="espn", platform_player_id="1", position="WR", name="Vet", team="SF"))
    db_session.add(
        PlayerSeasonBaseline(platform="espn", platform_player_id="1", season="2023", team="SF", target_share=0.30)
    )
    await db_session.commit()

    provider = NflverseMetricsProvider()

    # Zero current-season games -> the 2023 baseline carries the value entirely (games_played=0).
    metrics = await provider.get_metrics(db_session, league)
    assert len(metrics) == 1
    assert metrics[0].target_share == pytest.approx(0.30)
    assert metrics[0].games_played == 0
    assert metrics[0].experience_status == "veteran"

    # After one game at a very different rate (0.10), the blend sits between the two, but still
    # much closer to the trusted prior-season baseline (weight=0.875 at 1 game played).
    db_session.add(PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=1, target_share=0.10))
    await db_session.commit()
    metrics = await provider.get_metrics(db_session, league)
    early_share = metrics[0].target_share
    assert 0.10 < early_share < 0.30
    assert early_share == pytest.approx(0.30 * 0.875 + 0.10 * 0.125)

    # After 8 games at the same current rate, prior_season_weight is 0 -> pure current-season recent form.
    for week in range(2, 9):
        db_session.add(
            PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=week, target_share=0.10)
        )
    await db_session.commit()
    metrics = await provider.get_metrics(db_session, league)
    assert metrics[0].target_share == pytest.approx(0.10)
    assert metrics[0].games_played == 8


@pytest.mark.asyncio
async def test_rookie_target_share_populates_as_games_accumulate_without_fake_zeros(db_session):
    league = await _make_league(db_session, season="2024")
    db_session.add(Player(platform="espn", platform_player_id="1", position="WR", name="Rookie", team="SF"))
    await db_session.commit()

    provider = NflverseMetricsProvider()

    # No games yet, no baseline -> the player doesn't even appear (nothing to report, not a fake 0).
    metrics = await provider.get_metrics(db_session, league)
    assert metrics == []

    db_session.add(PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=1, target_share=0.15))
    await db_session.commit()
    metrics = await provider.get_metrics(db_session, league)
    assert metrics[0].experience_status == "rookie_or_limited_history"
    assert metrics[0].target_share == pytest.approx(0.15)
    assert metrics[0].games_played == 1

    db_session.add(PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=2, target_share=0.25))
    db_session.add(PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=3, target_share=0.35))
    await db_session.commit()
    metrics = await provider.get_metrics(db_session, league)
    assert metrics[0].experience_status == "rookie_or_limited_history"
    assert metrics[0].games_played == 3
    assert metrics[0].target_share == pytest.approx((0.15 + 0.25 + 0.35) / 3)


@pytest.mark.asyncio
async def test_games_played_reflects_actual_games_not_weeks_elapsed(db_session):
    league = await _make_league(db_session, season="2024")
    league.current_week = 4
    db_session.add_all(
        [
            Player(platform="espn", platform_player_id="healthy", position="WR", name="Healthy"),
            Player(platform="espn", platform_player_id="hurt", position="WR", name="Hurt"),
        ]
    )
    # Both players are 4 calendar weeks into the season, but "hurt" missed weeks 2-3 (bye/injury) --
    # only 2 real usage rows exist for them, not 4.
    db_session.add_all(
        [
            PlayerUsageStats(platform="espn", platform_player_id="healthy", season="2024", week=1, target_share=0.2),
            PlayerUsageStats(platform="espn", platform_player_id="healthy", season="2024", week=2, target_share=0.2),
            PlayerUsageStats(platform="espn", platform_player_id="healthy", season="2024", week=3, target_share=0.2),
            PlayerUsageStats(platform="espn", platform_player_id="healthy", season="2024", week=4, target_share=0.2),
            PlayerUsageStats(platform="espn", platform_player_id="hurt", season="2024", week=1, target_share=0.2),
            PlayerUsageStats(platform="espn", platform_player_id="hurt", season="2024", week=4, target_share=0.2),
        ]
    )
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = {m.platform_player_id: m for m in await provider.get_metrics(db_session, league)}

    assert metrics["healthy"].games_played == 4
    assert metrics["hurt"].games_played == 2


@pytest.mark.asyncio
async def test_team_change_discounts_stale_prior_season_baseline(db_session):
    league = await _make_league(db_session, season="2024")
    # Player's 2023 baseline was earned on KC; they're now on SF -- carrying over KC's usage rate
    # would misrepresent a role that no longer exists.
    db_session.add(Player(platform="espn", platform_player_id="1", position="WR", name="Traded", team="SF"))
    db_session.add(
        PlayerSeasonBaseline(platform="espn", platform_player_id="1", season="2023", team="KC", target_share=0.35)
    )
    db_session.add(PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=1, target_share=0.12))
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = await provider.get_metrics(db_session, league)

    # Should reflect only the new team's current-season usage, not a blend with the stale KC baseline.
    assert metrics[0].target_share == pytest.approx(0.12)


@pytest.mark.asyncio
async def test_availability_reflects_injury_status_when_not_on_bye(db_session):
    league = await _make_league(db_session, season="2024")
    league.current_week = 1
    db_session.add(Player(platform="espn", platform_player_id="1", position="WR", name="P", team="SF", injury_status="Questionable"))
    db_session.add(PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=1, targets=5))
    db_session.add(TeamMatchup(season="2024", week=1, team="SF", opponent="SEA"))
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = await provider.get_metrics(db_session, league)

    assert metrics[0].availability == "questionable"


@pytest.mark.asyncio
async def test_availability_is_unavailable_on_a_bye_week_even_when_healthy(db_session):
    league = await _make_league(db_session, season="2024")
    league.current_week = 5
    db_session.add(Player(platform="espn", platform_player_id="1", position="WR", name="P", team="SF"))
    db_session.add(PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=4, targets=5))
    # Schedule for week 5 is known (some other game exists), but SF has no row -> SF is on bye.
    db_session.add(TeamMatchup(season="2024", week=5, team="KC", opponent="DEN"))
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = await provider.get_metrics(db_session, league)

    assert metrics[0].availability == "unavailable"


@pytest.mark.asyncio
async def test_availability_does_not_assume_bye_when_schedule_not_yet_synced(db_session):
    league = await _make_league(db_session, season="2024")
    league.current_week = 1
    db_session.add(Player(platform="espn", platform_player_id="1", position="WR", name="P", team="SF"))
    db_session.add(PlayerUsageStats(platform="espn", platform_player_id="1", season="2024", week=1, targets=5))
    # No TeamMatchup rows at all for this season -- schedule was never synced, so we can't know about byes.
    await db_session.commit()

    provider = NflverseMetricsProvider()
    metrics = await provider.get_metrics(db_session, league)

    assert metrics[0].availability == "healthy"
