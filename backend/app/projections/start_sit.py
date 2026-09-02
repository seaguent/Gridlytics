from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.lineup import SLOT_ELIGIBILITY, find_optimal_lineup
from app.analytics.roster import NON_STARTING_SLOTS
from app.models import League, Player, ProjectionRecord, RosterSlot, Team
from app.projections.ensemble import EnsembleProjectionProvider
from app.projections.espn import ESPNProjectionProvider
from app.projections.final_projection import compute_final_projection, fetch_platform_only_projections
from app.projections.head_to_head import compare_players
from app.projections.historical import HistoricalAverageProjectionProvider
from app.projections.models import PlayerMetrics, PlayerProjection
from app.projections.nflverse_metrics import NflverseMetricsProvider
from app.projections.rows import metrics_to_dict
from app.projections.sleeper import SleeperProjectionProvider
from app.projections.uncertainty_pipeline import apply_uncertainty_ranges
from app.sleeper.client import SleeperClient

MATCHUP_EASY_THRESHOLD = 65
MATCHUP_TOUGH_THRESHOLD = 35
LIMITED_SAMPLE_GAMES = 3


async def get_current_roster(
    session: AsyncSession, league: League, team: Team, sleeper_client: SleeperClient | None = None
) -> dict[str, bool]:
    """Maps platform_player_id -> whether they're in the user's real, currently-set starting lineup."""
    if league.platform == "espn":
        result = await session.execute(
            select(RosterSlot.platform_player_id, RosterSlot.is_starter).where(
                RosterSlot.team_id == team.id, RosterSlot.week == league.current_week
            )
        )
        return {platform_player_id: is_starter for platform_player_id, is_starter in result.all()}

    client = sleeper_client or SleeperClient()
    try:
        rosters = await client.get_rosters(league.platform_league_id)
    finally:
        if sleeper_client is None:
            await client.aclose()

    for roster in rosters:
        if str(roster.roster_id) == team.platform_roster_id:
            starters = set(roster.starters)
            return {platform_player_id: platform_player_id in starters for platform_player_id in roster.players}
    return {}


async def get_recent_performance_by_player(
    session: AsyncSession, league: League, roster_player_ids: set[str]
) -> dict[str, tuple[float, float, int]]:
    result = await session.execute(
        select(RosterSlot.platform_player_id, RosterSlot.week, RosterSlot.points)
        .join(Team, RosterSlot.team_id == Team.id)
        .where(
            Team.league_id == league.id,
            RosterSlot.platform_player_id.in_(roster_player_ids),
            RosterSlot.week < league.current_week,
        )
        .order_by(RosterSlot.week.desc())
    )
    most_recent_actual: dict[str, tuple[int, float]] = {}
    for platform_player_id, week, points in result.all():
        most_recent_actual.setdefault(platform_player_id, (week, points))
    if not most_recent_actual:
        return {}

    result = await session.execute(
        select(ProjectionRecord.platform_player_id, ProjectionRecord.week, ProjectionRecord.projected_points).where(
            ProjectionRecord.league_id == league.id,
            ProjectionRecord.platform_player_id.in_(roster_player_ids),
            ProjectionRecord.source == league.platform,
        )
    )
    projected_by_player_week = {
        (platform_player_id, week): points for platform_player_id, week, points in result.all()
    }

    performance = {}
    for platform_player_id, (week, actual) in most_recent_actual.items():
        projected = projected_by_player_week.get((platform_player_id, week))
        if projected is not None:
            performance[platform_player_id] = (actual, projected, week)
    return performance


def _range_provenance_text(projection: PlayerProjection) -> str:
    if projection.range_source == "current_season":
        return f"based on {projection.sample_size} games this season"
    if projection.range_source == "blended_history":
        return f"based on {projection.sample_size} games blending prior and current season"
    if projection.range_source == "prior_season":
        return f"based on {projection.sample_size} games last season"
    if projection.range_source == "position_prior":
        return f"limited history -- {projection.position} baseline from {projection.sample_size} games"
    return "range not available yet"


