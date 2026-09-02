import pytest

from app.projections.context_aware.conflict import detect_projection_conflict


def test_kamara_style_conflict_platform_zero_plus_questionable():
    is_conflict, reason = detect_projection_conflict(
        context_aware_points=9.5, platform_points=0.0, availability_status="questionable",
        team_changed=False, role_confidence="high",
    )
    assert is_conflict is True
    assert "questionable" in reason.lower()


def test_stable_veteran_normal_agreement_is_not_a_conflict():
    is_conflict, reason = detect_projection_conflict(
        context_aware_points=18.9, platform_points=17.8, availability_status="healthy",
        team_changed=False, role_confidence="high",
    )
    assert is_conflict is False
    assert reason is None


def test_missing_platform_projection_is_not_a_conflict():
    is_conflict, reason = detect_projection_conflict(
        context_aware_points=12.0, platform_points=None, availability_status="healthy",
        team_changed=False, role_confidence="high",
    )
    assert is_conflict is False
    assert reason is None


def test_platform_zero_with_no_risk_signals_is_not_flagged():
    # Both near zero, or platform zero with a fully healthy/stable/high-confidence context --
    # not enough to call it a conflict.
    is_conflict, reason = detect_projection_conflict(
        context_aware_points=0.5, platform_points=0.0, availability_status="healthy",
        team_changed=False, role_confidence="high",
    )
    assert is_conflict is False


def test_platform_zero_plus_team_change_and_low_role_confidence_combines_reasons():
    is_conflict, reason = detect_projection_conflict(
        context_aware_points=10.0, platform_points=0.0, availability_status="healthy",
        team_changed=True, role_confidence="unknown",
    )
    assert is_conflict is True
    assert "team change" in reason.lower()
    assert "role" in reason.lower()


def test_magnitude_disagreement_flagged_with_a_real_context_risk_signal():
    # Both real and positive, clearly below the disagreement ratio (6/20=0.3 < 0.4), WITH a QB
    # change present.
    is_conflict, reason = detect_projection_conflict(
        context_aware_points=20.0, platform_points=6.0,
        availability_status="healthy", team_changed=False, role_confidence="high", qb_changed=True,
    )
    assert is_conflict is True
    assert "qb change" in reason.lower()


def test_magnitude_disagreement_not_flagged_without_any_context_risk_signal():
    # Same divergence, but nothing risky about the context -- disagreement alone is not a conflict.
    is_conflict, reason = detect_projection_conflict(
        context_aware_points=20.0, platform_points=6.0,
        availability_status="healthy", team_changed=False, role_confidence="high", qb_changed=False,
    )
    assert is_conflict is False


def test_magnitude_disagreement_not_flagged_when_projections_roughly_agree():
    is_conflict, reason = detect_projection_conflict(
        context_aware_points=20.0, platform_points=18.5,
        availability_status="healthy", team_changed=False, role_confidence="high", qb_changed=True,
    )
    assert is_conflict is False


def test_existing_near_zero_case_still_works_unchanged():
    is_conflict, reason = detect_projection_conflict(
        context_aware_points=15.0, platform_points=0.5,
        availability_status="questionable", team_changed=False, role_confidence="high",
    )
    assert is_conflict is True
    assert "questionable" in reason.lower()


def test_platform_points_is_never_written_into_the_math_diagnostic_only():
    # Direct regression test for the diagnostic-only guardrail: calling detect_projection_conflict
    # must not mutate or return any value derived arithmetically from platform_points -- it
    # returns only (bool, str | None), never a number.
    result = detect_projection_conflict(
        context_aware_points=20.0, platform_points=8.0,
        availability_status="healthy", team_changed=False, role_confidence="high", qb_changed=True,
    )
    assert isinstance(result, tuple) and len(result) == 2
    assert isinstance(result[0], bool)
    assert result[1] is None or isinstance(result[1], str)
