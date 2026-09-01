from app.espn.parser import parse_league, parse_matchups, parse_rosters, parse_teams
from app.espn.schemas import EspnLeagueResponse

SAMPLE_RAW = {
    "id": 999888,
    "seasonId": 2026,
    "status": {"currentMatchupPeriod": 3, "isActive": True},
    "settings": {
        "name": "Test League",
        "rosterSettings": {
            "lineupSlotCounts": {
                "0": 1,
                "2": 2,
                "4": 2,
                "6": 1,
                "23": 1,
                "16": 1,
                "17": 1,
                "20": 6,
                "21": 1,
            }
        },
        "scheduleSettings": {"matchupPeriodCount": 14, "playoffTeamCount": 6},
    },
    "teams": [
        {
            "id": 1,
            "name": "Team One",
            "owners": ["owner-guid-1"],
            "record": {
                "overall": {"wins": 2, "losses": 1, "ties": 0, "pointsFor": 300.5, "pointsAgainst": 280.2}
            },
            "roster": {
                "entries": [
                    {
                        "playerId": 111,
                        "lineupSlotId": 0,
                        "playerPoolEntry": {
                            "player": {
                                "fullName": "Starter QB",
                                "defaultPositionId": 1,
                                "proTeamId": 12,
                                "injuryStatus": "QUESTIONABLE",
                            }
                        },
                    },
                    {
                        "playerId": 112,
                        "lineupSlotId": 20,
                        "playerPoolEntry": {"player": {"fullName": "Bench RB", "defaultPositionId": 2}},
                    },
                ]
            },
        },
        {
            "id": 2,
            "location": "Team",
            "nickname": "Two",
            "owners": ["owner-guid-2"],
            "record": {
                "overall": {"wins": 1, "losses": 2, "ties": 0, "pointsFor": 270.0, "pointsAgainst": 290.0}
            },
            "roster": {"entries": []},
        },
    ],
    "schedule": [
        {
            "matchupPeriodId": 1,
            "home": {"teamId": 1, "totalPoints": 105.5},
            "away": {"teamId": 2, "totalPoints": 98.2},
        },
        {
            "matchupPeriodId": 2,
            "home": {"teamId": 2, "totalPoints": 110.0},
            "away": {"teamId": 1, "totalPoints": 100.0},
        },
    ],
    "members": [
        {"id": "owner-guid-1", "displayName": "sean"},
        {"id": "owner-guid-2", "displayName": "friend"},
    ],
}


def _sample() -> EspnLeagueResponse:
    return EspnLeagueResponse.model_validate(SAMPLE_RAW)


def test_parse_league_extracts_metadata_and_settings():
    league = parse_league(_sample())

    assert league["platform_league_id"] == "999888"
    assert league["season"] == "2026"
    assert league["name"] == "Test League"
    assert league["status"] == "in_season"
    assert league["current_week"] == 3
    assert league["playoff_teams"] == 6
    assert league["playoff_week_start"] == 15


def test_parse_league_builds_roster_positions_from_slot_counts():
    league = parse_league(_sample())
    positions = league["roster_positions"]

    assert positions.count("QB") == 1
    assert positions.count("RB") == 2
    assert positions.count("WR") == 2
    assert positions.count("TE") == 1
    assert positions.count("FLEX") == 1
    assert positions.count("DEF") == 1
    assert positions.count("K") == 1
    assert positions.count("BN") == 6
    assert positions.count("IR") == 1
    assert len(positions) == 16


def test_parse_teams_uses_name_field_when_present():
    teams = parse_teams(_sample())
    team_one = next(t for t in teams if t["platform_team_id"] == "1")

    assert team_one["display_name"] == "Team One"
    assert team_one["wins"] == 2
    assert team_one["points_for"] == 300.5
    assert team_one["platform_owner_id"] == "owner-guid-1"


def test_parse_teams_falls_back_to_location_and_nickname():
    teams = parse_teams(_sample())
    team_two = next(t for t in teams if t["platform_team_id"] == "2")

    assert team_two["display_name"] == "Team Two"


def test_parse_matchups_produces_one_row_per_team_per_week():
    matchups = parse_matchups(_sample())

    assert len(matchups) == 4
    week1_team1 = next(m for m in matchups if m["week"] == 1 and m["platform_team_id"] == "1")
    week1_team2 = next(m for m in matchups if m["week"] == 1 and m["platform_team_id"] == "2")
    assert week1_team1["points"] == 105.5
    assert week1_team2["points"] == 98.2
    assert week1_team1["platform_matchup_id"] == week1_team2["platform_matchup_id"]


def test_parse_rosters_maps_position_and_starter_status():
    roster_slots = parse_rosters(_sample())

    assert len(roster_slots) == 2
    starter = next(r for r in roster_slots if r["platform_player_id"] == "111")
    bench = next(r for r in roster_slots if r["platform_player_id"] == "112")

    assert starter["position"] == "QB"
    assert starter["is_starter"] is True
    assert starter["team"] == "KC"
    assert starter["injury_status"] == "QUESTIONABLE"
    assert bench["position"] == "RB"
    assert bench["is_starter"] is False
    assert bench["team"] is None
