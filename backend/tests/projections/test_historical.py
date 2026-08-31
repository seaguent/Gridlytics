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

    # Player A: weeks 1-3 = 10, 20, 30. Player B: weeks 1-3 = 5, 15, 10.
    # With num_weeks=2, decay=0.75: only weeks 2-3 count, week 3 (newest)
    # gets weight 1, week 2 gets weight 0.75.
    # Player A: (30*1 + 20*0.75) / 1.75 = 45/1.75 ~= 25.714
    # Player B: (10*1 + 15*0.75) / 1.75 = 21.25/1.75 ~= 12.143
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

    # ESPN's adapter hardcodes RosterSlot.points to 0 (per-player weekly
    # points aren't wired up yet). If this provider used that data, it would
    # silently return a fake ~0 projection that then contaminates the
    # ensemble average with real ESPN projections.
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
