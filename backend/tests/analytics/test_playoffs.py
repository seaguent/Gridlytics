from app.analytics.playoffs import simulate_season


def test_simulate_season_with_no_remaining_games_is_fully_determined():
    current_records = {
        "A": {"wins": 8, "losses": 2, "points_for": 1200},
        "B": {"wins": 6, "losses": 4, "points_for": 1100},
        "C": {"wins": 5, "losses": 5, "points_for": 1150},
        "D": {"wins": 2, "losses": 8, "points_for": 900},
    }
    team_score_dist = {team_id: {"mean": 100, "std": 15} for team_id in current_records}

    result = simulate_season(
        current_records=current_records,
        team_score_dist=team_score_dist,
        remaining_schedule=[],
        playoff_spots=2,
        num_trials=100,
    )

    # No games left -> locked in by (wins, points_for): A(8,1200), B(6,1100), C(5,1150), D(2,900); top 2 = A, B.
    assert result["A"]["playoff_odds"] == 1.0
    assert result["B"]["playoff_odds"] == 1.0
    assert result["C"]["playoff_odds"] == 0.0
    assert result["D"]["playoff_odds"] == 0.0


def test_simulate_season_favors_higher_scoring_team():
    current_records = {
        "high": {"wins": 5, "losses": 5, "points_for": 1000},
        "low": {"wins": 5, "losses": 5, "points_for": 1000},
        "opp1": {"wins": 5, "losses": 5, "points_for": 1000},
        "opp2": {"wins": 5, "losses": 5, "points_for": 1000},
    }
    team_score_dist = {
        "high": {"mean": 130, "std": 10},
        "low": {"mean": 90, "std": 10},
        "opp1": {"mean": 100, "std": 10},
        "opp2": {"mean": 100, "std": 10},
    }
    remaining_schedule = [
        (11, "high", "opp1"),
        (11, "low", "opp2"),
    ]

    result = simulate_season(
        current_records=current_records,
        team_score_dist=team_score_dist,
        remaining_schedule=remaining_schedule,
        playoff_spots=2,
        num_trials=2000,
        seed=42,
    )

    assert result["high"]["playoff_odds"] > result["low"]["playoff_odds"]


def test_simulate_season_is_reproducible_with_same_seed():
    current_records = {
        "A": {"wins": 5, "losses": 5, "points_for": 1000},
        "B": {"wins": 5, "losses": 5, "points_for": 1000},
    }
    team_score_dist = {team_id: {"mean": 100, "std": 15} for team_id in current_records}
    remaining_schedule = [(11, "A", "B")]

    result1 = simulate_season(
        current_records=current_records,
        team_score_dist=team_score_dist,
        remaining_schedule=remaining_schedule,
        playoff_spots=1,
        num_trials=500,
        seed=7,
    )
    result2 = simulate_season(
        current_records=current_records,
        team_score_dist=team_score_dist,
        remaining_schedule=remaining_schedule,
        playoff_spots=1,
        num_trials=500,
        seed=7,
    )

    assert result1 == result2
