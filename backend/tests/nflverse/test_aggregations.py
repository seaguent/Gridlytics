import pandas as pd

from app.nflverse.aggregations import (
    compute_position_defense_strength,
    compute_position_volatility_priors,
    compute_red_zone_opportunities,
)


def test_compute_red_zone_opportunities_counts_pass_and_rush_attempts_inside_the_20():
    pbp = pd.DataFrame(
        [
            # red zone pass target
            {
                "season_type": "REG", "week": 1, "yardline_100": 15,
                "pass_attempt": 1, "rush_attempt": 0,
                "receiver_player_id": "00-1", "rusher_player_id": None,
            },
            # red zone carry
            {
                "season_type": "REG", "week": 1, "yardline_100": 5,
                "pass_attempt": 0, "rush_attempt": 1,
                "receiver_player_id": None, "rusher_player_id": "00-2",
            },
            # outside the red zone -- should not count
            {
                "season_type": "REG", "week": 1, "yardline_100": 45,
                "pass_attempt": 1, "rush_attempt": 0,
                "receiver_player_id": "00-1", "rusher_player_id": None,
            },
            # playoff week -- should not count
            {
                "season_type": "POST", "week": 19, "yardline_100": 10,
                "pass_attempt": 1, "rush_attempt": 0,
                "receiver_player_id": "00-1", "rusher_player_id": None,
            },
        ]
    )

    result = compute_red_zone_opportunities(pbp)
    by_player = {(row["gsis_id"], row["week"]): row["red_zone_opportunities"] for _, row in result.iterrows()}

    assert by_player[("00-1", 1)] == 1
    assert by_player[("00-2", 1)] == 1
    assert ("00-1", 19) not in by_player


def test_compute_red_zone_opportunities_returns_empty_dataframe_for_empty_input():
    result = compute_red_zone_opportunities(pd.DataFrame())
    assert result.empty
    assert list(result.columns) == ["gsis_id", "week", "red_zone_opportunities"]


def test_compute_position_defense_strength_averages_points_allowed_by_position():
    weekly_stats = pd.DataFrame(
        [
            {"season_type": "REG", "opponent_team": "KC", "position": "WR", "fantasy_points_ppr": 20.0},
            {"season_type": "REG", "opponent_team": "KC", "position": "WR", "fantasy_points_ppr": 10.0},
            {"season_type": "REG", "opponent_team": "KC", "position": "RB", "fantasy_points_ppr": 5.0},
            {"season_type": "POST", "opponent_team": "KC", "position": "WR", "fantasy_points_ppr": 100.0},
        ]
    )

    result = compute_position_defense_strength(weekly_stats)
    by_key = {(row["opponent_team"], row["position"]): row["points_allowed_avg"] for _, row in result.iterrows()}

    assert by_key[("KC", "WR")] == 15.0
    assert by_key[("KC", "RB")] == 5.0


def _weekly_rows(player_id: str, position: str, scores: list[float]) -> list[dict]:
    return [
        {"player_id": player_id, "position": position, "season_type": "REG", "week": i + 1, "fantasy_points_ppr": s}
        for i, s in enumerate(scores)
    ]


def test_compute_position_volatility_priors_pools_normalized_ratios_by_position():
    rows = []
    # 3 RBs, each with their own average level but real week-to-week spread -- enough to pool.
    rows += _weekly_rows("rb-1", "RB", [8.0, 12.0, 4.0, 16.0])
    rows += _weekly_rows("rb-2", "RB", [16.0, 24.0, 8.0, 32.0])
    rows += _weekly_rows("rb-3", "RB", [6.0, 9.0, 3.0, 12.0])
    # A single WR with too few games to contribute a personal ratio -- should be excluded.
    rows += _weekly_rows("wr-1", "WR", [10.0, 12.0])

    weekly_stats = pd.DataFrame(rows)
    result = compute_position_volatility_priors(weekly_stats)

    assert "RB" in result
    low, high, sample_size = result["RB"]
    assert low < 1.0 < high
    assert sample_size == 12
    assert "WR" not in result


def test_compute_position_volatility_priors_excludes_non_regular_season_games():
    rows = _weekly_rows("rb-1", "RB", [8.0, 12.0, 4.0, 16.0])
    rows += _weekly_rows("rb-2", "RB", [16.0, 24.0, 8.0, 32.0])
    rows += _weekly_rows("rb-3", "RB", [6.0, 9.0, 3.0, 12.0])
    for row in _weekly_rows("rb-4", "RB", [100.0, 100.0, 100.0, 100.0]):
        row["season_type"] = "POST"
        rows.append(row)

    weekly_stats = pd.DataFrame(rows)
    result = compute_position_volatility_priors(weekly_stats)

    assert result["RB"][2] == 12


def test_compute_position_volatility_priors_returns_empty_dict_for_empty_input():
    assert compute_position_volatility_priors(pd.DataFrame()) == {}
