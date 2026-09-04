import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.lineup import find_optimal_lineup
from app.analytics.roster import NON_STARTING_SLOTS
from app.models import League, Player, ProjectionRecord, RosterSlot, Team
from app.nflverse.client import NflverseClient
from app.projections.availability import classify_availability
from app.projections.final_projection import compute_final_projection
from app.projections.models import PlayerProjection
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


def _teams_playing_by_week(schedule: pd.DataFrame, weeks: list[int]) -> dict[int, set[str]]:
    result: dict[int, set[str]] = {}
    for week in weeks:
        week_games = schedule[schedule["week"] == week]
        result[week] = set(week_games["home_team"]) | set(week_games["away_team"])
    return result


async def _load_roster_players(
    session: AsyncSession, league: League, team_id: int
) -> tuple[list[dict], dict[str, str], set[str]]:
    """Raw per-player ingredients for a roster -- deliberately NOT blended/finalized here, so the
    caller can apply real current-week availability for the current-week term of the ROS sum and
    neutral (matchup-agnostic) availability for every future-week term."""
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

    players: list[dict] = []
    names_by_id: dict[str, str] = {}
    for pid in player_ids:
        player = players_by_id.get(pid)
        if player is None:
            continue
        # POSITION_CATEGORIES (QB/RB/WR/TE) governs whether a context-aware gridlytics_base gets
        # attempted below -- K/DEF have no rate model and simply never get one, same as everyone
        # else falls back to platform-only when gridlytics_base is missing. It must never gate
        # whether a player counts toward the roster at all, or K/DEF slots go silently unfilled.
        players.append({
            "player_id": pid,
            "position": player.position,
            "team": player.team,
            "injury_status": player.injury_status,
            "gridlytics_base": gridlytics_base.get(pid),
            "platform_projection": platform_projection.get(pid),
        })
        names_by_id[pid] = player.name
    return players, names_by_id, starting_ids


def _current_week_candidates(players: list[dict], playing_teams: set[str]) -> list[dict]:
    """Blended projection, real current-week availability (injury + this-week bye)."""
    candidates = []
    for p in players:
        is_bye = bool(playing_teams) and p["team"] not in playing_teams
        availability = classify_availability(p["injury_status"], is_bye)
        points = compute_final_projection(p["gridlytics_base"], p["platform_projection"], availability)
        if points is None:
            continue
        candidates.append({"player_id": p["player_id"], "position": p["position"], "team": p["team"], "points": points})
    return candidates


def _neutral_candidates(players: list[dict]) -> list[dict]:
    """The matchup-neutral Gridlytics base rate, assuming normal availability -- used for every
    future week. Excludes a player only when there's no real base rate to carry forward at all
    (missing != zero), never a fabricated fallback to the current-week blended number."""
    candidates = []
    for p in players:
        if p["gridlytics_base"] is None:
            continue
        candidates.append(
            {"player_id": p["player_id"], "position": p["position"], "team": p["team"], "points": p["gridlytics_base"]}
        )
    return candidates


def _exclude_bye(candidates: list[dict], playing_teams: set[str]) -> list[dict]:
    if not playing_teams:
        # No schedule data for this week -- unknown is not the same as everyone being on bye.
        return candidates
    return [c for c in candidates if c["team"] in playing_teams]


