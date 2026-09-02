import pandas as pd
import pytest

from app.projections.context_aware.depth_chart import load_current_role, load_current_roles_batch


def _snapshot_row(dt, team, gsis_id, pos_abb, pos_rank):
    return {"dt": dt, "team": team, "gsis_id": gsis_id, "pos_abb": pos_abb, "pos_rank": pos_rank}


def test_no_depth_chart_data_returns_unknown():
    result = load_current_role(pd.DataFrame(), "00-1", "RB", "2025-09-04")
    assert result.pos_rank is None
    assert result.role_confidence == "unknown"
    assert result.role_changed_recently is False


def test_player_not_in_latest_snapshot_returns_low_confidence():
    rows = [_snapshot_row("2025-09-01T00:00:00Z", "SF", "00-2", "RB", 1)]
    result = load_current_role(pd.DataFrame(rows), "00-1", "RB", "2025-09-04")
    assert result.pos_rank is None
    assert result.role_confidence == "low"


def test_player_found_returns_high_confidence_and_real_rank():
    rows = [_snapshot_row("2025-09-01T00:00:00Z", "SF", "00-1", "RB", 2)]
    result = load_current_role(pd.DataFrame(rows), "00-1", "RB", "2025-09-04")
    assert result.pos_rank == 2
    assert result.role_confidence == "high"


def test_leakage_snapshot_at_or_after_cutoff_never_used():
    rows = [
        _snapshot_row("2025-09-01T00:00:00Z", "SF", "00-1", "RB", 3),  # before cutoff -- eligible
        _snapshot_row("2025-09-04T00:00:00Z", "SF", "00-1", "RB", 1),  # on/after cutoff -- must be ignored
    ]
    result = load_current_role(pd.DataFrame(rows), "00-1", "RB", "2025-09-04")
    assert result.pos_rank == 3


def test_role_change_detected_between_snapshots_roughly_three_weeks_apart():
    rows = [
        _snapshot_row("2025-08-10T00:00:00Z", "SF", "00-1", "RB", 2),  # ~25 days before cutoff
        _snapshot_row("2025-09-01T00:00:00Z", "SF", "00-1", "RB", 1),  # promoted
    ]
    result = load_current_role(pd.DataFrame(rows), "00-1", "RB", "2025-09-04")
    assert result.pos_rank == 1
    assert result.role_changed_recently is True


def test_no_role_change_when_rank_is_stable():
    rows = [
        _snapshot_row("2025-08-10T00:00:00Z", "SF", "00-1", "RB", 1),
        _snapshot_row("2025-09-01T00:00:00Z", "SF", "00-1", "RB", 1),
    ]
    result = load_current_role(pd.DataFrame(rows), "00-1", "RB", "2025-09-04")
    assert result.role_changed_recently is False


def test_batch_matches_single_player_lookup_for_multiple_real_players():
    rows = [
        _snapshot_row("2025-08-10T00:00:00Z", "SF", "00-1", "RB", 2),
        _snapshot_row("2025-09-01T00:00:00Z", "SF", "00-1", "RB", 1),  # promoted
        _snapshot_row("2025-09-01T00:00:00Z", "SF", "00-2", "RB", 2),
        _snapshot_row("2025-09-01T00:00:00Z", "SF", "00-3", "WR", 1),
    ]
    df = pd.DataFrame(rows)
    batch = load_current_roles_batch(df, "2025-09-04")

    for gsis_id, position in [("00-1", "RB"), ("00-2", "RB"), ("00-3", "WR")]:
        single = load_current_role(df, gsis_id, position, "2025-09-04")
        batched = batch[(gsis_id, position)]
        assert batched.pos_rank == single.pos_rank
        assert batched.role_confidence == single.role_confidence
        assert batched.role_changed_recently == single.role_changed_recently

    assert ("nonexistent", "RB") not in batch


def test_batch_returns_empty_dict_when_no_snapshot_exists_before_cutoff():
    rows = [_snapshot_row("2025-09-10T00:00:00Z", "SF", "00-1", "RB", 1)]  # only after the cutoff
    result = load_current_roles_batch(pd.DataFrame(rows), "2025-09-04")
    assert result == {}