def build_explanation(
    projection: PlayerProjection | None,
    metrics: PlayerMetrics | None,
    recent_performance: tuple[float, float, int] | None = None,
) -> list[str]:
    reasons = []

    if projection is None:
        reasons.append("No projection available for this player")
        return reasons

    if projection.floor is not None and projection.ceiling is not None:
        reasons.append(
            f"Projected {projection.projected_points:.1f} points "
            f"({projection.floor:.1f}-{projection.ceiling:.1f} range, {_range_provenance_text(projection)})"
        )
    else:
        reasons.append(f"Projected {projection.projected_points:.1f} points (range not available yet)")

    if recent_performance is not None:
        actual, projected, week = recent_performance
        delta = actual - projected
        if abs(delta) >= 0.5:
            direction = "Outperformed" if delta > 0 else "Underperformed"
            reasons.append(
                f"{direction} week {week}'s projection by {abs(delta):.1f} points "
                f"({actual:.1f} actual vs {projected:.1f} projected)"
            )

    if metrics is None:
        return reasons

    if metrics.experience_status == "rookie_or_limited_history":
        reasons.append(f"Limited NFL history -- projection relies primarily on {'/'.join(projection.sources)} data")

    if metrics.usage_trend:
        reasons.append(f"Usage trend: {metrics.usage_trend}")
    if metrics.recent_target_share is not None and metrics.season_target_share is not None:
        gap = metrics.recent_target_share - metrics.season_target_share
        if abs(gap) >= 0.03:
            reasons.append(
                f"Recent target share {metrics.recent_target_share * 100:.0f}% vs season average "
                f"{metrics.season_target_share * 100:.0f}%"
            )
        else:
            reasons.append(f"Recent target share: {metrics.recent_target_share * 100:.0f}%")
    elif metrics.recent_target_share is not None:
        reasons.append(f"Recent target share: {metrics.recent_target_share * 100:.0f}%")
    if metrics.snap_share is not None:
        reasons.append(f"Snap share: {metrics.snap_share * 100:.0f}%")
    if metrics.carries is not None:
        reasons.append(f"{metrics.carries} carries last game")
    if metrics.red_zone_opportunities is not None:
        reasons.append(f"{metrics.red_zone_opportunities} red zone opportunities last game")

    if metrics.opponent is not None and metrics.matchup_rating is not None:
        if metrics.matchup_rating >= MATCHUP_EASY_THRESHOLD:
            label = "Easy"
        elif metrics.matchup_rating <= MATCHUP_TOUGH_THRESHOLD:
            label = "Tough"
        else:
            label = "Average"
        reasons.append(f"{label} matchup vs {metrics.opponent}")

    if metrics.availability == "doubtful":
        reasons.append("Doubtful -- real risk of not playing")
    elif metrics.availability == "questionable":
        reasons.append("Questionable -- monitor injury report")
    elif metrics.availability == "unavailable":
        reasons.append("Unavailable this week (out, IR, or bye)")

    if 0 < metrics.games_played < LIMITED_SAMPLE_GAMES:
        plural = "" if metrics.games_played == 1 else "s"
        reasons.append(f"Limited sample: {metrics.games_played} game{plural} this season")

    return reasons


def _empty_start_sit_result() -> dict:
    return {
        "starters": [],
        "bench": [],
        "unavailable": [],
        "optimal_points": 0.0,
        "summary": {"changes_count": 0, "current_lineup_points": 0.0, "projected_points_change": 0.0},
    }


