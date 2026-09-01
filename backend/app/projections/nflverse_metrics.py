from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    League,
    Player,
    PlayerSeasonBaseline,
    PlayerUsageStats,
    TeamDefenseStrength,
    TeamMatchup,
)
from app.nflverse.crosswalk import normalize_team
from app.projections.availability import classify_availability
from app.projections.models import PlayerMetrics

TREND_THRESHOLD = 0.03
FULL_TRANSITION_WEEKS = 8
RECENT_FORM_GAMES = 3


def _compute_trend(shares: list[float]) -> str | None:
    if len(shares) < 2:
        return None

    midpoint = len(shares) // 2 or 1
    earlier = shares[:midpoint]
    later = shares[midpoint:] or shares[midpoint - 1 :]
    earlier_avg = sum(earlier) / len(earlier)
    later_avg = sum(later) / len(later)

    if later_avg - earlier_avg > TREND_THRESHOLD:
        return "rising"
    if earlier_avg - later_avg > TREND_THRESHOLD:
        return "falling"
    return "stable"


def _matchup_rating(points_allowed_avg: float, position_values: list[float]) -> float | None:
    if len(position_values) < 2:
        return None
    low, high = min(position_values), max(position_values)
    if high == low:
        return 50.0
    return (points_allowed_avg - low) / (high - low) * 100


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def prior_season_weight(games_played_this_season: int) -> float:
    # Sample-size based, not calendar-week based -- byes/injuries mean games
    # played and weeks elapsed aren't the same thing.
    return max(0.0, min(1.0, 1 - games_played_this_season / FULL_TRANSITION_WEEKS))


def _blend_target_share(
    recent: float | None, baseline: PlayerSeasonBaseline | None, games_played: int, current_team: str | None
) -> float | None:
    if baseline is None or baseline.target_share is None:
        return recent

    baseline_team = normalize_team(baseline.team)
    if current_team and baseline_team and current_team != baseline_team:
        # A team change means the prior team's usage rate isn't a trustworthy baseline anymore.
        return recent

    if recent is None:
        return baseline.target_share

    weight = prior_season_weight(games_played)
    return weight * baseline.target_share + (1 - weight) * recent


class NflverseMetricsProvider:
    async def get_metrics(self, session: AsyncSession, league: League) -> list[PlayerMetrics]:
        result = await session.execute(
            select(PlayerUsageStats)
            .where(
                PlayerUsageStats.platform == league.platform,
                PlayerUsageStats.season == league.season,
            )
            .order_by(PlayerUsageStats.week)
        )
        by_player: dict[str, list[PlayerUsageStats]] = {}
        for row in result.scalars():
            by_player.setdefault(row.platform_player_id, []).append(row)

        prior_season = str(int(league.season) - 1)
        result = await session.execute(
            select(PlayerSeasonBaseline).where(
                PlayerSeasonBaseline.platform == league.platform,
                PlayerSeasonBaseline.season == prior_season,
            )
        )
        baseline_by_player = {row.platform_player_id: row for row in result.scalars()}

        all_player_ids = set(by_player.keys()) | set(baseline_by_player.keys())
        if not all_player_ids:
            return []

        result = await session.execute(
            select(Player).where(
                Player.platform == league.platform,
                Player.platform_player_id.in_(all_player_ids),
            )
        )
        players = {player.platform_player_id: player for player in result.scalars()}

        result = await session.execute(
            select(TeamMatchup).where(
                TeamMatchup.season == league.season, TeamMatchup.week == league.current_week
            )
        )
        opponent_by_team = {row.team: row.opponent for row in result.scalars()}

        result = await session.execute(
            select(TeamDefenseStrength).where(TeamDefenseStrength.season == league.season)
        )
        defense_strength_rows = result.scalars().all()
        strength_by_team_position = {(row.team, row.position): row.points_allowed_avg for row in defense_strength_rows}
        values_by_position: dict[str, list[float]] = {}
        for row in defense_strength_rows:
            values_by_position.setdefault(row.position, []).append(row.points_allowed_avg)

        metrics = []
        for platform_player_id in all_player_ids:
            records = by_player.get(platform_player_id, [])
            baseline = baseline_by_player.get(platform_player_id)
            player = players.get(platform_player_id)
            position = player.position if player else None
            current_team = normalize_team(player.team) if player else None

            games_played = len(records)
            if records:
                latest = records[-1]
                shares = [r.target_share for r in records if r.target_share is not None]
                season_target_share = _average(shares)
                recent_target_share = _average(shares[-RECENT_FORM_GAMES:])
                targets = latest.targets
                carries = latest.carries
                snap_share = latest.snap_share
                red_zone_opportunities = latest.red_zone_opportunities
                usage_trend = _compute_trend(shares)
            else:
                season_target_share = None
                recent_target_share = None
                targets = None
                carries = None
                snap_share = None
                red_zone_opportunities = None
                usage_trend = None

            target_share = _blend_target_share(recent_target_share, baseline, games_played, current_team)
            experience_status = "veteran" if baseline is not None else "rookie_or_limited_history"

            opponent = None
            matchup_rating = None
            if current_team and position:
                opponent = opponent_by_team.get(current_team)
                if opponent is not None:
                    points_allowed = strength_by_team_position.get((opponent, position))
                    if points_allowed is not None:
                        matchup_rating = _matchup_rating(points_allowed, values_by_position[position])

            availability = None
            if player is not None:
                # Only trust bye detection once we know the schedule was actually loaded this week.
                schedule_known = bool(opponent_by_team)
                is_bye = schedule_known and current_team is not None and current_team not in opponent_by_team
                availability = classify_availability(player.injury_status, is_bye)

            metrics.append(
                PlayerMetrics(
                    platform_player_id=platform_player_id,
                    targets=targets,
                    target_share=target_share,
                    carries=carries,
                    snap_share=snap_share,
                    red_zone_opportunities=red_zone_opportunities,
                    usage_trend=usage_trend,
                    injury_status=player.injury_status if player else None,
                    opponent=opponent,
                    matchup_rating=matchup_rating,
                    experience_status=experience_status,
                    games_played=games_played,
                    season_target_share=season_target_share,
                    recent_target_share=recent_target_share,
                    availability=availability,
                )
            )
        return metrics
