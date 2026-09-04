from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.lineup import find_optimal_lineup
from app.analytics.roster import NON_STARTING_SLOTS
from app.models import League, LeagueConnection, Player, ProjectionRecord, RosterSlot, Team
from app.nflverse.client import NflverseClient
from app.nflverse.crosswalk import build_espn_lookup
from app.projections.availability import classify_availability
from app.projections.available_players import (
    AvailablePlayerCandidate,
    EspnAvailablePlayerProvider,
    SleeperAvailablePlayerProvider,
)
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
    add_share_columns,
    compute_share_priors_by_rank,
    project_context_aware_points_detailed_v2,
)
from app.projections.context_aware.qb_context import compute_qb_context
from app.projections.context_aware.team_context import TeamTendencies, compute_team_tendencies_v2
from app.projections.context_aware.team_prior import LOOKBACK_SEASONS, RECENCY_DECAY, compute_team_prior_by_team
from app.projections.final_projection import compute_final_projection
from app.projections.models import PlayerProjection
from app.projections.native.categories import POSITION_CATEGORIES
from app.projections.native.model import compute_all_position_priors
from app.projections.start_sit import build_explanation
from app.projections.value import compute_value_over_replacement

TOP_N_PER_POSITION = 15
MAX_DROP_CANDIDATES_PER_WAIVER = 5

REAL_ROLE_MAX_RANK = 2


def _rank_key(
    candidate: AvailablePlayerCandidate,
    recent_usage_by_gsis: dict[str, float],
    roles_by_gsis_position: dict[tuple[str, str], RoleInfo],
) -> tuple[float, float, float] | None:
    if candidate.platform_projection is not None:
        return (2.0, candidate.platform_projection, 0.0)

    usage = recent_usage_by_gsis.get(candidate.gsis_id) if candidate.gsis_id else None
    if usage:
        return (1.0, usage, 0.0)

    role = roles_by_gsis_position.get((candidate.gsis_id, candidate.position)) if candidate.gsis_id else None
    if role is not None and role.pos_rank is not None and role.pos_rank <= REAL_ROLE_MAX_RANK:
        return (0.0, 1.0 / role.pos_rank, 0.0)

    return None


def rank_and_narrow_candidates(
    candidates: list[AvailablePlayerCandidate],
    recent_usage_by_gsis: dict[str, float],
    roles_by_gsis_position: dict[tuple[str, str], RoleInfo],
) -> list[AvailablePlayerCandidate]:
    keyed = []
    for candidate in candidates:
        key = _rank_key(candidate, recent_usage_by_gsis, roles_by_gsis_position)
        if key is not None:
            keyed.append((key, candidate))

    by_position: dict[str, list[tuple[tuple[float, float, float], AvailablePlayerCandidate]]] = {}
    for key, candidate in keyed:
        by_position.setdefault(candidate.position, []).append((key, candidate))

    result = []
    for position_candidates in by_position.values():
        position_candidates.sort(key=lambda pair: pair[0], reverse=True)
        result.extend(candidate for _, candidate in position_candidates[:TOP_N_PER_POSITION])
    return result


@dataclass
class WaiverTransaction:
    candidate_player_id: str
    improvement: float
    drop_player_id: str | None
    drop_name: str | None


def _plausible_drop_set(roster_candidates: list[dict], bench_ids: set[str], candidate_position: str) -> list[dict]:
    bench = [p for p in roster_candidates if p["player_id"] in bench_ids]
    lowest_value = sorted(bench, key=lambda p: p["points"])[:3]
    same_position = sorted(
        [p for p in bench if p["position"] == candidate_position], key=lambda p: p["points"]
    )[:3]

    seen: set[str] = set()
    drops: list[dict] = []
    for player in lowest_value + same_position:
        if player["player_id"] not in seen:
            seen.add(player["player_id"])
            drops.append(player)
    return drops[:MAX_DROP_CANDIDATES_PER_WAIVER]


def simulate_best_transaction(
    roster_candidates: list[dict],
    current_optimal_points: float,
    current_assignment: list[tuple[str, str]],
    starting_slots: list[str],
    candidate: dict,
    roster_names_by_id: dict[str, str],
) -> WaiverTransaction | None:
    started_ids = {player_id for _, player_id in current_assignment}
    bench_ids = {p["player_id"] for p in roster_candidates if p["player_id"] not in started_ids}

    drop_options = _plausible_drop_set(roster_candidates, bench_ids, candidate["position"])
    if not drop_options:
        return None

    best_drop = None
    best_improvement = float("-inf")
    for drop in drop_options:
        hypothetical = [p for p in roster_candidates if p["player_id"] != drop["player_id"]] + [candidate]
        _, new_points = find_optimal_lineup(hypothetical, starting_slots)
        improvement = new_points - current_optimal_points
        if improvement > best_improvement:
            best_improvement = improvement
            best_drop = drop

    return WaiverTransaction(
        candidate_player_id=candidate["player_id"],
        improvement=best_improvement,
        drop_player_id=best_drop["player_id"],
        drop_name=roster_names_by_id.get(best_drop["player_id"], best_drop["player_id"]),
    )


