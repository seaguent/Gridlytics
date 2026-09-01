from dataclasses import dataclass

import pandas as pd

from app.projections.blending import prior_season_weight

MIN_SAMPLE_SIZE = 2
FULL_TRANSITION_GAMES = 8
LOW_PERCENTILE = 0.2
HIGH_PERCENTILE = 0.8


@dataclass
class UncertaintyRange:
    floor: float | None
    ceiling: float | None
    confidence: float | None
    range_source: str | None
    sample_size: int


def _percentile_ratios(scores: list[float]) -> tuple[float, float, float] | None:
    if len(scores) < MIN_SAMPLE_SIZE:
        return None
    series = pd.Series(scores)
    mean = series.mean()
    if mean == 0 or pd.isna(mean):
        return None
    low = series.quantile(LOW_PERCENTILE) / mean
    high = series.quantile(HIGH_PERCENTILE) / mean
    std = series.std()
    confidence = 1 / (1 + (std / mean)) if not pd.isna(std) and std != 0 else 1.0
    return low, high, confidence


def compute_uncertainty_range(
    projected_points: float,
    current_season_scores: list[float],
    prior_season_scores: list[float] | None,
    position_prior: tuple[float, float, int] | None,
    team_changed: bool = False,
) -> UncertaintyRange:
    n_current = len(current_season_scores)
    # A team change makes the prior team's week-to-week volatility an unreliable guide to this one.
    effective_prior_scores = None if team_changed else prior_season_scores

    current_ratios = _percentile_ratios(current_season_scores)
    prior_ratios = _percentile_ratios(effective_prior_scores) if effective_prior_scores else None

    if current_ratios is not None and n_current >= FULL_TRANSITION_GAMES:
        low, high, confidence = current_ratios
        source, sample_size = "current_season", n_current
    elif current_ratios is not None and prior_ratios is not None:
        weight = prior_season_weight(n_current)
        low = weight * prior_ratios[0] + (1 - weight) * current_ratios[0]
        high = weight * prior_ratios[1] + (1 - weight) * current_ratios[1]
        confidence = weight * prior_ratios[2] + (1 - weight) * current_ratios[2]
        source, sample_size = "blended_history", n_current + len(effective_prior_scores)
    elif current_ratios is not None:
        low, high, confidence = current_ratios
        source, sample_size = "current_season", n_current
    elif prior_ratios is not None:
        low, high, confidence = prior_ratios
        source, sample_size = "prior_season", len(effective_prior_scores)
    elif position_prior is not None:
        low, high, sample_size = position_prior
        confidence = None
        source = "position_prior"
    else:
        return UncertaintyRange(None, None, None, None, n_current)

    floor = max(0.0, projected_points * low)
    ceiling = projected_points * high
    return UncertaintyRange(floor, ceiling, confidence, source, sample_size)
