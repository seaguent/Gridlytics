from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.espn.parser import parse_league, parse_matchups, parse_projections, parse_rosters, parse_teams
from app.espn.schemas import EspnLeagueResponse
from app.models import League, Matchup, Player, ProjectionRecord, RosterSlot, Team, WeeklyScore


async def sync_league(session: AsyncSession, raw: EspnLeagueResponse) -> League:
    league_fields = parse_league(raw)

    result = await session.execute(
        select(League).where(
            League.platform == "espn",
            League.platform_league_id == league_fields["platform_league_id"],
            League.season == league_fields["season"],
        )
    )
    league = result.scalar_one_or_none()
    if league is None:
        league = League(platform="espn", **league_fields)
        session.add(league)
        await session.flush()
    else:
        for field, value in league_fields.items():
            if field not in ("platform_league_id", "season"):
                setattr(league, field, value)
    league.last_synced_at = datetime.now(UTC).replace(tzinfo=None)

    teams_by_platform_id: dict[str, Team] = {}
    for team_fields in parse_teams(raw):
        platform_team_id = team_fields.pop("platform_team_id")
        result = await session.execute(
            select(Team).where(
                Team.league_id == league.id,
                Team.platform_roster_id == platform_team_id,
            )
        )
        team = result.scalar_one_or_none()
        if team is None:
            team = Team(league_id=league.id, platform_roster_id=platform_team_id, **team_fields)
            session.add(team)
            await session.flush()
        else:
            for field, value in team_fields.items():
                setattr(team, field, value)
        teams_by_platform_id[platform_team_id] = team

    matchups_by_key: dict[tuple[int, int], Matchup] = {}
    for matchup_fields in parse_matchups(raw):
        team = teams_by_platform_id.get(matchup_fields["platform_team_id"])
        if team is None:
            continue

        key = (matchup_fields["week"], matchup_fields["platform_matchup_id"])
        matchup = matchups_by_key.get(key)
        if matchup is None:
            result = await session.execute(
                select(Matchup).where(
                    Matchup.league_id == league.id,
                    Matchup.week == matchup_fields["week"],
                    Matchup.platform_matchup_id == matchup_fields["platform_matchup_id"],
                )
            )
            matchup = result.scalar_one_or_none()
            if matchup is None:
                matchup = Matchup(
                    league_id=league.id,
                    week=matchup_fields["week"],
                    platform_matchup_id=matchup_fields["platform_matchup_id"],
                )
                session.add(matchup)
                await session.flush()
            matchups_by_key[key] = matchup

        result = await session.execute(
            select(WeeklyScore).where(
                WeeklyScore.team_id == team.id,
                WeeklyScore.matchup_id == matchup.id,
            )
        )
        weekly_score = result.scalar_one_or_none()
        if weekly_score is None:
            session.add(
                WeeklyScore(
                    team_id=team.id,
                    matchup_id=matchup.id,
                    week=matchup_fields["week"],
                    points=matchup_fields["points"],
                )
            )
        else:
            weekly_score.points = matchup_fields["points"]

    for roster_fields in parse_rosters(raw):
        team = teams_by_platform_id.get(roster_fields["platform_team_id"])
        if team is None:
            continue

        result = await session.execute(
            select(Player).where(
                Player.platform == "espn",
                Player.platform_player_id == roster_fields["platform_player_id"],
            )
        )
        player = result.scalar_one_or_none()
        if player is None:
            session.add(
                Player(
                    platform="espn",
                    platform_player_id=roster_fields["platform_player_id"],
                    position=roster_fields["position"],
                    name=roster_fields["player_name"],
                    team=roster_fields["team"],
                    injury_status=roster_fields["injury_status"],
                )
            )
        else:
            player.position = roster_fields["position"]
            player.name = roster_fields["player_name"]
            player.team = roster_fields["team"]
            player.injury_status = roster_fields["injury_status"]

        result = await session.execute(
            select(RosterSlot).where(
                RosterSlot.team_id == team.id,
                RosterSlot.week == league.current_week,
                RosterSlot.platform_player_id == roster_fields["platform_player_id"],
            )
        )
        slot = result.scalar_one_or_none()
        if slot is None:
            session.add(
                RosterSlot(
                    team_id=team.id,
                    week=league.current_week,
                    platform_player_id=roster_fields["platform_player_id"],
                    is_starter=roster_fields["is_starter"],
                    points=0,
                )
            )
        else:
            slot.is_starter = roster_fields["is_starter"]

    for projection_fields in parse_projections(raw):
        result = await session.execute(
            select(ProjectionRecord).where(
                ProjectionRecord.league_id == league.id,
                ProjectionRecord.platform_player_id == projection_fields["platform_player_id"],
                ProjectionRecord.week == league.current_week,
                ProjectionRecord.source == "espn",
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            session.add(
                ProjectionRecord(
                    league_id=league.id,
                    platform_player_id=projection_fields["platform_player_id"],
                    week=league.current_week,
                    source="espn",
                    name=projection_fields["name"],
                    position=projection_fields["position"],
                    projected_points=projection_fields["projected_points"],
                )
            )
        else:
            record.projected_points = projection_fields["projected_points"]
            record.name = projection_fields["name"]
            record.position = projection_fields["position"]

    await session.commit()
    return league
