import pandas as pd

MIN_SAMPLE_SIZE = 2


def compute_floor_ceiling_confidence(
    scores: pd.Series,
) -> tuple[float | None, float | None, float | None]:
    # Fewer than 2 points can't support a real std -- don't fabricate confidence=1.0 from one game.
    if len(scores) < MIN_SAMPLE_SIZE:
        return None, None, None

    mean = scores.mean()
    std = scores.std()

    if pd.isna(std) or std == 0:
        return max(0.0, mean), mean, 1.0

    floor = max(0.0, mean - std)
    ceiling = mean + std
    confidence = 1 / (1 + (std / mean)) if mean != 0 else 0.0
    return floor, ceiling, confidence
