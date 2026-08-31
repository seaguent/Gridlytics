import copy

from app.espn.parser import parse_projections
from app.espn.schemas import EspnLeagueResponse
from tests.espn.test_parser import SAMPLE_RAW


def _sample_with_stats() -> EspnLeagueResponse:
    raw = copy.deepcopy(SAMPLE_RAW)
    # currentMatchupPeriod is 3 in the shared fixture.
    raw["teams"][0]["roster"]["entries"][0]["playerPoolEntry"]["player"]["stats"] = [
        {"scoringPeriodId": 3, "statSourceId": 1, "appliedTotal": 18.2},  # projected, current week
        {"scoringPeriodId": 3, "statSourceId": 0, "appliedTotal": 21.4},  # actual, current week
        {"scoringPeriodId": 2, "statSourceId": 1, "appliedTotal": 15.0},  # projected, old week
    ]
    raw["teams"][0]["roster"]["entries"][1]["playerPoolEntry"]["player"]["stats"] = []
    return EspnLeagueResponse.model_validate(raw)


def test_parse_projections_uses_projected_stat_for_current_period():
    projections = parse_projections(_sample_with_stats())

    assert len(projections) == 1
    projection = projections[0]
    assert projection["platform_player_id"] == "111"
    assert projection["projected_points"] == 18.2
    assert projection["name"] == "Starter QB"
    assert projection["position"] == "QB"


def test_parse_projections_skips_players_with_no_current_week_projection():
    projections = parse_projections(_sample_with_stats())
    ids = {p["platform_player_id"] for p in projections}

    assert "112" not in ids  # no stats at all
