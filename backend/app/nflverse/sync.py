import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    League,
    Player,
    PlayerSeasonBaseline,
    PlayerUsageStats,
    PositionVolatilityPrior,
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
)


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


async def sync_matchup_context(
    session: AsyncSession, client: NflverseClient, league: League, weekly_stats: pd.DataFrame
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

    schedule = await client.get_schedule(league.season)
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
    await sync_matchup_context(session, client, league, weekly_stats)

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
