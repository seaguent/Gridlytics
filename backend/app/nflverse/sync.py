import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    League,
    Player,
    PlayerSeasonBaseline,
    PlayerUsageStats,
    PositionVolatilityPrior,
    ProjectionRecord,
    RosterSlot,
    Team,
    TeamDefenseStrength,
    TeamMatchup,
)
from app.nflverse.aggregations import (
    compute_position_defense_strength,
    compute_position_volatility_priors,
    compute_red_zone_opportunities,
)
from app.nflverse.client import NflverseClient
from app.nflverse.crosswalk import (
    MANUAL_SLEEPER_OVERRIDES,
    build_espn_lookup,
    build_name_position_lookup,
    build_pfr_lookup,
    build_sleeper_lookup,
    normalize_name,
    normalize_team,
)
from app.projections.availability import classify_availability
from app.projections.blending import prior_season_weight
from app.projections.comparative_backtest import _week_as_of_date
from app.projections.context_aware.career_prior import compute_career_prior
from app.projections.context_aware.career_prior_sync import build_career_seasons, fetch_season_stats_range
from app.projections.context_aware.depth_chart import RoleInfo, load_current_roles_batch
from app.projections.context_aware.effective_role import (
    TeammateStatus,
    compute_effective_pos_rank,
    load_same_position_groups,
)
from app.projections.context_aware.model import (
    CareerAwareBreakdown,
    add_share_columns,
    compute_share_priors_by_rank,
    project_context_aware_points_detailed_v2,
)
from app.projections.context_aware.qb_context import compute_qb_context
from app.projections.context_aware.team_context import TeamTendencies, compute_team_tendencies_v2
from app.projections.context_aware.team_prior import LOOKBACK_SEASONS, RECENCY_DECAY, compute_team_prior_by_team
from app.projections.native.categories import POSITION_CATEGORIES
from app.projections.native.model import (
    CategoryBreakdown,
    NativeProjectionBreakdown,
    compute_all_position_priors,
    project_player_points_detailed,
)
from app.projections.scoring_rules import scoring_rules_for_league


def _clean_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _clean_int(value) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


async def _rostered_player_ids(session: AsyncSession, league: League) -> set[str]:
    result = await session.execute(
        select(RosterSlot.platform_player_id)
        .join(Team, RosterSlot.team_id == Team.id)
        .where(Team.league_id == league.id)
        .distinct()
    )
    return {row[0] for row in result.all()}


def _player_to_gsis_map_espn(rostered_player_ids: set[str], crosswalk: pd.DataFrame) -> dict[str, str]:
    espn_lookup = build_espn_lookup(crosswalk)
    return {pid: espn_lookup[pid] for pid in rostered_player_ids if pid in espn_lookup}


async def _player_to_gsis_map_sleeper(
    session: AsyncSession,
    league: League,
    rostered_player_ids: set[str],
    crosswalk: pd.DataFrame,
    sleeper_crosswalk: pd.DataFrame,
) -> dict[str, str]:
    result = await session.execute(
        select(Player).where(
            Player.platform == league.platform,
            Player.platform_player_id.in_(rostered_player_ids),
        )
    )
    players = {player.platform_player_id: player for player in result.scalars()}

    sleeper_lookup = build_sleeper_lookup(sleeper_crosswalk)
    name_position_lookup = build_name_position_lookup(crosswalk)

    player_to_gsis: dict[str, str] = {}
    for platform_player_id in rostered_player_ids:
        override = MANUAL_SLEEPER_OVERRIDES.get(platform_player_id)
        if override:
            player_to_gsis[platform_player_id] = override
            continue

        player = players.get(platform_player_id)
        if player is None:
            continue

        if player.gsis_id:
            player_to_gsis[platform_player_id] = player.gsis_id
            continue

        gsis_id = sleeper_lookup.get(platform_player_id)
        if gsis_id:
            player_to_gsis[platform_player_id] = gsis_id
            continue

        gsis_id = name_position_lookup.get((normalize_name(player.name), player.position.upper()))
        if gsis_id:
            player_to_gsis[platform_player_id] = gsis_id

    return player_to_gsis


