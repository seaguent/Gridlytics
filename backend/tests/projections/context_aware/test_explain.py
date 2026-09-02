import pytest

from app.projections.context_aware.explain import explain_projection
from app.projections.context_aware.model import CareerAwareBreakdown, CategoryShareBreakdown, EffectivePrior
from app.projections.context_aware.qb_context import QBContext
from app.projections.context_aware.team_context import TeamTendencies


def _breakdown(total_points, qb_changed, role_confidence="high", conflict=False, conflict_reason=None):
    return CareerAwareBreakdown(
        total_points=total_points,
        categories=[
            CategoryShareBreakdown(
                name="receiving", expected_team_opportunities=34.2, expected_share=0.275,
                expected_opportunities=9.4, points=total_points or 0.0,
            )
        ],
        availability_status="healthy", team_changed=False, role_confidence=role_confidence,
        role_changed_recently=False, projection_conflict=conflict, conflict_reason=conflict_reason,
        career_talent_prior={
            "yards_per_target": EffectivePrior(career_value=9.5, career_evidence_weight=0.9,
                                                fallback_value=8.0, effective_value=9.35),
        },
        career_workload_prior={
            "target_share": EffectivePrior(career_value=0.28, career_evidence_weight=0.85,
                                            fallback_value=0.20, effective_value=0.268),
        },
        qb_context=QBContext(current_qb_gsis_id="qb-1", prior_qb_gsis_id="qb-2",
                              qb_changed=qb_changed, confidence="depth_chart"),
        current_team="MIN", prior_season_team="MIN",
        team_offense=TeamTendencies(pass_attempts_per_game=34.2, rush_attempts_per_game=24.0),
    )


def test_explain_includes_only_real_math_inputs():
    breakdown = _breakdown(total_points=17.1, qb_changed=True)
    text = explain_projection(breakdown)
    assert "34.2" in text  # expected team pass attempts -- real input to expected_opportunities
    assert "27.5" in text or "0.275" in text  # expected target share
    assert "9.4" in text  # expected targets
    assert "qb change" in text.lower()
    assert "17.1" in text  # the final number itself


def test_explain_omits_conflict_reason_when_no_conflict():
    breakdown = _breakdown(total_points=17.1, qb_changed=False, conflict=False)
    text = explain_projection(breakdown)
    assert "conflict" not in text.lower() or "no conflict" in text.lower()


def test_explain_handles_no_projection_case():
    breakdown = _breakdown(total_points=None, qb_changed=False)
    text = explain_projection(breakdown)
    assert "no projection" in text.lower() or "unavailable" in text.lower()
