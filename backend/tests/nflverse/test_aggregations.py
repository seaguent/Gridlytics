import pandas as pd

from app.nflverse.aggregations import compute_position_defense_strength, compute_red_zone_opportunities


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
