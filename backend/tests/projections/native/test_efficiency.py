import pytest

from app.projections.native.efficiency import estimate_player_efficiency


def test_no_games_returns_position_average():
    result = estimate_player_efficiency([], position_average=0.5)
    assert result == 0.5


def test_full_confidence_games_mostly_trusts_own_rate():
    # 8 games at a consistent personal rate -- weight = 1.0, fully the player's own rate.
    per_game = [0.9] * 8
    result = estimate_player_efficiency(per_game, position_average=0.5)
    assert result == pytest.approx(0.9)


def test_small_sample_shrinks_heavily_toward_position_average():
    # 2 games -- weight = 2/8 = 0.25.
    per_game = [0.9, 0.9]
    result = estimate_player_efficiency(per_game, position_average=0.5)
    # 0.25*0.9 + 0.75*0.5 = 0.6
    assert result == pytest.approx(0.6)


def test_team_change_applies_additional_discount():
    per_game = [0.9] * 8  # would normally be weight=1.0
    result = estimate_player_efficiency(per_game, position_average=0.5, team_changed=True)
    # weight = 1.0 * 0.5 (team-change discount) = 0.5 -> 0.5*0.9 + 0.5*0.5 = 0.7
    assert result == pytest.approx(0.7)


def test_outlier_game_is_capped_before_averaging():
    # position_average=0.5 -> cap = 1.5. One huge game (5.0) must not swing the average unchecked.
    per_game = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 5.0]
    result = estimate_player_efficiency(per_game, position_average=0.5)
    # capped values: seven 0.5s + one 1.5 -> avg = (3.5 + 1.5) / 8 = 0.625; weight=1.0 (8 games)
    assert result == pytest.approx(0.625)


def test_non_positive_position_average_skips_capping():
    # A legitimately ~0 position average (e.g. a rare rate) shouldn't zero out every real value.
    per_game = [0.1, 0.2]
    result = estimate_player_efficiency(per_game, position_average=0.0)
    # weight = 2/8 = 0.25; uncapped avg = 0.15 -> 0.25*0.15 + 0.75*0.0 = 0.0375
    assert result == pytest.approx(0.0375)
