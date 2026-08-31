import pytest
from sqlalchemy import select

from app.espn.adapter import sync_league
from app.espn.schemas import EspnLeagueResponse
from app.models import League, Matchup, Player, RosterSlot, Team, WeeklyScore
from tests.espn.test_parser import SAMPLE_RAW


@pytest.mark.asyncio
async def test_sync_league_persists_league_teams_matchups_and_rosters(db_session):
    raw = EspnLeagueResponse.model_validate(SAMPLE_RAW)

    league = await sync_league(db_session, raw)

    assert league.platform == "espn"
    assert league.platform_league_id == "999888"
    assert league.season == "2026"
    assert league.name == "Test League"

    result = await db_session.execute(select(Team).where(Team.league_id == league.id))
    teams = {team.platform_roster_id: team for team in result.scalars()}
    assert len(teams) == 2
    assert teams["1"].display_name == "Team One"
    assert teams["1"].wins == 2

    result = await db_session.execute(select(Matchup).where(Matchup.league_id == league.id))
    matchups = result.scalars().all()
    assert len(matchups) == 2  # one per week

    result = await db_session.execute(
        select(WeeklyScore).join(Team).where(Team.league_id == league.id)
    )
    weekly_scores = result.scalars().all()
    assert len(weekly_scores) == 4  # 2 weeks x 2 teams

    result = await db_session.execute(select(Player).where(Player.platform == "espn"))
    players = {player.platform_player_id: player for player in result.scalars()}
    assert players["111"].position == "QB"
    assert players["112"].position == "RB"

    result = await db_session.execute(
        select(RosterSlot).where(RosterSlot.team_id == teams["1"].id)
    )
    roster_slots = {slot.platform_player_id: slot for slot in result.scalars()}
    assert roster_slots["111"].is_starter is True
    assert roster_slots["112"].is_starter is False


@pytest.mark.asyncio
async def test_sync_league_is_idempotent(db_session):
    raw = EspnLeagueResponse.model_validate(SAMPLE_RAW)

    await sync_league(db_session, raw)
    league = await sync_league(db_session, raw)

    result = await db_session.execute(select(League).where(League.platform == "espn"))
    assert len(result.scalars().all()) == 1

    result = await db_session.execute(select(Team).where(Team.league_id == league.id))
    assert len(result.scalars().all()) == 2

    result = await db_session.execute(
        select(WeeklyScore).join(Team).where(Team.league_id == league.id)
    )
    assert len(result.scalars().all()) == 4
