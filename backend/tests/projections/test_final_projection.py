import pytest

from app.projections.final_projection import GRIDLYTICS_BLEND_WEIGHT, compute_final_projection


def test_healthy_blend_averages_both_sources():
    result = compute_final_projection(
        gridlytics_base=12.0, platform_projection=10.0, availability_status="healthy"
    )
    assert result == pytest.approx(11.0)


def test_large_disagreement_still_uses_the_plain_blend_formula():
    # Real-shaped case: our model and the platform disagree a lot (e.g. a player coming off
    # injury where the platform has real severity information we don't). No special-casing --
    # the blend is a plain 50/50 average even when the two sides are far apart.
    result = compute_final_projection(
        gridlytics_base=16.0, platform_projection=8.0, availability_status="questionable"
    )
    assert result == pytest.approx(12.0)


def test_missing_platform_projection_uses_gridlytics_base_only():
    result = compute_final_projection(
        gridlytics_base=14.0, platform_projection=None, availability_status="healthy"
    )
    assert result == pytest.approx(14.0)


def test_legitimate_zero_confirmed_unavailable_returns_zero():
    result = compute_final_projection(
        gridlytics_base=14.0, platform_projection=0.0, availability_status="unavailable"
    )
    assert result == pytest.approx(0.0)


def test_suspicious_zero_without_unavailable_status_uses_gridlytics_base_only():
    # Platform reports 0 but nothing confirms the player is actually out/IR/bye -- treat the
    # platform number as missing/unreliable rather than averaging toward a fabricated zero.
    result = compute_final_projection(
        gridlytics_base=14.0, platform_projection=0.0, availability_status="questionable"
    )
    assert result == pytest.approx(14.0)


def test_suspicious_zero_with_unknown_availability_uses_gridlytics_base_only():
    result = compute_final_projection(
        gridlytics_base=14.0, platform_projection=0.0, availability_status=None
    )
    assert result == pytest.approx(14.0)


def test_unavailable_player_returns_zero_regardless_of_real_projection_values():
    # Unavailable always wins, even when both sides have real nonzero numbers.
    result = compute_final_projection(
        gridlytics_base=25.0, platform_projection=20.0, availability_status="unavailable"
    )
    assert result == pytest.approx(0.0)


def test_both_sources_missing_returns_none_not_a_fabricated_zero():
    result = compute_final_projection(
        gridlytics_base=None, platform_projection=None, availability_status="healthy"
    )
    assert result is None


def test_missing_gridlytics_base_falls_back_to_platform_only():
    result = compute_final_projection(
        gridlytics_base=None, platform_projection=9.0, availability_status="healthy"
    )
    assert result == pytest.approx(9.0)


def test_weight_is_configurable_not_hardcoded():
    result = compute_final_projection(
        gridlytics_base=20.0, platform_projection=10.0, availability_status="healthy", weight=0.75
    )
    assert result == pytest.approx(0.75 * 20.0 + 0.25 * 10.0)


def test_default_weight_constant_is_fifty_fifty():
    assert GRIDLYTICS_BLEND_WEIGHT == pytest.approx(0.5)