def _snap_share_lookup(snap_counts: pd.DataFrame, crosswalk: pd.DataFrame) -> dict[tuple[str, int], float]:
    if snap_counts.empty:
        return {}

    pfr_lookup = build_pfr_lookup(crosswalk)
    regular_season = snap_counts[snap_counts["game_type"] == "REG"]

    lookup: dict[tuple[str, int], float] = {}
    for _, row in regular_season.iterrows():
        gsis_id = pfr_lookup.get(row.get("pfr_player_id"))
        offense_pct = row.get("offense_pct")
        if gsis_id is None or pd.isna(offense_pct):
            continue
        lookup[(gsis_id, int(row["week"]))] = float(offense_pct)
    return lookup


def _red_zone_lookup(pbp: pd.DataFrame) -> dict[tuple[str, int], int]:
    red_zone_df = compute_red_zone_opportunities(pbp)
    return {
        (row["gsis_id"], int(row["week"])): int(row["red_zone_opportunities"])
        for _, row in red_zone_df.iterrows()
    }


async def sync_player_season_baseline(
    session: AsyncSession, client: NflverseClient, league: League, gsis_to_players: dict[str, list[str]]
) -> None:
    prior_season = str(int(league.season) - 1)
    season_stats = await client.get_season_stats(prior_season)
    if season_stats.empty:
        return

    relevant = season_stats[season_stats["player_id"].isin(gsis_to_players.keys())]

    for _, row in relevant.iterrows():
        gsis_id = row["player_id"]
        target_share = _clean_float(row.get("target_share"))
        team = row.get("recent_team")
        team = None if pd.isna(team) else team

        for platform_player_id in gsis_to_players[gsis_id]:
            result = await session.execute(
                select(PlayerSeasonBaseline).where(
                    PlayerSeasonBaseline.platform == league.platform,
                    PlayerSeasonBaseline.platform_player_id == platform_player_id,
                    PlayerSeasonBaseline.season == prior_season,
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                session.add(
                    PlayerSeasonBaseline(
                        platform=league.platform,
                        platform_player_id=platform_player_id,
                        season=prior_season,
                        team=team,
                        target_share=target_share,
                    )
                )
            else:
                record.team = team
                record.target_share = target_share

    await session.commit()


async def _upsert_usage_stats_row(
    session: AsyncSession,
    league: League,
    platform_player_id: str,
    season: str,
    week: int,
    *,
    targets: int | None = None,
    target_share: float | None = None,
    carries: int | None = None,
    snap_share: float | None = None,
    red_zone_opportunities: int | None = None,
    fantasy_points_ppr: float | None = None,
) -> None:
    result = await session.execute(
        select(PlayerUsageStats).where(
            PlayerUsageStats.platform == league.platform,
            PlayerUsageStats.platform_player_id == platform_player_id,
            PlayerUsageStats.season == season,
            PlayerUsageStats.week == week,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        session.add(
            PlayerUsageStats(
                platform=league.platform,
                platform_player_id=platform_player_id,
                season=season,
                week=week,
                targets=targets,
                target_share=target_share,
                carries=carries,
                snap_share=snap_share,
                red_zone_opportunities=red_zone_opportunities,
                fantasy_points_ppr=fantasy_points_ppr,
            )
        )
    else:
        record.targets = targets
        record.target_share = target_share
        record.carries = carries
        record.snap_share = snap_share
        record.red_zone_opportunities = red_zone_opportunities
        record.fantasy_points_ppr = fantasy_points_ppr


async def sync_position_volatility_priors(session: AsyncSession, season: str, weekly_stats: pd.DataFrame) -> None:
    priors = compute_position_volatility_priors(weekly_stats)
    for position, (low_ratio, high_ratio, sample_size) in priors.items():
        result = await session.execute(
            select(PositionVolatilityPrior).where(
                PositionVolatilityPrior.season == season,
                PositionVolatilityPrior.position == position,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            session.add(
                PositionVolatilityPrior(
                    season=season,
                    position=position,
                    low_ratio=low_ratio,
                    high_ratio=high_ratio,
                    sample_size=sample_size,
                )
            )
        else:
            record.low_ratio = low_ratio
            record.high_ratio = high_ratio
            record.sample_size = sample_size

    await session.commit()


def _dominant_category(breakdown: NativeProjectionBreakdown | CareerAwareBreakdown):
    # Works unchanged for either breakdown type -- both list a `.categories` sequence whose
    # entries carry `.name`/`.expected_opportunities` (CategoryBreakdown and CategoryShareBreakdown
    # respectively), the only two fields this needs.
    if not breakdown.categories:
        return None
    # Ties prefer the first-listed category for that position -- breakdown.categories already
    # preserves POSITION_CATEGORIES' order since it's built in that same loop order.
    best = breakdown.categories[0]
    for category in breakdown.categories[1:]:
        if (category.expected_opportunities or 0) > (best.expected_opportunities or 0):
            best = category
    return best


async def sync_context_aware_projections(
    session: AsyncSession,
    league: League,
    weekly_stats: pd.DataFrame,
    prior_weekly_stats: pd.DataFrame,
    team_weekly_by_year: dict[int, pd.DataFrame],
    season_stats_by_year: dict[int, pd.DataFrame],
    depth_charts: pd.DataFrame,
    schedule: pd.DataFrame,
    rostered_player_ids: set[str],
    player_to_gsis: dict[str, str],
) -> None:
    """The native model is kept only as a fallback for players the context-aware model has no evidence for."""
    combined = pd.concat([prior_weekly_stats, weekly_stats], ignore_index=True) if not prior_weekly_stats.empty else weekly_stats
    if combined.empty:
        # No real nflverse data of any kind -- never fabricate an all-zero projection.
        return
    combined_with_shares = add_share_columns(combined)

    season = int(league.season)
    before_week = league.current_week
    position_priors = compute_all_position_priors(combined, season=season, before_week=before_week)
    scoring_rules = scoring_rules_for_league(league.platform, league.scoring_settings)

    result = await session.execute(
        select(Player).where(Player.platform == league.platform, Player.platform_player_id.in_(rostered_player_ids))
    )
    players_by_id = {p.platform_player_id: p for p in result.scalars()}
    # Injury/availability for same-position teammates, scoped to this league's already-rostered
    # players (player_to_gsis and players_by_id are already loaded for exactly that set -- no
    # new query, no new ingestion). A teammate outside that set (e.g. a true free-agent starter
    # on ESPN) simply won't appear here; compute_effective_pos_rank treats an unresolved
    # teammate as available, so it's a silent no-promotion, not a wrong one.
    availability_by_gsis: dict[str, str] = {
        gsis_id: classify_availability(players_by_id[pid].injury_status, is_bye=False)
        for pid, gsis_id in player_to_gsis.items()
        if pid in players_by_id
    }

    result = await session.execute(
        select(PlayerSeasonBaseline).where(
            PlayerSeasonBaseline.platform == league.platform,
            PlayerSeasonBaseline.season == str(season - 1),
        )
    )
    baseline_by_player = {row.platform_player_id: row for row in result.scalars()}

    # Multi-year team prior replaces the brittle single-season carry-forward for every
    # context-aware category.
    multi_year_team_prior_by_team = compute_team_prior_by_team(
        team_weekly_by_year, target_season=season, lookback=LOOKBACK_SEASONS, decay=RECENCY_DECAY,
    )
    team_tendencies_v2 = compute_team_tendencies_v2(
        combined_with_shares, multi_year_team_prior_by_team, season=season, before_week=before_week,
    )

    as_of_date = _week_as_of_date(schedule, season, before_week)
    roles_batch = load_current_roles_batch(depth_charts, as_of_date) if as_of_date is not None else {}
    teammate_groups = load_same_position_groups(depth_charts, as_of_date) if as_of_date is not None else {}
    share_priors_by_rank = (
        compute_share_priors_by_rank(combined_with_shares, depth_charts, season=season, before_week=before_week, as_of_date=as_of_date)
        if as_of_date is not None else {}
    )
    teams_with_rostered_players = {
        normalize_team(player.team) for player in players_by_id.values() if player.team
    }
    qb_context_by_team = (
        {
            team: compute_qb_context(
                current_team=team, prior_season_team=team,
                weekly_stats=combined, prior_weekly_stats=combined,
                depth_charts=depth_charts, as_of_date=as_of_date, season=season, before_week=before_week,
            )
            for team in teams_with_rostered_players
        }
        if as_of_date is not None else {}
    )

    for platform_player_id in rostered_player_ids:
        player = players_by_id.get(platform_player_id)
        # Position must come from the app's own already-synced Player.position, not from
        # nflverse rows -- a true zero-history rookie has no nflverse rows at all, and must
        # still get a position-prior-based projection, not be silently skipped.
        if player is None or player.position not in POSITION_CATEGORIES:
            continue

        gsis_id = player_to_gsis.get(platform_player_id)
        current_games: list[dict] = []
        prior_games: list[dict] = []
        if gsis_id:
            current_games = combined_with_shares[
                (combined_with_shares["player_id"] == gsis_id) & (combined_with_shares["season"] == season)
                & (combined_with_shares["season_type"] == "REG") & (combined_with_shares["week"] < before_week)
            ].sort_values("week").to_dict("records")
            prior_games = combined_with_shares[
                (combined_with_shares["player_id"] == gsis_id) & (combined_with_shares["season"] == season - 1)
                & (combined_with_shares["season_type"] == "REG")
            ].sort_values("week").to_dict("records")

        baseline = baseline_by_player.get(platform_player_id)
        current_team = normalize_team(player.team)
        prior_season_team = normalize_team(baseline.team) if baseline else None
        team_changed = bool(current_team and prior_season_team and current_team != prior_season_team)

        native_breakdown = project_player_points_detailed(
            player.position, current_games, prior_games or None, position_priors.get(player.position, {}), team_changed,
            scoring_rules=scoring_rules,
        )

        breakdown_new: CareerAwareBreakdown | None = None
        if gsis_id and current_team is not None:
            limited_seasons = {s: df for s, df in season_stats_by_year.items() if season - LOOKBACK_SEASONS <= s < season}
            career_seasons = build_career_seasons(limited_seasons, gsis_id, season)
            role = roles_batch.get((gsis_id, player.position))
            if role is None:
                fallback_confidence = "low" if roles_batch else "unknown"
                role = RoleInfo(pos_rank=None, role_confidence=fallback_confidence, role_changed_recently=False)

            # role.pos_rank stays the untouched, real nflverse depth-chart rank -- projection_role
            # is a separate, additively-derived value, never a mutation of role/roles_batch.
            projection_role = role
            room = teammate_groups.get((current_team, player.position), [])
            if room:
                teammates = [
                    TeammateStatus(
                        gsis_id=teammate_gsis_id,
                        pos_rank=roles_batch[(teammate_gsis_id, player.position)].pos_rank
                        if (teammate_gsis_id, player.position) in roles_batch else None,
                        availability_status=availability_by_gsis.get(teammate_gsis_id, "healthy"),
                    )
                    for teammate_gsis_id in room
                ]
                effective_rank = compute_effective_pos_rank(gsis_id, role.pos_rank, teammates)
                if effective_rank != role.pos_rank:
                    projection_role = RoleInfo(
                        pos_rank=effective_rank,
                        role_confidence=role.role_confidence,
                        role_changed_recently=role.role_changed_recently,
                    )

            qb_context = qb_context_by_team.get(current_team)
            if qb_context is not None:
                # No QB-change workload discount -- a directional test found no consistent effect
                # on team pass volume. qb_changed stays purely informational, surfaced via the
                # breakdown/qb_context.
                career_prior = compute_career_prior(
                    career_seasons, team_changed=team_changed, role_changed_recently=role.role_changed_recently,
                )
                tendencies = team_tendencies_v2.get(current_team, TeamTendencies(None, None))
                breakdown_new = project_context_aware_points_detailed_v2(
                    player.position, current_games, prior_games or None, career_prior, career_seasons,
                    tendencies, projection_role, qb_context, share_priors_by_rank, position_priors.get(player.position, {}),
                    current_team=current_team, prior_season_team=prior_season_team,
                    platform_points=None, availability_status="healthy", scoring_rules=scoring_rules,
                )

        if breakdown_new is not None and breakdown_new.total_points is not None:
            projected_points = breakdown_new.total_points
            dominant = _dominant_category(breakdown_new)
        elif native_breakdown is not None:
            # The context-aware model genuinely had nothing to say (e.g. unknown depth-chart rank
            # with zero career and zero current-season evidence) -- fall back to native's own
            # position-average-based projection rather than silently skipping a rostered player.
            projected_points = native_breakdown.total_points
            dominant = _dominant_category(native_breakdown)
        else:
            continue

        # Same games-played-based blend weight either model actually used internally (current-
        # season stats progressively outweigh prior-season/career priors as real games accumulate)
        # -- real, computed here, not a fabricated per-category value.
        prior_weight = prior_season_weight(len(current_games))
        expected_opportunities = dominant.expected_opportunities if dominant else None
        dominant_category = dominant.name if dominant else None

        result = await session.execute(
            select(ProjectionRecord).where(
                ProjectionRecord.league_id == league.id,
                ProjectionRecord.platform_player_id == platform_player_id,
                ProjectionRecord.week == league.current_week,
                ProjectionRecord.source == "gridlytics",
            )
        )
        record = result.scalar_one_or_none()

        if record is None:
            session.add(
                ProjectionRecord(
                    league_id=league.id,
                    platform_player_id=platform_player_id,
                    week=league.current_week,
                    source="gridlytics",
                    name=player.name,
                    position=player.position,
                    projected_points=projected_points,
                    expected_opportunities=expected_opportunities,
                    prior_season_weight=prior_weight,
                    dominant_category=dominant_category,
                )
            )
        else:
            record.name = player.name
            record.position = player.position
            record.projected_points = projected_points
            record.expected_opportunities = expected_opportunities
            record.prior_season_weight = prior_weight
            record.dominant_category = dominant_category

    await session.commit()


async def sync_matchup_context(
    session: AsyncSession, league: League, weekly_stats: pd.DataFrame, schedule: pd.DataFrame
) -> None:
    defense_strength = compute_position_defense_strength(weekly_stats)
    for _, row in defense_strength.iterrows():
        result = await session.execute(
            select(TeamDefenseStrength).where(
                TeamDefenseStrength.season == league.season,
                TeamDefenseStrength.team == row["opponent_team"],
                TeamDefenseStrength.position == row["position"],
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            session.add(
                TeamDefenseStrength(
                    season=league.season,
                    team=row["opponent_team"],
                    position=row["position"],
                    points_allowed_avg=row["points_allowed_avg"],
                )
            )
        else:
            record.points_allowed_avg = row["points_allowed_avg"]

    for _, row in schedule.iterrows():
        week = int(row["week"])
        for team, opponent in ((row["home_team"], row["away_team"]), (row["away_team"], row["home_team"])):
            result = await session.execute(
                select(TeamMatchup).where(
                    TeamMatchup.season == league.season,
                    TeamMatchup.week == week,
                    TeamMatchup.team == team,
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                session.add(TeamMatchup(season=league.season, week=week, team=team, opponent=opponent))
            else:
                record.opponent = opponent

    await session.commit()


async def sync_usage_stats(session: AsyncSession, client: NflverseClient, league: League) -> None:
    rostered_player_ids = await _rostered_player_ids(session, league)
    if not rostered_player_ids:
        return

    # Prior-season baseline sync below must not depend on the CURRENT season's file existing yet.
    weekly_stats = await client.get_weekly_stats(league.season)
    schedule = await client.get_schedule(league.season)
    await sync_matchup_context(session, league, weekly_stats, schedule)

    crosswalk = await client.get_player_crosswalk()

    if league.platform == "espn":
        player_to_gsis = _player_to_gsis_map_espn(rostered_player_ids, crosswalk)
    else:
        sleeper_crosswalk = await client.get_sleeper_crosswalk()
        player_to_gsis = await _player_to_gsis_map_sleeper(
            session, league, rostered_player_ids, crosswalk, sleeper_crosswalk
        )

    if not player_to_gsis:
        return

    gsis_to_players: dict[str, list[str]] = {}
    for platform_player_id, gsis_id in player_to_gsis.items():
        gsis_to_players.setdefault(gsis_id, []).append(platform_player_id)

    await sync_player_season_baseline(session, client, league, gsis_to_players)

    prior_season = str(int(league.season) - 1)
    prior_weekly_stats = await client.get_weekly_stats(prior_season)
    if not prior_weekly_stats.empty:
        await sync_position_volatility_priors(session, prior_season, prior_weekly_stats)

        prior_relevant = prior_weekly_stats[
            (prior_weekly_stats["player_id"].isin(gsis_to_players.keys()))
            & (prior_weekly_stats["season_type"] == "REG")
        ]
        for _, row in prior_relevant.iterrows():
            gsis_id = row["player_id"]
            for platform_player_id in gsis_to_players[gsis_id]:
                await _upsert_usage_stats_row(
                    session,
                    league,
                    platform_player_id,
                    prior_season,
                    int(row["week"]),
                    targets=_clean_int(row.get("targets")),
                    target_share=_clean_float(row.get("target_share")),
                    carries=_clean_int(row.get("carries")),
                    fantasy_points_ppr=_clean_float(row.get("fantasy_points_ppr")),
                )
        await session.commit()

    season = int(league.season)
    depth_charts = await client.get_depth_charts(league.season)
    season_stats_by_year = await fetch_season_stats_range(client, current_season=season, lookback=LOOKBACK_SEASONS)

    # Multi-year team-volume history for the validated team prior -- season-1 is already fetched
    # above (prior_weekly_stats); LOOKBACK_SEASONS-1 more real seasons back are needed too.
    team_weekly_by_year: dict[int, pd.DataFrame] = {}
    if not prior_weekly_stats.empty:
        team_weekly_by_year[season - 1] = prior_weekly_stats
    for offset in range(2, LOOKBACK_SEASONS + 1):
        year = season - offset
        df = await client.get_weekly_stats(str(year))
        if not df.empty:
            team_weekly_by_year[year] = df

    await sync_context_aware_projections(
        session, league, weekly_stats, prior_weekly_stats, team_weekly_by_year, season_stats_by_year,
        depth_charts, schedule, rostered_player_ids, player_to_gsis,
    )

    if weekly_stats.empty:
        return

    snap_counts = await client.get_snap_counts(league.season)
    pbp = await client.get_play_by_play(league.season)
    snap_lookup = _snap_share_lookup(snap_counts, crosswalk)
    red_zone_lookup = _red_zone_lookup(pbp)

    relevant = weekly_stats[
        (weekly_stats["player_id"].isin(gsis_to_players.keys())) & (weekly_stats["season_type"] == "REG")
    ]

    for _, row in relevant.iterrows():
        week = int(row["week"])
        gsis_id = row["player_id"]
        targets = _clean_int(row.get("targets"))
        target_share = _clean_float(row.get("target_share"))
        carries = _clean_int(row.get("carries"))
        snap_share = snap_lookup.get((gsis_id, week))
        red_zone_opportunities = red_zone_lookup.get((gsis_id, week))
        fantasy_points_ppr = _clean_float(row.get("fantasy_points_ppr"))

        for platform_player_id in gsis_to_players[gsis_id]:
            await _upsert_usage_stats_row(
                session,
                league,
                platform_player_id,
                league.season,
                week,
                targets=targets,
                target_share=target_share,
                carries=carries,
                snap_share=snap_share,
                red_zone_opportunities=red_zone_opportunities,
                fantasy_points_ppr=fantasy_points_ppr,
            )

    await session.commit()
