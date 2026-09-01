import pytest

from app.projections.native.historical_baseline import project_historical_recency


def test_fewer_than_min_weeks_returns_none():
    assert project_historical_recency([12.0]) is None
    assert project_historical_recency([]) is None


def test_two_weeks_produces_a_decay_weighted_average():
    # Most recent week weighted higher via decay=0.75: weights [1.0, 0.75] for [newest, oldest].
    result = project_historical_recency([10.0, 20.0])  # week order: oldest-first, so 20.0 is most recent
    # weighted = (20.0*1.0 + 10.0*0.75) / (1.0 + 0.75) = (20 + 7.5) / 1.75 = 15.714285...
    assert result == pytest.approx(15.714285714285714)


def test_only_last_num_weeks_considered():
    # 6 real weeks, num_weeks=5 -- the oldest (first) week must be excluded entirely.
    points = [1000.0, 10.0, 10.0, 10.0, 10.0, 10.0]  # first value is an outlier outside the window
    result = project_historical_recency(points, num_weeks=5)
    assert result == pytest.approx(10.0)
