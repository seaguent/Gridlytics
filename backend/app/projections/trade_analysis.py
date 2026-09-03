from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.lineup import find_optimal_lineup
from app.analytics.roster import NON_STARTING_SLOTS
from app.models import League, Player, ProjectionRecord, RosterSlot, Team
from app.projections.final_projection import compute_final_projection
from app.projections.models import PlayerProjection
from app.projections.native.categories import POSITION_CATEGORIES
from app.projections.start_sit import build_explanation


def simulate_trade(
    roster_candidates: list[dict],
    starting_slots: list[str],
    give_player_ids: set[str],
    receive_candidates: list[dict],
) -> tuple[float, float]:
    _, current_points = find_optimal_lineup(roster_candidates, starting_slots)
    hypothetical = [p for p in roster_candidates if p["player_id"] not in give_player_ids] + receive_candidates
    _, projected_points = find_optimal_lineup(hypothetical, starting_slots)
    return current_points, projected_points


class InvalidTradeError(Exception):
    pass


async def _load_roster_candidates(
    session: AsyncSession, league: League, team_id: int
) -> tuple[list[dict], dict[str, str], set[str]]:
    result = await session.execute(
        select(RosterSlot.platform_player_id, RosterSlot.is_starter).where(
            RosterSlot.team_id == team_id, RosterSlot.week == league.current_week
        )
    )
    roster_rows = result.all()
    player_ids = [pid for pid, _ in roster_rows]
    starting_ids = {pid for pid, is_starter in roster_rows if is_starter}

    result = await session.execute(
        select(Player).where(Player.platform == league.platform, Player.platform_player_id.in_(player_ids))
    )
    players_by_id = {p.platform_player_id: p for p in result.scalars()}

    result = await session.execute(
        select(ProjectionRecord).where(
            ProjectionRecord.league_id == league.id, ProjectionRecord.week == league.current_week,
            ProjectionRecord.source == league.platform, ProjectionRecord.platform_player_id.in_(player_ids),
        )
    )
    platform_projection = {r.platform_player_id: r.projected_points for r in result.scalars()}

    result = await session.execute(
        select(ProjectionRecord).where(
            ProjectionRecord.league_id == league.id, ProjectionRecord.week == league.current_week,
            ProjectionRecord.source == "gridlytics", ProjectionRecord.platform_player_id.in_(player_ids),
        )
    )
    gridlytics_base = {r.platform_player_id: r.projected_points for r in result.scalars()}

    candidates: list[dict] = []
    names_by_id: dict[str, str] = {}
    for pid in player_ids:
        player = players_by_id.get(pid)
        if player is None or player.position not in POSITION_CATEGORIES:
            continue
        final = compute_final_projection(gridlytics_base.get(pid), platform_projection.get(pid), None)
        if final is None:
            continue
        candidates.append({"player_id": pid, "position": player.position, "points": final})
        names_by_id[pid] = player.name
    return candidates, names_by_id, starting_ids


def _reasons_for(pids: list[str], candidates_by_id: dict[str, dict], names_by_id: dict[str, str]) -> list[str]:
    reasons: list[str] = []
    for pid in pids:
        candidate = candidates_by_id[pid]
        projection = PlayerProjection(
            platform_player_id=pid, name=names_by_id.get(pid, pid), position=candidate["position"],
            projected_points=candidate["points"], sources=[],
        )
        reasons.extend(build_explanation(projection, None))
    return reasons


async def compute_trade_analysis(
    session: AsyncSession,
    league: League,
    my_team_id: int,
    other_team_id: int,
    give_player_ids: list[str],
    receive_player_ids: list[str],
) -> dict:
    if not give_player_ids and not receive_player_ids:
        raise InvalidTradeError("A trade needs at least one player on one side")
    if other_team_id == my_team_id:
        raise InvalidTradeError("Cannot trade with your own team")

    result = await session.execute(select(Team).where(Team.id == other_team_id, Team.league_id == league.id))
    if result.scalar_one_or_none() is None:
        raise InvalidTradeError("That team is not in this league")

    my_candidates, my_names, my_starting_ids = await _load_roster_candidates(session, league, my_team_id)
    other_candidates, other_names, other_starting_ids = await _load_roster_candidates(session, league, other_team_id)
    my_ids = {c["player_id"] for c in my_candidates}
    other_ids = {c["player_id"] for c in other_candidates}

    for pid in give_player_ids:
        if pid not in my_ids:
            raise InvalidTradeError(f"{pid} is not on your roster")
    for pid in receive_player_ids:
        if pid not in other_ids:
            raise InvalidTradeError(f"{pid} is not on that team's roster")

    starting_slots = [slot for slot in league.roster_positions if slot not in NON_STARTING_SLOTS]
    give_set = set(give_player_ids)
    receive_set = set(receive_player_ids)
    my_by_id = {c["player_id"]: c for c in my_candidates}
    other_by_id = {c["player_id"]: c for c in other_candidates}
    receive_candidates = [other_by_id[pid] for pid in receive_player_ids]
    give_candidates = [my_by_id[pid] for pid in give_player_ids]

    # "current" matches Start/Sit's own current_lineup_points exactly: the real, actually-started
    # players (RosterSlot.is_starter), not the mathematically-optimal lineup -- those two only
    # coincide when the manager's real lineup already happens to be optimal.
    your_current = sum(c["points"] for c in my_candidates if c["player_id"] in my_starting_ids)
    their_current = sum(c["points"] for c in other_candidates if c["player_id"] in other_starting_ids)

    _, your_projected = simulate_trade(my_candidates, starting_slots, give_set, receive_candidates)
    _, their_projected = simulate_trade(other_candidates, starting_slots, receive_set, give_candidates)

    return {
        "your_team": {
            "current_points": your_current, "projected_points": your_projected,
            "delta": your_projected - your_current,
            "reasons": _reasons_for(receive_player_ids, other_by_id, other_names),
        },
        "other_team": {
            "current_points": their_current, "projected_points": their_projected,
            "delta": their_projected - their_current,
            "reasons": _reasons_for(give_player_ids, my_by_id, my_names),
        },
    }
