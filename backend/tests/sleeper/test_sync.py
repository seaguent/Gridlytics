from datetime import datetime, timedelta, UTC

import httpx
import pytest
import respx
from sqlalchemy import select

from app.models import Matchup, Player, ProjectionRecord, Team, WeeklyScore
from app.sleeper.client import SLEEPER_BASE_URL, SLEEPER_PROJECTIONS_BASE_URL, SleeperClient
from app.sleeper.sync import refresh_league


def _mock_league_with_current_week(league_id: str, leg: int, playoff_week_start: int) -> None:
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "league_id": league_id, "name": "The League", "season": "2026", "season_type": "regular",
                "sport": "nfl", "status": "in_season", "total_rosters": 1,
                "settings": {"leg": leg, "playoff_teams": 4, "playoff_week_start": playoff_week_start},
            },
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/rosters").mock(
        return_value=httpx.Response(
            200,
            json=[{"roster_id": 1, "owner_id": "u1", "league_id": league_id, "players": [], "starters": [],
                   "settings": {"wins": 0, "losses": 0, "ties": 0}}],
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/users").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(return_value=httpx.Response(200, json={}))


def _real_matchup_response(points: float) -> httpx.Response:
    # players_points deliberately stays empty -- a non-empty one would populate RosterSlot with a
    # real platform_player_id, which makes _rostered_player_ids non-empty and pulls the whole
    # nflverse sync_usage_stats cascade into this test. The Matchup/WeeklyScore rows this test
    # actually needs (the real completeness signal, and something to prove stays unchanged) get
    # created either way, from the matchup's own team-level points.
    return httpx.Response(
        200,
        json=[{"roster_id": 1, "matchup_id": 1, "points": points, "starters": [], "players_points": {}}],
    )


def _mock_league_and_players(league_id: str = "123") -> None:
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "league_id": league_id,
                "name": "The League",
                "season": "2026",
                "season_type": "regular",
                "sport": "nfl",
                "status": "in_season",
                "total_rosters": 2,
                "settings": {"leg": 2, "playoff_teams": 4, "playoff_week_start": 4},
            },
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/rosters").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/users").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(
        return_value=httpx.Response(200, json={"1": {"position": "RB", "full_name": "Guy"}})
    )
    # playoff_week_start=4 -> sync_week is called for weeks 1, 2, 3
    for week in (1, 2, 3):
        respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/{week}").mock(
            return_value=httpx.Response(200, json=[])
        )
    # rosters are empty, so sync_projections returns early without calling the projections endpoint


@pytest.mark.asyncio
@respx.mock
async def test_refresh_league_syncs_players_when_cache_is_empty(db_session):
    _mock_league_and_players()

    client = SleeperClient()
    await refresh_league(db_session, client, "123")
    await client.aclose()

    result = await db_session.execute(select(Player))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
@respx.mock
async def test_refresh_league_syncs_every_week_up_to_playoffs(db_session):
    _mock_league_and_players()

    client = SleeperClient()
    league = await refresh_league(db_session, client, "123")
    await client.aclose()

    result = await db_session.execute(select(Matchup).where(Matchup.league_id == league.id))
    weeks_attempted = {matchup.week for matchup in result.scalars().all()}
    # Confirms refresh_league ran weeks 1-3 (playoff_week_start=4) without erroring and stopped there.
    assert weeks_attempted == set()


@pytest.mark.asyncio
@respx.mock
async def test_refresh_league_skips_player_sync_when_cache_is_fresh(db_session):
    _mock_league_and_players()
    db_session.add(
        Player(
            platform="sleeper",
            platform_player_id="999",
            position="QB",
            name="Already Cached",
            updated_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        )
    )
    await db_session.commit()

    client = SleeperClient()
    await refresh_league(db_session, client, "123")
    await client.aclose()

    result = await db_session.execute(select(Player))
    players = result.scalars().all()
    # Cache is fresh, so /players/nfl should not have been fetched -- only the pre-existing row remains.
    assert len(players) == 1
    assert players[0].platform_player_id == "999"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_league_syncs_projections_for_rostered_players(db_session):
    league_id = "123"
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "league_id": league_id,
                "name": "The League",
                "season": "2026",
                "season_type": "regular",
                "sport": "nfl",
                "status": "in_season",
                "total_rosters": 1,
                "settings": {"leg": 1, "playoff_teams": 4, "playoff_week_start": 1},
                "scoring_settings": {"rec": 1.0},
            },
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/rosters").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "roster_id": 1,
                    "owner_id": "u1",
                    "league_id": league_id,
                    "players": ["7039"],
                    "starters": [],
                    "settings": {"wins": 0, "losses": 0, "ties": 0},
                }
            ],
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/users").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(
        return_value=httpx.Response(200, json={"1": {"position": "RB", "full_name": "Guy"}})
    )
    # playoff_week_start=1 -> sync_week's range(1, 1) is empty, no matchup calls
    respx.get(f"{SLEEPER_PROJECTIONS_BASE_URL}/2026/1").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "player_id": "7039",
                    "week": 1,
                    "stats": {"pts_std": 8.5, "pts_half_ppr": 10.6, "pts_ppr": 12.7},
                    "player": {"first_name": "Cody", "last_name": "White", "position": "WR"},
                }
            ],
        )
    )

    client = SleeperClient()
    await refresh_league(db_session, client, league_id)
    await client.aclose()

    result = await db_session.execute(
        select(ProjectionRecord).where(ProjectionRecord.source == "sleeper")
    )
    records = result.scalars().all()
    assert len(records) == 1
    assert records[0].platform_player_id == "7039"
    # rec=1.0 -> full PPR
    assert records[0].projected_points == 12.7


