import pandas as pd


def compute_floor_ceiling_confidence(scores: pd.Series) -> tuple[float, float, float]:
    mean = scores.mean()
    std = scores.std()

    if pd.isna(std) or std == 0:
        return max(0.0, mean), mean, 1.0

    floor = max(0.0, mean - std)
    ceiling = mean + std
    confidence = 1 / (1 + (std / mean)) if mean != 0 else 0.0
    return floor, ceiling, confidence