def _reasons_for(pids: list[str], candidates_by_id: dict[str, dict], names_by_id: dict[str, str]) -> list[str]:
    reasons: list[str] = []
    for pid in pids:
        candidate = candidates_by_id.get(pid)
        if candidate is None:
            continue
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

    my_players, my_names, my_starting_ids = await _load_roster_players(session, league, my_team_id)
    other_players, other_names, other_starting_ids = await _load_roster_players(session, league, other_team_id)
    my_ids = {p["player_id"] for p in my_players}
    other_ids = {p["player_id"] for p in other_players}

    for pid in give_player_ids:
        if pid not in my_ids:
            raise InvalidTradeError(f"{pid} is not on your roster")
    for pid in receive_player_ids:
        if pid not in other_ids:
            raise InvalidTradeError(f"{pid} is not on that team's roster")

    nflverse_client = NflverseClient()
    try:
        schedule = await nflverse_client.get_schedule(league.season)
    finally:
        await nflverse_client.aclose()

    weeks = list(range(league.current_week, league.playoff_week_start)) or [league.current_week]
    current_week = weeks[0]
    future_weeks = weeks[1:]
    teams_playing_by_week = _teams_playing_by_week(schedule, weeks)

    starting_slots = [slot for slot in league.roster_positions if slot not in NON_STARTING_SLOTS]
    give_set = set(give_player_ids)
    receive_set = set(receive_player_ids)

    # --- Current week: blended projection, real current-week availability ---
    current_playing_teams = teams_playing_by_week.get(current_week, set())
    my_current = _current_week_candidates(my_players, current_playing_teams)
    other_current = _current_week_candidates(other_players, current_playing_teams)
    my_current_by_id = {c["player_id"]: c for c in my_current}
    other_current_by_id = {c["player_id"]: c for c in other_current}
    receive_current = [other_current_by_id[pid] for pid in receive_player_ids if pid in other_current_by_id]
    give_current = [my_current_by_id[pid] for pid in give_player_ids if pid in my_current_by_id]

    # Both before and after use the OPTIMAL lineup -- an existing lineup-setting mistake (the
    # manager benching their best player) is a real, separate problem Start/Sit already surfaces,
    # but it must never leak into the trade delta, which has to isolate the trade's own value.
    your_actual_current_starters_points = sum(
        c["points"] for c in my_current if c["player_id"] in my_starting_ids
    )
    their_actual_current_starters_points = sum(
        c["points"] for c in other_current if c["player_id"] in other_starting_ids
    )
    your_current_week_before, your_current_week_after = simulate_trade(
        my_current, starting_slots, give_set, receive_current
    )
    their_current_week_before, their_current_week_after = simulate_trade(
        other_current, starting_slots, receive_set, give_current
    )

    # --- Future weeks: neutral Gridlytics base rate, normal availability, bye-excluded ---
    my_neutral = _neutral_candidates(my_players)
    other_neutral = _neutral_candidates(other_players)
    my_neutral_by_id = {c["player_id"]: c for c in my_neutral}
    other_neutral_by_id = {c["player_id"]: c for c in other_neutral}
    receive_neutral = [other_neutral_by_id[pid] for pid in receive_player_ids if pid in other_neutral_by_id]
    give_neutral = [my_neutral_by_id[pid] for pid in give_player_ids if pid in my_neutral_by_id]

    your_future_before = 0.0
    your_future_after = 0.0
    their_future_before = 0.0
    their_future_after = 0.0
    for week in future_weeks:
        playing_teams = teams_playing_by_week.get(week, set())
        my_week = _exclude_bye(my_neutral, playing_teams)
        other_week = _exclude_bye(other_neutral, playing_teams)
        receive_week = _exclude_bye(receive_neutral, playing_teams)
        give_week = _exclude_bye(give_neutral, playing_teams)

        week_before, week_after = simulate_trade(my_week, starting_slots, give_set, receive_week)
        your_future_before += week_before
        your_future_after += week_after

        week_before, week_after = simulate_trade(other_week, starting_slots, receive_set, give_week)
        their_future_before += week_before
        their_future_after += week_after

    your_ros_before = your_current_week_before + your_future_before
    your_ros_after = your_current_week_after + your_future_after
    their_ros_before = their_current_week_before + their_future_before
    their_ros_after = their_current_week_after + their_future_after

    return {
        "weeks_remaining": len(weeks),
        "your_team": {
            "current_week_before": your_current_week_before, "current_week_after": your_current_week_after,
            "current_week_delta": your_current_week_after - your_current_week_before,
            "rest_of_season_before": your_ros_before, "rest_of_season_after": your_ros_after,
            "rest_of_season_delta": your_ros_after - your_ros_before,
            # Context only -- what the manager actually has started this week, never used in the
            # delta above. Can differ from current_week_before when the real lineup isn't optimal.
            "actual_current_starters_points": your_actual_current_starters_points,
            "reasons": _reasons_for(receive_player_ids, other_current_by_id, other_names),
        },
        "other_team": {
            "current_week_before": their_current_week_before, "current_week_after": their_current_week_after,
            "current_week_delta": their_current_week_after - their_current_week_before,
            "rest_of_season_before": their_ros_before, "rest_of_season_after": their_ros_after,
            "rest_of_season_delta": their_ros_after - their_ros_before,
            "actual_current_starters_points": their_actual_current_starters_points,
            "reasons": _reasons_for(give_player_ids, my_current_by_id, my_names),
        },
    }
