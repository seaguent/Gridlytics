from app.sleeper.schemas import SleeperLeague, SleeperProjection, SleeperRoster


def test_sleeper_league_parses_known_fields_and_ignores_unknown():
    raw = {
        "league_id": "123",
        "name": "The League",
        "season": "2026",
        "season_type": "regular",
        "sport": "nfl",
        "status": "in_season",
        "total_rosters": 12,
        "some_field_sleeper_added_later": "ignore me",
    }
    league = SleeperLeague.model_validate(raw)
    assert league.league_id == "123"
    assert league.name == "The League"
    assert league.total_rosters == 12


def test_sleeper_league_parses_scoring_settings():
    raw = {
        "league_id": "123",
        "name": "The League",
        "season": "2026",
        "season_type": "regular",
        "sport": "nfl",
        "status": "in_season",
        "total_rosters": 12,
        "scoring_settings": {"rec": 0.5, "pass_td": 4},
    }
    league = SleeperLeague.model_validate(raw)
    assert league.scoring_settings["rec"] == 0.5


def test_sleeper_projection_parses_nested_player_and_stats():
    raw = {
        "player_id": "7039",
        "week": 1,
        "stats": {"pts_std": 8.5, "pts_half_ppr": 10.6, "pts_ppr": 12.7},
        "player": {"first_name": "Cody", "last_name": "White", "position": "WR"},
        "some_field_sleeper_added_later": "ignore me",
    }
    projection = SleeperProjection.model_validate(raw)
    assert projection.player_id == "7039"
    assert projection.stats.pts_ppr == 12.7
    assert projection.player.first_name == "Cody"


def test_sleeper_roster_parses_nested_settings():
    raw = {
        "roster_id": 1,
        "owner_id": "user_1",
        "league_id": "123",
        "players": ["1001", "1002"],
        "starters": ["1001"],
        "settings": {"wins": 5, "losses": 3, "ties": 0},
    }
    roster = SleeperRoster.model_validate(raw)
    assert roster.roster_id == 1
    assert roster.settings.wins == 5
