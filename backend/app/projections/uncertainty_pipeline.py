from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League, Player, PlayerSeasonBaseline, PlayerUsageStats, PositionVolatilityPrior
from app.nflverse.crosswalk import normalize_team
from app.projections.models import PlayerProjection
from app.projections.uncertainty import compute_uncertainty_range


async def _scores_by_player(
    session: AsyncSession, league: League, season: str, platform_player_ids: list[str], *, before_week: int | None
) -> dict[str, list[float]]:
    conditions = [
        PlayerUsageStats.platform == league.platform,
        PlayerUsageStats.season == season,
        PlayerUsageStats.platform_player_id.in_(platform_player_ids),
    ]
    if before_week is not None:
        conditions.append(PlayerUsageStats.week < before_week)

    result = await session.execute(
        select(PlayerUsageStats.platform_player_id, PlayerUsageStats.fantasy_points_ppr).where(*conditions)
    )
    scores: dict[str, list[float]] = {}
    for platform_player_id, points in result.all():
        if points is not None:
            scores.setdefault(platform_player_id, []).append(points)
    return scores


async def apply_uncertainty_ranges(
    session: AsyncSession, league: League, projections: list[PlayerProjection]
) -> list[PlayerProjection]:
    if not projections:
        return projections

    platform_player_ids = [p.platform_player_id for p in projections]
    prior_season = str(int(league.season) - 1)

    current_scores = await _scores_by_player(
        session, league, league.season, platform_player_ids, before_week=league.current_week
    )
    prior_scores = await _scores_by_player(session, league, prior_season, platform_player_ids, before_week=None)

    result = await session.execute(
        select(PlayerSeasonBaseline).where(
            PlayerSeasonBaseline.platform == league.platform,
            PlayerSeasonBaseline.season == prior_season,
            PlayerSeasonBaseline.platform_player_id.in_(platform_player_ids),
        )
    )
    baseline_by_player = {row.platform_player_id: row for row in result.scalars()}

    result = await session.execute(
        select(Player).where(
            Player.platform == league.platform, Player.platform_player_id.in_(platform_player_ids)
        )
    )
    player_by_id = {player.platform_player_id: player for player in result.scalars()}

    result = await session.execute(
        select(PositionVolatilityPrior).where(PositionVolatilityPrior.season == prior_season)
    )
    position_priors = {row.position: (row.low_ratio, row.high_ratio, row.sample_size) for row in result.scalars()}

    updated = []
    for projection in projections:
        platform_player_id = projection.platform_player_id
        baseline = baseline_by_player.get(platform_player_id)
        player = player_by_id.get(platform_player_id)
        current_team = normalize_team(player.team) if player else None
        baseline_team = normalize_team(baseline.team) if baseline else None
        team_changed = bool(current_team and baseline_team and current_team != baseline_team)

        uncertainty = compute_uncertainty_range(
            projected_points=projection.projected_points,
            current_season_scores=current_scores.get(platform_player_id, []),
            prior_season_scores=prior_scores.get(platform_player_id) or None,
            position_prior=position_priors.get(projection.position),
            team_changed=team_changed,
        )
        updated.append(
            replace(
                projection,
                floor=uncertainty.floor,
                ceiling=uncertainty.ceiling,
                confidence=uncertainty.confidence,
                range_source=uncertainty.range_source,
                sample_size=uncertainty.sample_size,
            )
        )
    return updated