async def compute_start_sit(
    session: AsyncSession, league: League, team: Team, sleeper_client: SleeperClient | None = None
) -> dict:
    roster = await get_current_roster(session, league, team, sleeper_client)
    roster_player_ids = set(roster.keys())
    if not roster_player_ids:
        return _empty_start_sit_result()

    provider = EnsembleProjectionProvider(
        [ESPNProjectionProvider(), SleeperProjectionProvider(), HistoricalAverageProjectionProvider()]
    )
    roster_projections = [
        p for p in await provider.get_projections(session, league) if p.platform_player_id in roster_player_ids
    ]
    roster_projections = await apply_uncertainty_ranges(session, league, roster_projections)
    projections_by_id = {p.platform_player_id: p for p in roster_projections}
    metrics_by_id = {
        m.platform_player_id: m
        for m in await NflverseMetricsProvider().get_metrics(session, league)
        if m.platform_player_id in roster_player_ids
    }

    result = await session.execute(
        select(Player).where(
            Player.platform == league.platform, Player.platform_player_id.in_(roster_player_ids)
        )
    )
    players_by_id = {player.platform_player_id: player for player in result.scalars()}
    recent_performance_by_id = await get_recent_performance_by_player(session, league, roster_player_ids)

    result = await session.execute(
        select(ProjectionRecord).where(
            ProjectionRecord.league_id == league.id,
            ProjectionRecord.week == league.current_week,
            ProjectionRecord.source == "gridlytics",
            ProjectionRecord.platform_player_id.in_(roster_player_ids),
        )
    )
    native_by_id = {r.platform_player_id: r for r in result.scalars()}
    platform_projection_by_id = await fetch_platform_only_projections(session, league)

    rows_by_id = {}
    blended_projections_by_id = {}
    candidates = []
    unavailable_ids = set()

    for platform_player_id in roster_player_ids:
        player = players_by_id.get(platform_player_id)
        projection = projections_by_id.get(platform_player_id)
        metrics = metrics_by_id.get(platform_player_id)
        position = player.position if player else (projection.position if projection else "UNKNOWN")
        name = player.name if player else (projection.name if projection else platform_player_id)

        native = native_by_id.get(platform_player_id)
        platform_projection = platform_projection_by_id.get(platform_player_id)
        # Gridlytics' own decision number: context-aware base blended with the platform's own
        # projection, per compute_final_projection's zero-handling rules. Drives the optimizer
        # and sort order -- the row's "projected_points" display field stays the untouched
        # platform number instead (set below).
        final_projection = compute_final_projection(
            gridlytics_base=native.projected_points if native else None,
            platform_projection=platform_projection,
            availability_status=metrics.availability if metrics else None,
        )
        # Explanation text narrates Gridlytics' own reasoning, so it uses Gridlytics' number
        # (the blend), not the platform's. Floor/ceiling stay from the original multi-source
        # ensemble range, unchanged.
        explanation_projection = replace(projection, projected_points=final_projection) if projection else None
        blended_projections_by_id[platform_player_id] = explanation_projection

        row = {
            "platform_player_id": platform_player_id,
            "name": name,
            "position": position,
            "currently_starting": roster.get(platform_player_id, False),
            # The primary "X proj" field is the untouched ESPN/Sleeper platform number -- NEVER
            # the blend. Gridlytics' own (blended) opinion is a separate field below.
            "projected_points": platform_projection,
            "sources": projection.sources if projection else [],
            "floor": projection.floor if projection else None,
            "ceiling": projection.ceiling if projection else None,
            "confidence": projection.confidence if projection else None,
            "range_source": projection.range_source if projection else None,
            "sample_size": projection.sample_size if projection else 0,
            "gridlytics_base_projection": native.projected_points if native else None,
            "platform_projection": platform_projection,
            "final_gridlytics_projection": final_projection,
            # "Gridlytics" in the UI is the blended final number, not the raw base --
            # comparing this against "projected_points" (pure platform) is the real,
            # user-facing ESPN-vs-Gridlytics comparison.
            "gridlytics_projected_points": final_projection,
            "gridlytics_expected_opportunities": native.expected_opportunities if native else None,
            "gridlytics_prior_season_weight": native.prior_season_weight if native else None,
            "gridlytics_dominant_category": native.dominant_category if native else None,
            "gridlytics_lower_confidence": bool(
                metrics is not None
                and position == "TE"
                and metrics.experience_status == "rookie_or_limited_history"
            ),
            "reasons": build_explanation(
                explanation_projection, metrics, recent_performance_by_id.get(platform_player_id)
            ),
            **metrics_to_dict(position, metrics),
        }
        rows_by_id[platform_player_id] = row

        is_unavailable = metrics is not None and metrics.availability == "unavailable"
        if is_unavailable:
            unavailable_ids.add(platform_player_id)
        elif final_projection is not None:
            candidates.append({"player_id": platform_player_id, "position": position, "points": final_projection})

    starting_slots = [slot for slot in league.roster_positions if slot not in NON_STARTING_SLOTS]
    assignment, optimal_points = find_optimal_lineup(candidates, starting_slots)
    started_ids = {player_id for _, player_id in assignment}
    slot_by_id = {player_id: slot for slot, player_id in assignment}

    starters, bench, unavailable = [], [], []
    for platform_player_id, row in rows_by_id.items():
        if platform_player_id in unavailable_ids:
            row["action"] = "unavailable"
            row["comparison"] = None
            unavailable.append(row)
        elif platform_player_id in started_ids:
            row["recommended_slot"] = slot_by_id[platform_player_id]
            row["action"] = "start" if row["currently_starting"] else "swap_in"
            row["comparison"] = None
            starters.append(row)
        else:
            row["action"] = "swap_out" if row["currently_starting"] else "bench"
            row["comparison"] = None
            bench.append(row)

    # Pair each newly-recommended starter with the real starter they're bumping (same slot-eligible
    # position), so the UI can present it as one "start X over Y" decision instead of two loose cards.
    unpaired_swap_outs = [row for row in bench if row["action"] == "swap_out"]
    for starter_row in starters:
        if starter_row["action"] != "swap_in":
            continue
        starter_id = starter_row["platform_player_id"]
        eligible_positions = SLOT_ELIGIBILITY.get(starter_row["recommended_slot"], set())
        partner = next((row for row in unpaired_swap_outs if row["position"] in eligible_positions), None)
        if partner is None or blended_projections_by_id.get(starter_id) is None:
            continue
        partner_id = partner["platform_player_id"]
        unpaired_swap_outs.remove(partner)
        starter_row["swap_out_player_id"] = partner_id
        starter_row["swap_out_name"] = partner["name"]
        if blended_projections_by_id.get(partner_id) is not None:
            # Same blended number the optimizer used to make this swap decision, so the
            # head-to-head "+Z pts" gap matches the reasoning behind the recommendation.
            starter_row["comparison"] = compare_players(
                blended_projections_by_id[starter_id],
                metrics_by_id.get(starter_id),
                blended_projections_by_id[partner_id],
                metrics_by_id.get(partner_id),
            )

    # Sort and lineup-points math stay on Gridlytics' own (blended) decision number, matching
    # what the optimizer itself maximized -- not the pure platform display field.
    starters.sort(key=lambda r: (r["final_gridlytics_projection"] or 0), reverse=True)
    bench.sort(key=lambda r: (r["final_gridlytics_projection"] or 0), reverse=True)

    changes_count = sum(1 for row in starters if row["action"] == "swap_in")
    current_lineup_points = sum(
        row["final_gridlytics_projection"] or 0 for row in rows_by_id.values() if row["currently_starting"]
    )

    return {
        "starters": starters,
        "bench": bench,
        "unavailable": unavailable,
        "optimal_points": optimal_points,
        "summary": {
            "changes_count": changes_count,
            "current_lineup_points": current_lineup_points,
            "projected_points_change": optimal_points - current_lineup_points,
        },
    }
