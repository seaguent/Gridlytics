import pytest
from sqlalchemy import select

from app.espn.adapter import sync_league
from app.espn.schemas import EspnLeagueResponse
from app.models import League, Matchup, Player, RosterSlot, Team, WeeklyScore
from tests.espn.test_actual_scores import _sample_with_actual_history
from tests.espn.test_parser import SAMPLE_RAW


@pytest.mark.asyncio
async def test_sync_league_persists_league_teams_matchups_and_rosters(db_session):
    raw = EspnLeagueResponse.model_validate(SAMPLE_RAW)

    league = await sync_league(db_session, raw)

    assert league.platform == "espn"
    assert league.platform_league_id == "999888"
    assert league.season == "2026"
    assert league.name == "Test League"
    assert league.scoring_settings == {
        "scoring_items": [
            {"stat_id": 3, "points": 0.05},
            {"stat_id": 41, "points": 0.5},
            {"stat_id": 20, "points": -1.0},
        ]
    }

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
async def test_sync_league_persists_real_actual_points_for_current_and_past_weeks(db_session):
    raw = _sample_with_actual_history()

    league = await sync_league(db_session, raw)

    result = await db_session.execute(select(Team).where(Team.league_id == league.id))
    team_one = next(t for t in result.scalars() if t.platform_roster_id == "1")

    result = await db_session.execute(select(RosterSlot).where(RosterSlot.team_id == team_one.id))
    slots_by_player_week = {(s.platform_player_id, s.week): s.points for s in result.scalars()}

    assert slots_by_player_week[("111", 1)] == 24.6
    assert slots_by_player_week[("111", 2)] == 12.1
    # current week (3) has no real actual stat in the fixture (game not played yet) -- must not be fabricated
    assert slots_by_player_week[("111", 3)] == 0
    assert slots_by_player_week[("112", 1)] == 5.3


@pytest.mark.asyncio
async def test_sync_league_actual_points_are_idempotent(db_session):
    raw = _sample_with_actual_history()

    await sync_league(db_session, raw)
    league = await sync_league(db_session, raw)

    result = await db_session.execute(select(Team).where(Team.league_id == league.id))
    team_one = next(t for t in result.scalars() if t.platform_roster_id == "1")

    result = await db_session.execute(select(RosterSlot).where(RosterSlot.team_id == team_one.id))
    slots = result.scalars().all()
    # 2 players x 2 real weeks (111: weeks 1,2,3; 112: weeks 1,3) -- no duplicate rows from re-sync
    assert len({(s.platform_player_id, s.week) for s in slots}) == len(slots)


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
