import pandas as pd
import pytest

from app.projections.context_aware.qb_context import QBContext, compute_qb_context, infer_starting_qb

DEPTH_CHARTS = pd.DataFrame([
    {"dt": "2026-08-01T00:00:00", "team": "MIN", "gsis_id": "qb-starter", "pos_abb": "QB", "pos_rank": 1},
    {"dt": "2026-08-01T00:00:00", "team": "MIN", "gsis_id": "qb-backup", "pos_abb": "QB", "pos_rank": 2},
])

WEEKLY_STATS = pd.DataFrame([
    {"player_id": "qb-a", "team": "MIN", "season": 2026, "season_type": "REG", "week": 1, "attempts": 30},
    {"player_id": "qb-b", "team": "MIN", "season": 2026, "season_type": "REG", "week": 2, "attempts": 5},
])

PRIOR_WEEKLY_STATS = pd.DataFrame([
    {"player_id": "prior-qb", "team": "MIN", "season": 2025, "season_type": "REG", "week": 1, "attempts": 35},
    {"player_id": "prior-qb", "team": "MIN", "season": 2025, "season_type": "REG", "week": 2, "attempts": 32},
])


def test_tier1_depth_chart_qb1_used_when_available():
    gsis_id, confidence = infer_starting_qb(
        "MIN", WEEKLY_STATS, PRIOR_WEEKLY_STATS, DEPTH_CHARTS,
        as_of_date="2026-09-01", season=2026, before_week=1,
    )
    assert gsis_id == "qb-starter"
    assert confidence == "depth_chart"


def test_tier2_current_pass_attempt_leader_when_no_depth_chart_data():
    empty_depth_charts = pd.DataFrame(columns=DEPTH_CHARTS.columns)
    gsis_id, confidence = infer_starting_qb(
        "MIN", WEEKLY_STATS, PRIOR_WEEKLY_STATS, empty_depth_charts,
        as_of_date="2026-09-15", season=2026, before_week=3,
    )
    assert gsis_id == "qb-a"  # 30 attempts > qb-b's 5
    assert confidence == "pass_attempts"


def test_tier3_prior_starter_when_current_season_has_no_data_yet():
    empty_depth_charts = pd.DataFrame(columns=DEPTH_CHARTS.columns)
    empty_weekly = pd.DataFrame(columns=WEEKLY_STATS.columns)
    gsis_id, confidence = infer_starting_qb(
        "MIN", empty_weekly, PRIOR_WEEKLY_STATS, empty_depth_charts,
        as_of_date="2026-08-01", season=2026, before_week=1,
    )
    assert gsis_id == "prior-qb"
    assert confidence == "prior_starter"


def test_tier4_unknown_never_guesses():
    empty_depth_charts = pd.DataFrame(columns=DEPTH_CHARTS.columns)
    empty_weekly = pd.DataFrame(columns=WEEKLY_STATS.columns)
    gsis_id, confidence = infer_starting_qb(
        "MIN", empty_weekly, empty_weekly, empty_depth_charts,
        as_of_date="2026-08-01", season=2026, before_week=1,
    )
    assert gsis_id is None
    assert confidence == "unknown"


def test_leakage_current_season_lookup_never_uses_weeks_at_or_after_before_week():
    mutated = WEEKLY_STATS.copy()
    mutated.loc[mutated["player_id"] == "qb-b", "attempts"] = 9999  # week 2, at/after before_week=2
    empty_depth_charts = pd.DataFrame(columns=DEPTH_CHARTS.columns)
    gsis_id, _ = infer_starting_qb(
        "MIN", mutated, PRIOR_WEEKLY_STATS, empty_depth_charts,
        as_of_date="2026-09-08", season=2026, before_week=2,
    )
    assert gsis_id == "qb-a"  # week 1 only -- qb-b's inflated week-2 value must never be counted


def test_compute_qb_context_detects_real_change():
    result = compute_qb_context(
        current_team="MIN", prior_season_team="MIN",
        weekly_stats=WEEKLY_STATS, prior_weekly_stats=PRIOR_WEEKLY_STATS, depth_charts=DEPTH_CHARTS,
        as_of_date="2026-09-01", season=2026, before_week=1,
    )
    assert result.current_qb_gsis_id == "qb-starter"  # depth chart tier wins
    assert result.prior_qb_gsis_id == "prior-qb"
    assert result.qb_changed is True
    assert result.confidence == "depth_chart"


def test_compute_qb_context_never_flags_change_when_either_side_unknown():
    empty_depth_charts = pd.DataFrame(columns=DEPTH_CHARTS.columns)
    empty_weekly = pd.DataFrame(columns=WEEKLY_STATS.columns)
    result = compute_qb_context(
        current_team="MIN", prior_season_team=None,
        weekly_stats=empty_weekly, prior_weekly_stats=empty_weekly, depth_charts=empty_depth_charts,
        as_of_date="2026-08-01", season=2026, before_week=1,
    )
    assert result.current_qb_gsis_id is None
    assert result.prior_qb_gsis_id is None
    assert result.qb_changed is False  # never a false positive when we genuinely don't know