@pytest.mark.asyncio
@respx.mock
async def test_refresh_league_skips_a_completed_past_week_but_keeps_resyncing_current_and_incomplete_weeks(
    db_session,
):
    """current_week (leg)=3, playoff_week_start=4 -> weeks 1, 2, 3 are attempted. Week 1 gets a
    real matchup on the first sync (becomes "complete"); week 2 gets an empty response (creates no
    Matchup row, stays "incomplete"); week 3 is the current week."""
    league_id = "123"
    _mock_league_with_current_week(league_id, leg=3, playoff_week_start=4)

    week1_route = respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/1").mock(
        return_value=_real_matchup_response(100.0)
    )
    week2_route = respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/2").mock(
        return_value=httpx.Response(200, json=[])
    )
    week3_route = respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/3").mock(
        return_value=_real_matchup_response(50.0)
    )

    client = SleeperClient()
    await refresh_league(db_session, client, league_id)  # first sync -- nothing exists yet
    await refresh_league(db_session, client, league_id)  # second sync -- week 1 should now be skipped
    await client.aclose()

    assert week1_route.call_count == 1  # complete after the first sync -- skipped the second time
    assert week2_route.call_count == 2  # never got a real Matchup row (empty response) -- still incomplete
    assert week3_route.call_count == 2  # current week -- always resynced


@pytest.mark.asyncio
@respx.mock
async def test_refresh_league_force_full_resync_reprocesses_completed_weeks(db_session):
    league_id = "123"
    _mock_league_with_current_week(league_id, leg=3, playoff_week_start=4)

    week1_route = respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/1").mock(
        return_value=_real_matchup_response(100.0)
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/2").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/3").mock(
        return_value=_real_matchup_response(50.0)
    )

    client = SleeperClient()
    await refresh_league(db_session, client, league_id)  # week 1 becomes complete
    await refresh_league(db_session, client, league_id)  # normal refresh -- proves the skip is live here
    assert week1_route.call_count == 1

    await refresh_league(db_session, client, league_id, force_full_resync=True)  # forced -- ignores completeness
    await client.aclose()

    assert week1_route.call_count == 2  # force bypassed the same skip that just applied above


@pytest.mark.asyncio
@respx.mock
async def test_refresh_league_skipping_a_complete_week_leaves_its_stored_data_unchanged(db_session):
    """The skip must never change what's already stored -- a skipped week's real WeeklyScore data
    from the first sync must still be there, untouched, after a second refresh that skips it."""
    league_id = "123"
    _mock_league_with_current_week(league_id, leg=3, playoff_week_start=4)

    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/1").mock(
        return_value=_real_matchup_response(100.0)
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/2").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{SLEEPER_BASE_URL}/league/{league_id}/matchups/3").mock(
        return_value=_real_matchup_response(50.0)
    )

    client = SleeperClient()
    league = await refresh_league(db_session, client, league_id)
    await refresh_league(db_session, client, league_id)
    await client.aclose()

    result = await db_session.execute(select(Team).where(Team.league_id == league.id))
    team = result.scalar_one()
    result = await db_session.execute(
        select(WeeklyScore).join(Matchup, WeeklyScore.matchup_id == Matchup.id).where(
            Matchup.league_id == league.id, Matchup.week == 1, WeeklyScore.team_id == team.id,
        )
    )
    week1_score = result.scalar_one()
    assert week1_score.points == pytest.approx(100.0)
