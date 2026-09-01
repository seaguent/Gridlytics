import pytest

from app.projections.uncertainty import compute_uncertainty_range


def test_sufficient_current_season_history_uses_current_season_source():
    # 8 real current-season games -- enough to trust on its own, no need for a prior-season blend.
    current = [18.0, 20.0, 16.0, 22.0, 19.0, 21.0, 17.0, 23.0]

    result = compute_uncertainty_range(
        projected_points=20.0, current_season_scores=current, prior_season_scores=[10.0, 30.0], position_prior=None
    )

    assert result.range_source == "current_season"
    assert result.sample_size == 8
    assert result.floor is not None and result.ceiling is not None
    assert result.floor < 20.0 < result.ceiling


def test_preseason_veteran_with_zero_current_games_uses_prior_season():
    prior = [24.6, 12.1, 30.0, 18.0, 15.5, 20.0]

    result = compute_uncertainty_range(
        projected_points=21.1, current_season_scores=[], prior_season_scores=prior, position_prior=None
    )

    assert result.range_source == "prior_season"
    assert result.sample_size == len(prior)
    assert result.floor is not None and result.ceiling is not None
    # range should be centered around the current projection, not the prior season's raw point totals
    assert 0 < result.floor < 21.1 < result.ceiling


def test_week_one_veteran_with_one_current_game_and_prior_season_blends():
    prior = [24.6, 12.1, 30.0, 18.0, 15.5, 20.0]

    # Only 1 current game -- can't compute its own percentile ratios (needs >=2), so this still
    # falls back to prior_season rather than fabricating a "blend" from one data point.
    result = compute_uncertainty_range(
        projected_points=21.1, current_season_scores=[19.0], prior_season_scores=prior, position_prior=None
    )
    assert result.range_source == "prior_season"

    # 2+ current games -- now a real blend can happen.
    result = compute_uncertainty_range(
        projected_points=21.1, current_season_scores=[19.0, 22.0], prior_season_scores=prior, position_prior=None
    )
    assert result.range_source == "blended_history"
    assert result.sample_size == 2 + len(prior)


def test_blend_weight_shifts_toward_current_season_as_games_accumulate():
    prior = [20.0, 20.0, 20.0, 20.0, 20.0, 20.0]  # tight, consistent prior distribution
    # a much more volatile current-season role (boom/bust), same average level as prior
    current_pool = [4.0, 36.0, 4.0, 36.0, 4.0, 36.0, 4.0, 36.0, 4.0, 36.0]

    two_games = compute_uncertainty_range(20.0, current_pool[:2], prior, None)
    seven_games = compute_uncertainty_range(20.0, current_pool[:7], prior, None)

    # More current games observed -> the range should widen toward the more volatile current regime.
    assert two_games.ceiling < seven_games.ceiling
    assert two_games.range_source == "blended_history"
    assert seven_games.range_source == "blended_history"


def test_rookie_with_no_history_uses_position_prior():
    result = compute_uncertainty_range(
        projected_points=17.6,
        current_season_scores=[],
        prior_season_scores=None,
        position_prior=(0.6, 1.4, 850),
    )

    assert result.range_source == "position_prior"
    assert result.sample_size == 850
    assert result.confidence is None
    assert result.floor == pytest.approx(17.6 * 0.6)
    assert result.ceiling == pytest.approx(17.6 * 1.4)


def test_team_change_discounts_stale_prior_season_but_still_uses_current_if_available():
    prior = [24.6, 12.1, 30.0, 18.0, 15.5, 20.0]

    # Team changed, no current-season games yet, no position prior -- nothing trustworthy left.
    result = compute_uncertainty_range(21.1, [], prior, None, team_changed=True)
    assert result.range_source is None
    assert result.floor is None

    # Team changed, but has some real current-season games on the NEW team -- use those instead.
    result = compute_uncertainty_range(21.1, [18.0, 20.0], prior, None, team_changed=True)
    assert result.range_source == "current_season"


def test_insufficient_history_and_no_position_prior_returns_no_range():
    result = compute_uncertainty_range(
        projected_points=8.5, current_season_scores=[], prior_season_scores=None, position_prior=None
    )

    assert result.floor is None
    assert result.ceiling is None
    assert result.confidence is None
    assert result.range_source is None


def test_floor_never_goes_negative():
    result = compute_uncertainty_range(
        projected_points=2.0, current_season_scores=[0.0, 0.0, 5.0, 0.0], prior_season_scores=None, position_prior=None
    )
    assert result.floor >= 0.0