async def compute_waiver_recommendations(
    session: AsyncSession,
    league: League,
    connection: LeagueConnection,
    raw_free_agents_data: dict | None = None,
) -> dict:
    if league.platform not in ("sleeper", "espn"):
        return {"mode": "unsupported_platform", "recommendations": []}

    mode = "projection_only" if connection.my_team_id is None else "lineup_comparison"

    # espn_to_gsis (ESPN's own numeric player id -> gsis_id) is loaded exactly once per request,
    # right here, and reused for two different things below: resolving free-agent candidate
    # identity (handed to the provider instead of it fetching /players.csv itself) and resolving
    # rostered ESPN teammates' Player rows for the effective-role availability lookup further
    # down. Stays None for Sleeper, which doesn't need it -- Sleeper's own gsis_id is already
    # directly on the Player row.
    espn_to_gsis: dict[str, str] | None = None
    if league.platform == "sleeper":
        sleeper_provider = SleeperAvailablePlayerProvider()
        all_candidates = await sleeper_provider.get_available_players(session, league)
    else:
        crosswalk_client = NflverseClient()
        try:
            crosswalk = await crosswalk_client.get_player_crosswalk()
        finally:
            await crosswalk_client.aclose()
        espn_to_gsis = build_espn_lookup(crosswalk)
        espn_provider = EspnAvailablePlayerProvider(espn_lookup=espn_to_gsis)
        all_candidates = await espn_provider.get_available_players(session, league, raw_free_agents_data)
    if not all_candidates:
        return {"mode": mode, "recommendations": []}

    client = NflverseClient()
    try:
        season = int(league.season)
        weekly_years: dict[int, pd.DataFrame] = {}
        for offset in range(0, LOOKBACK_SEASONS + 1):
            year = season - offset
            df = await client.get_weekly_stats(str(year))
            if not df.empty:
                weekly_years[year] = df
        weekly_stats = pd.concat(list(weekly_years.values()), ignore_index=True) if weekly_years else pd.DataFrame()
        weekly_with_shares = add_share_columns(weekly_stats) if not weekly_stats.empty else weekly_stats

        season_stats_by_year = await fetch_season_stats_range(client, current_season=season, lookback=LOOKBACK_SEASONS)
        depth_charts = await client.get_depth_charts(league.season)
        schedule = await client.get_schedule(league.season)
    finally:
        await client.aclose()

    as_of_date = _week_as_of_date(schedule, season, league.current_week)

    recent_usage_by_gsis: dict[str, float] = {}
    if not weekly_stats.empty:
        reg = weekly_stats[
            (weekly_stats["season_type"] == "REG") & (weekly_stats["season"] == season)
            & (weekly_stats["week"] < league.current_week)
        ]
        if not reg.empty:
            for gsis_id, group in reg.groupby("player_id"):
                targets = group["targets"].fillna(0) if "targets" in group else 0
                carries = group["carries"].fillna(0) if "carries" in group else 0
                recent_usage_by_gsis[gsis_id] = float((targets + carries).mean())

    roles_by_gsis_position = load_current_roles_batch(depth_charts, as_of_date) if as_of_date else {}
    teammate_groups = load_same_position_groups(depth_charts, as_of_date) if as_of_date else {}

    narrowed = rank_and_narrow_candidates(all_candidates, recent_usage_by_gsis, roles_by_gsis_position)
    if not narrowed:
        return {"mode": mode, "recommendations": []}

    # Teammate availability for the effective-role adjustment below, scoped to only the gsis_ids
    # actually needed (one batched query, not one per candidate). Player.gsis_id is directly
    # populated for every Sleeper player (the universal sync in app/sleeper/players.py), so
    # teammates are found by querying that column directly. ESPN Player rows never carry a
    # gsis_id at all -- teammates are found there via the SAME espn_to_gsis lookup built once
    # above, reversed (gsis_id -> ESPN's own platform_player_id) to know which Player rows to
    # query. Either way, a teammate we can't resolve is simply absent from availability_by_gsis;
    # compute_effective_pos_rank treats that as available (no promotion), never a wrong one.
    needed_gsis_ids: set[str] = set()
    for candidate in narrowed:
        if candidate.team:
            needed_gsis_ids.update(teammate_groups.get((candidate.team, candidate.position), []))
    availability_by_gsis: dict[str, str] = {}
    if needed_gsis_ids and league.platform == "sleeper":
        result = await session.execute(
            select(Player).where(Player.platform == "sleeper", Player.gsis_id.in_(needed_gsis_ids))
        )
        availability_by_gsis = {
            p.gsis_id: classify_availability(p.injury_status, is_bye=False) for p in result.scalars()
        }
    elif needed_gsis_ids and espn_to_gsis:
        gsis_to_espn_id = {gsis: espn_id for espn_id, gsis in espn_to_gsis.items()}
        needed_espn_ids = {gsis_to_espn_id[g] for g in needed_gsis_ids if g in gsis_to_espn_id}
        if needed_espn_ids:
            result = await session.execute(
                select(Player).where(Player.platform == "espn", Player.platform_player_id.in_(needed_espn_ids))
            )
            for p in result.scalars():
                gsis = espn_to_gsis.get(p.platform_player_id)
                if gsis:
                    availability_by_gsis[gsis] = classify_availability(p.injury_status, is_bye=False)

    multi_year_team_prior = compute_team_prior_by_team(
        weekly_years, target_season=season, lookback=LOOKBACK_SEASONS, decay=RECENCY_DECAY
    )
    team_tendencies_v2 = compute_team_tendencies_v2(
        weekly_with_shares, multi_year_team_prior, season=season, before_week=league.current_week
    )
    share_priors = (
        compute_share_priors_by_rank(
            weekly_with_shares, depth_charts, season=season, before_week=league.current_week, as_of_date=as_of_date
        )
        if as_of_date else {}
    )
    position_priors = (
        compute_all_position_priors(weekly_stats, season=season, before_week=league.current_week)
        if not weekly_stats.empty else {}
    )
    limited_seasons = {s: df for s, df in season_stats_by_year.items() if season - LOOKBACK_SEASONS <= s < season}

    teams_present = {c.team for c in narrowed if c.team}
    qb_context_by_team = {}
    if as_of_date:
        for team in teams_present:
            qb_context_by_team[team] = compute_qb_context(
                current_team=team, prior_season_team=team, weekly_stats=weekly_stats, prior_weekly_stats=weekly_stats,
                depth_charts=depth_charts, as_of_date=as_of_date, season=season, before_week=league.current_week,
            )

    scored_candidates = []
    for candidate in narrowed:
        if candidate.position not in POSITION_CATEGORIES:
            continue

        gridlytics_base = None
        if candidate.gsis_id and as_of_date:
            career_seasons = build_career_seasons(limited_seasons, candidate.gsis_id, season)
            role = roles_by_gsis_position.get((candidate.gsis_id, candidate.position))
            qb_context = qb_context_by_team.get(candidate.team)
            if role is not None and qb_context is not None:
                # role.pos_rank stays the untouched, real nflverse depth-chart rank -- this is a
                # separate, additively-derived value, never a mutation of role/roles_by_gsis_position.
                projection_role = role
                room = teammate_groups.get((candidate.team, candidate.position), [])
                if room:
                    teammates = [
                        TeammateStatus(
                            gsis_id=teammate_gsis_id,
                            pos_rank=roles_by_gsis_position[(teammate_gsis_id, candidate.position)].pos_rank
                            if (teammate_gsis_id, candidate.position) in roles_by_gsis_position else None,
                            availability_status=availability_by_gsis.get(teammate_gsis_id, "healthy"),
                        )
                        for teammate_gsis_id in room
                    ]
                    effective_rank = compute_effective_pos_rank(candidate.gsis_id, role.pos_rank, teammates)
                    if effective_rank != role.pos_rank:
                        projection_role = RoleInfo(
                            pos_rank=effective_rank,
                            role_confidence=role.role_confidence,
                            role_changed_recently=role.role_changed_recently,
                        )

                career_prior = compute_career_prior(
                    career_seasons, team_changed=False, role_changed_recently=role.role_changed_recently
                )
                tendencies = team_tendencies_v2.get(candidate.team, TeamTendencies(None, None))
                breakdown = project_context_aware_points_detailed_v2(
                    candidate.position, [], None, career_prior, career_seasons, tendencies, projection_role, qb_context,
                    share_priors, position_priors.get(candidate.position, {}),
                    current_team=candidate.team, prior_season_team=candidate.team,
                    platform_points=None, availability_status="healthy",
                )
                gridlytics_base = breakdown.total_points if breakdown else None

        availability_status = classify_availability(candidate.injury_status, is_bye=False)
        final_projection = compute_final_projection(gridlytics_base, candidate.platform_projection, availability_status)
        if final_projection is None:
            continue

        scored_candidates.append({
            "candidate": candidate,
            "gridlytics_base_projection": gridlytics_base,
            "final_gridlytics_projection": final_projection,
        })

    if connection.my_team_id is None:
        result = await session.execute(select(Team).where(Team.league_id == league.id))
        num_teams = len(result.scalars().all()) or 1
        projections = [
            PlayerProjection(
                platform_player_id=sc["candidate"].platform_player_id, name=sc["candidate"].name,
                position=sc["candidate"].position, projected_points=sc["final_gridlytics_projection"],
                sources=[],
            )
            for sc in scored_candidates
        ]
        vor = compute_value_over_replacement(projections, league.roster_positions, num_teams)
        recommendations = [
            {
                "platform_player_id": sc["candidate"].platform_player_id, "name": sc["candidate"].name,
                "position": sc["candidate"].position, "team": sc["candidate"].team,
                "projected_lineup_improvement": None, "replaces_player_id": None, "replaces_name": None,
                "gridlytics_base_projection": sc["gridlytics_base_projection"],
                "platform_projection": sc["candidate"].platform_projection,
                "final_gridlytics_projection": sc["final_gridlytics_projection"],
                "value_over_replacement": vor.get(sc["candidate"].platform_player_id),
                "reasons": [],
            }
            for sc in scored_candidates
        ]
        recommendations.sort(key=lambda r: r["final_gridlytics_projection"] or 0, reverse=True)
        return {"mode": "projection_only", "recommendations": recommendations}

    result = await session.execute(
        select(RosterSlot.platform_player_id, RosterSlot.is_starter).where(
            RosterSlot.team_id == connection.my_team_id, RosterSlot.week == league.current_week
        )
    )
    roster_player_ids = [pid for pid, _ in result.all()]

    result = await session.execute(
        select(Player).where(Player.platform == league.platform, Player.platform_player_id.in_(roster_player_ids))
    )
    roster_players = {p.platform_player_id: p for p in result.scalars()}

    result = await session.execute(
        select(ProjectionRecord).where(
            ProjectionRecord.league_id == league.id, ProjectionRecord.week == league.current_week,
            ProjectionRecord.source == league.platform, ProjectionRecord.platform_player_id.in_(roster_player_ids),
        )
    )
    roster_platform_projection = {r.platform_player_id: r.projected_points for r in result.scalars()}

    result = await session.execute(
        select(ProjectionRecord).where(
            ProjectionRecord.league_id == league.id, ProjectionRecord.week == league.current_week,
            ProjectionRecord.source == "gridlytics", ProjectionRecord.platform_player_id.in_(roster_player_ids),
        )
    )
    roster_gridlytics_base = {r.platform_player_id: r.projected_points for r in result.scalars()}

    roster_candidates = []
    roster_names_by_id = {}
    for pid in roster_player_ids:
        player = roster_players.get(pid)
        if player is None:
            continue
        # POSITION_CATEGORIES (QB/RB/WR/TE) governs whether a context-aware gridlytics_base gets
        # attempted below -- it must never gate roster membership itself, or K/DEF slots silently
        # go unfilled in the lineup-comparison baseline.
        final = compute_final_projection(roster_gridlytics_base.get(pid), roster_platform_projection.get(pid), None)
        if final is None:
            continue
        roster_candidates.append({"player_id": pid, "position": player.position, "points": final})
        roster_names_by_id[pid] = player.name

    starting_slots = [slot for slot in league.roster_positions if slot not in NON_STARTING_SLOTS]
    current_assignment, current_optimal_points = find_optimal_lineup(roster_candidates, starting_slots)

    recommendations = []
    for sc in scored_candidates:
        candidate_dict = {
            "player_id": sc["candidate"].platform_player_id, "position": sc["candidate"].position,
            "points": sc["final_gridlytics_projection"],
        }
        transaction = simulate_best_transaction(
            roster_candidates, current_optimal_points, current_assignment, starting_slots, candidate_dict, roster_names_by_id
        )
        if transaction is None or transaction.improvement <= 0:
            continue
        recommendations.append({
            "platform_player_id": sc["candidate"].platform_player_id, "name": sc["candidate"].name,
            "position": sc["candidate"].position, "team": sc["candidate"].team,
            "projected_lineup_improvement": transaction.improvement,
            "replaces_player_id": transaction.drop_player_id, "replaces_name": transaction.drop_name,
            "gridlytics_base_projection": sc["gridlytics_base_projection"],
            "platform_projection": sc["candidate"].platform_projection,
            "final_gridlytics_projection": sc["final_gridlytics_projection"],
            "value_over_replacement": None,
            "reasons": build_explanation(
                PlayerProjection(
                    platform_player_id=sc["candidate"].platform_player_id, name=sc["candidate"].name,
                    position=sc["candidate"].position, projected_points=sc["final_gridlytics_projection"],
                    sources=[],
                ),
                None,
            ),
        })

    recommendations.sort(key=lambda r: r["projected_lineup_improvement"], reverse=True)
    return {"mode": "lineup_comparison", "recommendations": recommendations}
