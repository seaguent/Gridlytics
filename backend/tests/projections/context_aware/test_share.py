import pytest

from app.projections.context_aware.share import estimate_player_share


def test_no_data_at_all_falls_back_to_role_rank_prior():
    result = estimate_player_share([], None, role_rank_prior_share=0.15, team_changed=False, role_changed_recently=False)
    assert result == pytest.approx(0.15)


def test_no_data_and_no_role_prior_returns_none():
    result = estimate_player_share([], None, role_rank_prior_share=None, team_changed=False, role_changed_recently=False)
    assert result is None


def test_no_current_uses_prior_season_share_when_stable():
    result = estimate_player_share([], [0.20, 0.22, 0.18], role_rank_prior_share=0.10, team_changed=False, role_changed_recently=False)
    assert result == pytest.approx(0.20)


def test_team_change_zeroes_out_prior_share_entirely():
    result = estimate_player_share([], [0.20, 0.22, 0.18], role_rank_prior_share=0.10, team_changed=True, role_changed_recently=False)
    assert result == pytest.approx(0.10)  # falls all the way to role prior, prior share ignored


def test_role_change_softly_discounts_prior_share_without_a_team_change():
    result = estimate_player_share([], [0.20, 0.20, 0.20], role_rank_prior_share=0.10, team_changed=False, role_changed_recently=True)
    # ROLE_CHANGE_DISCOUNT = 0.5 -> effective_prior = 0.20 * 0.5 = 0.10
    assert result == pytest.approx(0.10)


def test_full_current_season_ignores_prior():
    current = [0.30] * 8  # 8 games -- prior_season_weight(8) == 0.0
    result = estimate_player_share(current, [0.10, 0.10], role_rank_prior_share=0.05, team_changed=False, role_changed_recently=False)
    assert result == pytest.approx(0.30)


def test_small_current_sample_blends_toward_prior():
    current = [0.30, 0.30]  # 2 games -- prior_season_weight(2) = 0.75
    prior = [0.10] * 6
    result = estimate_player_share(current, prior, role_rank_prior_share=0.05, team_changed=False, role_changed_recently=False)
    assert result == pytest.approx(0.75 * 0.10 + 0.25 * 0.30)
