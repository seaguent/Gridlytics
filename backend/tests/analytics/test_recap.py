import pandas as pd

from app.analytics.recap import generate_weekly_recap

# Scenario: A(130) beat C(100); B(90) beat D(85).
# Power scores: A=90, B=40, C=70, D=60.
# -> A beating C is chalk (A was favored by power). B beating D is the
#    upset (B was a big underdog by power, but won anyway).
# -> Ranking all 4 scores that week: D=1st(lowest), B=2nd, C=3rd, A=4th
#    (highest) -> all-play fractions D=0, B=1/3, C=2/3, A=1.0.
#    Of the two LOSERS (C, D), C had the better week (2/3) but still lost
#    because they faced the week's top scorer -> C is "unluckiest".


def _week_scores() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"team_id": "A", "points": 130, "opponent_team_id": "C"},
            {"team_id": "B", "points": 90, "opponent_team_id": "D"},
            {"team_id": "C", "points": 100, "opponent_team_id": "A"},
            {"team_id": "D", "points": 85, "opponent_team_id": "B"},
        ]
    )


def _power_scores() -> dict:
    return {"A": 90, "B": 40, "C": 70, "D": 60}


def _bench_points() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"team_id": "A", "bench_points": 5},
            {"team_id": "B", "bench_points": 25},
            {"team_id": "C", "bench_points": 10},
            {"team_id": "D", "bench_points": 8},
        ]
    )


def test_generate_weekly_recap_matches_hand_calculation():
    recap = generate_weekly_recap(_week_scores(), _power_scores(), _bench_points())

    assert recap["highest_scorer"] == {"team_id": "A", "points": 130}
    assert recap["lowest_scorer"] == {"team_id": "D", "points": 85}

    assert recap["closest_game"]["margin"] == 5
    assert {recap["closest_game"]["team_a"], recap["closest_game"]["team_b"]} == {"B", "D"}

    assert recap["biggest_upset"] == {"winner_team_id": "B", "loser_team_id": "D", "power_gap": 20}

    assert recap["unluckiest_team"]["team_id"] == "C"
    assert recap["unluckiest_team"]["all_play_win_fraction"] == 2 / 3

    assert recap["worst_bench_decision"] == {"team_id": "B", "bench_points": 25}


def test_generate_weekly_recap_handles_no_upset():
    # Favorite (by power) wins every game -> no "upset" to report.
    week_scores = pd.DataFrame(
        [
            {"team_id": "A", "points": 120, "opponent_team_id": "B"},
            {"team_id": "B", "points": 100, "opponent_team_id": "A"},
        ]
    )
    power_scores = {"A": 90, "B": 40}
    bench_points = pd.DataFrame(columns=["team_id", "bench_points"])

    recap = generate_weekly_recap(week_scores, power_scores, bench_points)

    assert recap["biggest_upset"] is None
    assert recap["worst_bench_decision"] is None
