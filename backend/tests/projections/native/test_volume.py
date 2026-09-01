import pytest

from app.projections.native.volume import project_expected_volume


def test_no_data_at_all_returns_none():
    assert project_expected_volume([], None) is None


def test_no_current_season_uses_prior_season_average():
    result = project_expected_volume([], [8.0, 10.0, 12.0])
    assert result == pytest.approx(10.0)


def test_team_change_discounts_prior_season_volume_to_none():
    result = project_expected_volume([], [8.0, 10.0, 12.0], team_changed=True)
    assert result is None


def test_full_current_season_history_ignores_prior_season():
    # 8 games played -- prior_season_weight(8) == 0.0, so the prior shouldn't matter at all.
    current = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    result = project_expected_volume(current, [100.0])
    assert result == pytest.approx(10.0)


def test_small_current_sample_blends_toward_prior_season():
    # 2 games played -- prior_season_weight(2) = 1 - 2/8 = 0.75.
    current = [20.0, 20.0]
    prior = [10.0] * 6
    result = project_expected_volume(current, prior)
    # current_estimate = 20 (recent == season avg here); 0.75*10 + 0.25*20 = 7.5 + 5.0 = 12.5
    assert result == pytest.approx(12.5)


def test_recent_games_weighted_more_than_full_season_average():
    # Season average pulled down by an early slump; recent games show a real uptick.
    current = [4.0, 4.0, 4.0, 4.0, 4.0, 16.0, 16.0, 16.0]  # season avg=8.5, last 3 avg=16.0
    result = project_expected_volume(current, None)
    # prior_season_weight(8) == 0 -> pure current_estimate = 0.6*16.0 + 0.4*8.5 = 13.0
    assert result == pytest.approx(13.0)
