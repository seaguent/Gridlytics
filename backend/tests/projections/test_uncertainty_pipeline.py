import pytest

from app.models import League, Player, PlayerSeasonBaseline, PlayerUsageStats, PositionVolatilityPrior
from app.projections.models import PlayerProjection
from app.projections.uncertainty_pipeline import apply_uncertainty_ranges


async def _make_league(db_session, season: str = "2026", current_week: int = 5) -> League:
    league = League(
        platform="espn",
        platform_league_id="1",
        season=season,
        name="L",
        status="in_season",
        current_week=current_week,
    )
    db_session.add(league)
    await db_session.flush()
    return league


@pytest.mark.asyncio
async def test_applies_current_season_scores_when_sufficient_games_exist(db_session):
    league = await _make_league(db_session)
    for week, points in enumerate([18.0, 20.0, 16.0, 22.0, 19.0, 21.0, 17.0, 23.0], start=1):
        db_session.add(
            PlayerUsageStats(
                platform="espn", platform_player_id="p1", season="2026", week=week, fantasy_points_ppr=points
            )
        )
    league.current_week = 9
    await db_session.commit()

    projections = [
        PlayerProjection(platform_player_id="p1", name="P1", position="WR", projected_points=20.0, sources=["espn"])
    ]
    updated = await apply_uncertainty_ranges(db_session, league, projections)

    assert updated[0].range_source == "current_season"
    assert updated[0].sample_size == 8
    assert updated[0].floor is not None and updated[0].ceiling is not None


@pytest.mark.asyncio
async def test_preseason_veteran_uses_prior_season_scores(db_session):
    league = await _make_league(db_session, current_week=1)
    for week, points in enumerate([24.6, 12.1, 30.0, 18.0, 15.5, 20.0], start=1):
        db_session.add(
            PlayerUsageStats(
                platform="espn", platform_player_id="p1", season="2025", week=week, fantasy_points_ppr=points
            )
        )
    db_session.add(
        PlayerSeasonBaseline(platform="espn", platform_player_id="p1", season="2025", team="LA", target_share=0.25)
    )
    db_session.add(Player(platform="espn", platform_player_id="p1", position="WR", name="P1", team="LA"))
    await db_session.commit()

    projections = [
        PlayerProjection(platform_player_id="p1", name="P1", position="WR", projected_points=21.1, sources=["espn"])
    ]
    updated = await apply_uncertainty_ranges(db_session, league, projections)

    assert updated[0].range_source == "prior_season"
    assert updated[0].sample_size == 6


@pytest.mark.asyncio
async def test_team_change_discounts_prior_season_history(db_session):
    league = await _make_league(db_session, current_week=1)
    for week, points in enumerate([24.6, 12.1, 30.0, 18.0, 15.5, 20.0], start=1):
        db_session.add(
            PlayerUsageStats(
                platform="espn", platform_player_id="p1", season="2025", week=week, fantasy_points_ppr=points
            )
        )
    db_session.add(
        PlayerSeasonBaseline(platform="espn", platform_player_id="p1", season="2025", team="LA", target_share=0.25)
    )
    # Player is now on a different team -- prior team's volatility shouldn't carry over.
    db_session.add(Player(platform="espn", platform_player_id="p1", position="WR", name="P1", team="SEA"))
    await db_session.commit()

    projections = [
        PlayerProjection(platform_player_id="p1", name="P1", position="WR", projected_points=21.1, sources=["espn"])
    ]
    updated = await apply_uncertainty_ranges(db_session, league, projections)

    assert updated[0].range_source is None


@pytest.mark.asyncio
async def test_rookie_falls_back_to_position_prior(db_session):
    league = await _make_league(db_session, current_week=1)
    db_session.add(
        PositionVolatilityPrior(season="2025", position="RB", low_ratio=0.6, high_ratio=1.4, sample_size=850)
    )
    await db_session.commit()

    projections = [
        PlayerProjection(platform_player_id="rookie1", name="R1", position="RB", projected_points=12.0, sources=["espn"])
    ]
    updated = await apply_uncertainty_ranges(db_session, league, projections)

    assert updated[0].range_source == "position_prior"
    assert updated[0].sample_size == 850
    assert updated[0].floor == pytest.approx(12.0 * 0.6)
    assert updated[0].ceiling == pytest.approx(12.0 * 1.4)


@pytest.mark.asyncio
async def test_insufficient_history_and_no_position_prior_leaves_range_none(db_session):
    league = await _make_league(db_session, current_week=1)
    await db_session.commit()

    projections = [
        PlayerProjection(platform_player_id="p1", name="P1", position="TE", projected_points=5.0, sources=["espn"])
    ]
    updated = await apply_uncertainty_ranges(db_session, league, projections)

    assert updated[0].range_source is None
    assert updated[0].floor is None


@pytest.mark.asyncio
async def test_returns_empty_list_unchanged(db_session):
    league = await _make_league(db_session)
    assert await apply_uncertainty_ranges(db_session, league, []) == []
