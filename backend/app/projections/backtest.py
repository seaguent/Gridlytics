def compute_mae(predictions: list[tuple[float, float]]) -> float:
    errors = [abs(projected - actual) for projected, actual in predictions]
    return sum(errors) / len(errors)


def compute_rmse(predictions: list[tuple[float, float]]) -> float:
    squared_errors = [(projected - actual) ** 2 for projected, actual in predictions]
    return (sum(squared_errors) / len(squared_errors)) ** 0.5


def compute_start_sit_accuracy(decisions: list[tuple[float, float, float, float]]) -> float:
    correct = 0
    for started_proj, started_actual, benched_proj, benched_actual in decisions:
        predicted_start_better = started_proj > benched_proj
        actual_start_better = started_actual > benched_actual
        if predicted_start_better == actual_start_better:
            correct += 1
    return correct / len(decisions)


def compare_providers(results: dict[str, list[tuple[float, float]]]) -> list[dict]:
    rows = [
        {
            "source": source,
            "mae": compute_mae(predictions),
            "rmse": compute_rmse(predictions),
            "n": len(predictions),
        }
        for source, predictions in results.items()
    ]
    return sorted(rows, key=lambda row: row["mae"])
