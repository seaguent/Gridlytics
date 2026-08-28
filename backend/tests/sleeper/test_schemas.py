from app.sleeper.schemas import SleeperLeague, SleeperRoster


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
