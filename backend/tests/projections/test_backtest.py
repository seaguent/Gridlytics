import pytest

from app.projections.backtest import compare_providers, compute_mae, compute_rmse, compute_start_sit_accuracy


def test_compute_mae_matches_hand_calculation():
    # errors: |20-18|=2, |15-20|=5, |10-8|=2 -> mean = 3.0
    predictions = [(20, 18), (15, 20), (10, 8)]
    assert compute_mae(predictions) == pytest.approx(3.0)


def test_compute_rmse_matches_hand_calculation():
    # squared errors: 4, 25, 4 -> mean = 11 -> sqrt(11) ~= 3.3166
    predictions = [(20, 18), (15, 20), (10, 8)]
    assert compute_rmse(predictions) == pytest.approx(3.3166, abs=0.001)


def test_compute_rmse_penalizes_large_errors_more_than_mae():
    # One big miss should push RMSE further above MAE than a set of small ones.
    predictions = [(10, 10), (10, 10), (10, 30)]  # one huge miss of 20
    mae = compute_mae(predictions)
    rmse = compute_rmse(predictions)
    assert rmse > mae


def test_compute_start_sit_accuracy_matches_hand_calculation():
    # (started_proj, started_actual, benched_proj, benched_actual)
    decisions = [
        (20, 18, 10, 8),  # projection said started > benched; actual agrees -> correct
        (12, 5, 18, 25),  # projection said benched > started; actual agrees -> correct
        (15, 10, 10, 20),  # projection said started > benched; actual disagrees -> wrong
    ]
    assert compute_start_sit_accuracy(decisions) == pytest.approx(2 / 3)


def test_compare_providers_ranks_by_mae_ascending():
    results = {
        "historical_average": [(20, 15), (10, 5)],  # errors 5, 5 -> MAE 5.0
        "espn": [(20, 19), (10, 9)],  # errors 1, 1 -> MAE 1.0
    }
    ranked = compare_providers(results)

    assert [row["source"] for row in ranked] == ["espn", "historical_average"]
    assert ranked[0]["mae"] == pytest.approx(1.0)
    assert ranked[1]["mae"] == pytest.approx(5.0)
