from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League, Matchup, RosterSlot, Team, WeeklyScore
from app.sleeper.client import SleeperClient


async def sync_league(session: AsyncSession, client: SleeperClient, league_id: str) -> League:
    raw_league = await client.get_league(league_id)
    raw_rosters = await client.get_rosters(league_id)
    raw_users = await client.get_users(league_id)

    display_names = {user.user_id: user.display_name for user in raw_users}

    result = await session.execute(
        select(League).where(
            League.platform == "sleeper",
            League.platform_league_id == league_id,
            League.season == raw_league.season,
        )
    )
    league = result.scalar_one_or_none()
    if league is None:
        league = League(
            platform="sleeper",
            platform_league_id=league_id,
            season=raw_league.season,
            name=raw_league.name,
            status=raw_league.status,
            roster_positions=raw_league.roster_positions,
            current_week=raw_league.settings.leg,
            playoff_teams=raw_league.settings.playoff_teams,
            playoff_week_start=raw_league.settings.playoff_week_start,
            last_synced_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(league)
        await session.flush()
    else:
        league.season = raw_league.season
        league.name = raw_league.name
        league.status = raw_league.status
        league.roster_positions = raw_league.roster_positions
        league.current_week = raw_league.settings.leg
        league.playoff_teams = raw_league.settings.playoff_teams
        league.playoff_week_start = raw_league.settings.playoff_week_start
        league.last_synced_at = datetime.now(UTC).replace(tzinfo=None)

    for raw_roster in raw_rosters:
        result = await session.execute(
            select(Team).where(
                Team.league_id == league.id,
                Team.platform_roster_id == str(raw_roster.roster_id),
            )
        )
        team = result.scalar_one_or_none()
        display_name = display_names.get(raw_roster.owner_id, f"Roster {raw_roster.roster_id}")

        if team is None:
            team = Team(
                league_id=league.id,
                platform_roster_id=str(raw_roster.roster_id),
                platform_owner_id=raw_roster.owner_id,
                display_name=display_name,
                wins=raw_roster.settings.wins,
                losses=raw_roster.settings.losses,
                ties=raw_roster.settings.ties,
                points_for=raw_roster.settings.fpts,
                points_against=raw_roster.settings.fpts_against,
            )
            session.add(team)
        else:
            team.display_name = display_name
            team.wins = raw_roster.settings.wins
            team.losses = raw_roster.settings.losses
            team.ties = raw_roster.settings.ties
            team.points_for = raw_roster.settings.fpts
            team.points_against = raw_roster.settings.fpts_against

    await session.commit()
    return league


async def sync_week(
    session: AsyncSession, client: SleeperClient, league: League, week: int
) -> None:
    raw_matchups = await client.get_matchups(league.platform_league_id, week)

    result = await session.execute(select(Team).where(Team.league_id == league.id))
    teams_by_roster_id = {team.platform_roster_id: team for team in result.scalars()}

    matchups_by_platform_id: dict[int, Matchup] = {}

    for raw in raw_matchups:
        platform_matchup_id = raw.matchup_id if raw.matchup_id is not None else raw.roster_id
        matchup = matchups_by_platform_id.get(platform_matchup_id)

        if matchup is None:
            result = await session.execute(
                select(Matchup).where(
                    Matchup.league_id == league.id,
                    Matchup.week == week,
                    Matchup.platform_matchup_id == platform_matchup_id,
                )
            )
            matchup = result.scalar_one_or_none()
            if matchup is None:
                matchup = Matchup(
                    league_id=league.id, week=week, platform_matchup_id=platform_matchup_id
                )
                session.add(matchup)
                await session.flush()
            matchups_by_platform_id[platform_matchup_id] = matchup

        team = teams_by_roster_id.get(str(raw.roster_id))
        if team is None:
            continue

        result = await session.execute(
            select(WeeklyScore).where(
                WeeklyScore.team_id == team.id,
                WeeklyScore.matchup_id == matchup.id,
            )
        )
        weekly_score = result.scalar_one_or_none()
        if weekly_score is None:
            session.add(
                WeeklyScore(team_id=team.id, matchup_id=matchup.id, week=week, points=raw.points)
            )
        else:
            weekly_score.points = raw.points

        starters = set(raw.starters)
        for platform_player_id, points in raw.players_points.items():
            is_starter = platform_player_id in starters

            result = await session.execute(
                select(RosterSlot).where(
                    RosterSlot.team_id == team.id,
                    RosterSlot.week == week,
                    RosterSlot.platform_player_id == platform_player_id,
                )
            )
            slot = result.scalar_one_or_none()
            if slot is None:
                session.add(
                    RosterSlot(
                        team_id=team.id,
                        week=week,
                        platform_player_id=platform_player_id,
                        is_starter=is_starter,
                        points=points,
                    )
                )
            else:
                slot.is_starter = is_starter
                slot.points = points

    await session.commit()
