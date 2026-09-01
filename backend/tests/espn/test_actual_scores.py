import copy

from app.espn.parser import parse_actual_scores
from app.espn.schemas import EspnLeagueResponse
from tests.espn.test_parser import SAMPLE_RAW


def _sample_with_actual_history() -> EspnLeagueResponse:
    raw = copy.deepcopy(SAMPLE_RAW)
    raw["teams"][0]["roster"]["entries"][0]["playerPoolEntry"]["player"]["stats"] = [
        {"scoringPeriodId": 3, "statSourceId": 1, "appliedTotal": 18.2},
        {"scoringPeriodId": 1, "statSourceId": 0, "appliedTotal": 24.6},
        {"scoringPeriodId": 2, "statSourceId": 0, "appliedTotal": 12.1},
        # future/not-yet-played week -- projected only, no actual entry at all
        {"scoringPeriodId": 3, "statSourceId": 1, "appliedTotal": 20.0},
    ]
    raw["teams"][0]["roster"]["entries"][1]["playerPoolEntry"]["player"]["stats"] = [
        {"scoringPeriodId": 1, "statSourceId": 0, "appliedTotal": 5.3},
    ]
    return EspnLeagueResponse.model_validate(raw)


def test_parse_actual_scores_returns_one_row_per_real_week():
    scores = parse_actual_scores(_sample_with_actual_history())
    starter_scores = {s["week"]: s["points"] for s in scores if s["platform_player_id"] == "111"}

    assert starter_scores == {1: 24.6, 2: 12.1}
    assert 3 not in starter_scores


def test_parse_actual_scores_covers_every_rostered_player():
    scores = parse_actual_scores(_sample_with_actual_history())
    bench_scores = [s for s in scores if s["platform_player_id"] == "112"]

    assert len(bench_scores) == 1
    assert bench_scores[0]["week"] == 1
    assert bench_scores[0]["points"] == 5.3


def test_parse_actual_scores_ignores_stats_with_no_applied_total():
    raw = copy.deepcopy(SAMPLE_RAW)
    raw["teams"][0]["roster"]["entries"][0]["playerPoolEntry"]["player"]["stats"] = [
        {"scoringPeriodId": 1, "statSourceId": 0, "appliedTotal": None},
    ]
    scores = parse_actual_scores(EspnLeagueResponse.model_validate(raw))

    assert scores == []


def test_parse_actual_scores_returns_empty_list_for_no_stats():
    scores = parse_actual_scores(EspnLeagueResponse.model_validate(SAMPLE_RAW))
    assert scores == []
