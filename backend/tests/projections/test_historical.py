import pytest

from app.models import League, Player, RosterSlot, Team
from app.projections.historical import HistoricalAverageProjectionProvider


@pytest.mark.asyncio
async def test_historical_average_projection_uses_recency_weighting(db_session):
    league = League(platform="sleeper", platform_league_id="1", season="2026", name="L", status="in_season")
    db_session.add(league)
    await db_session.flush()

    team = Team(league_id=league.id, platform_roster_id="1", display_name="A")
    db_session.add(team)
    await db_session.flush()

    db_session.add_all(
        [
            Player(platform="sleeper", platform_player_id="100", position="RB", name="Player A"),
            Player(platform="sleeper", platform_player_id="200", position="WR", name="Player B"),
        ]
    )

    # num_weeks=2, decay=0.75: A (30,20 weighted) -> 45/1.75~=25.714; B (10,15 weighted) -> 21.25/1.75~=12.143.
    db_session.add_all(
        [
            RosterSlot(team_id=team.id, week=1, platform_player_id="100", is_starter=True, points=10),
            RosterSlot(team_id=team.id, week=2, platform_player_id="100", is_starter=True, points=20),
            RosterSlot(team_id=team.id, week=3, platform_player_id="100", is_starter=True, points=30),
            RosterSlot(team_id=team.id, week=1, platform_player_id="200", is_starter=False, points=5),
            RosterSlot(team_id=team.id, week=2, platform_player_id="200", is_starter=False, points=15),
            RosterSlot(team_id=team.id, week=3, platform_player_id="200", is_starter=False, points=10),
        ]
    )
    await db_session.commit()

    provider = HistoricalAverageProjectionProvider(num_weeks=2, decay=0.75)
    projections = await provider.get_projections(db_session, league)

    by_id = {p.platform_player_id: p for p in projections}
    assert by_id["100"].projected_points == pytest.approx(25.714, abs=0.005)
    assert by_id["100"].name == "Player A"
    assert by_id["100"].position == "RB"
    assert by_id["100"].sources == ["historical_weighted_average"]
    assert by_id["200"].projected_points == pytest.approx(12.143, abs=0.005)


@pytest.mark.asyncio
async def test_historical_average_projection_skips_players_with_insufficient_history(db_session):
    league = League(platform="sleeper", platform_league_id="1", season="2026", name="L", status="in_season")
    db_session.add(league)
    await db_session.flush()

    team = Team(league_id=league.id, platform_roster_id="1", display_name="A")
    db_session.add(team)
    await db_session.flush()

    db_session.add_all(
        [
            Player(platform="sleeper", platform_player_id="100", position="RB", name="Veteran"),
            Player(platform="sleeper", platform_player_id="200", position="WR", name="Just Drafted"),
        ]
    )
    db_session.add_all(
        [
            # Veteran: 3 real weeks -- enough history to trust.
            RosterSlot(team_id=team.id, week=1, platform_player_id="100", is_starter=True, points=10),
            RosterSlot(team_id=team.id, week=2, platform_player_id="100", is_starter=True, points=15),
            RosterSlot(team_id=team.id, week=3, platform_player_id="100", is_starter=True, points=12),
            # Just drafted: only 1 real week -- one game is not a trend.
            RosterSlot(team_id=team.id, week=3, platform_player_id="200", is_starter=False, points=8),
        ]
    )
    await db_session.commit()

    provider = HistoricalAverageProjectionProvider(num_weeks=5, decay=0.75)
    projections = await provider.get_projections(db_session, league)

    ids = {p.platform_player_id for p in projections}
    assert "100" in ids
    assert "200" not in ids


@pytest.mark.asyncio
async def test_historical_average_projection_returns_empty_with_no_history(db_session):
    league = League(platform="sleeper", platform_league_id="1", season="2026", name="L", status="in_season")
    db_session.add(league)
    await db_session.flush()

    provider = HistoricalAverageProjectionProvider()
    projections = await provider.get_projections(db_session, league)

    assert projections == []


@pytest.mark.asyncio
async def test_historical_average_projection_skips_non_sleeper_leagues(db_session):
    league = League(platform="espn", platform_league_id="1", season="2026", name="L", status="in_season")
    db_session.add(league)
    await db_session.flush()

    team = Team(league_id=league.id, platform_roster_id="1", display_name="A")
    db_session.add(team)
    await db_session.flush()

    db_session.add(Player(platform="espn", platform_player_id="100", position="WR", name="Puka Nacua"))

    # ESPN's adapter hardcodes RosterSlot.points to 0 -- using it would fake a ~0 projection.
    db_session.add_all(
        [
            RosterSlot(team_id=team.id, platform_player_id="100", week=1, points=0, is_starter=True),
            RosterSlot(team_id=team.id, platform_player_id="100", week=2, points=0, is_starter=True),
        ]
    )
    await db_session.flush()

    provider = HistoricalAverageProjectionProvider()
    projections = await provider.get_projections(db_session, league)

    assert projections == []
