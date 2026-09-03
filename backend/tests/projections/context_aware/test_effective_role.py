import pandas as pd

from app.projections.context_aware.effective_role import (
    TeammateStatus,
    compute_effective_pos_rank,
    load_same_position_groups,
)


def _rb_room(rb1_status="healthy", rb2_status="healthy", rb3_status="healthy"):
    return [
        TeammateStatus(gsis_id="rb1", pos_rank=1, availability_status=rb1_status),
        TeammateStatus(gsis_id="rb2", pos_rank=2, availability_status=rb2_status),
        TeammateStatus(gsis_id="rb3", pos_rank=3, availability_status=rb3_status),
    ]


def test_rb1_healthy_rb2_stays_effective_rank_2():
    room = _rb_room()
    assert compute_effective_pos_rank("rb2", 2, room) == 2


def test_rb1_out_rb2_promoted_to_effective_rank_1():
    room = _rb_room(rb1_status="unavailable")
    assert compute_effective_pos_rank("rb2", 2, room) == 1


def test_rb1_questionable_no_automatic_promotion():
    room = _rb_room(rb1_status="questionable")
    assert compute_effective_pos_rank("rb2", 2, room) == 2


def test_rb1_and_rb2_out_rb3_promoted_to_effective_rank_1():
    room = _rb_room(rb1_status="unavailable", rb2_status="unavailable")
    assert compute_effective_pos_rank("rb3", 3, room) == 1


def test_injury_clears_original_hierarchy_restored():
    out_room = _rb_room(rb1_status="unavailable")
    assert compute_effective_pos_rank("rb2", 2, out_room) == 1

    healthy_room = _rb_room()  # same room, RB1 healthy again
    assert compute_effective_pos_rank("rb2", 2, healthy_room) == 2


def test_no_teammate_data_preserves_original_rank():
    assert compute_effective_pos_rank("rb2", 2, teammates=[]) == 2


def test_no_original_rank_stays_none():
    assert compute_effective_pos_rank("rb2", None, _rb_room()) is None


def test_player_missing_from_its_own_teammate_group_preserves_original_rank():
    # rb2 isn't actually present in the supplied room (e.g. a stale/mismatched lookup) --
    # must not silently invent a rank for it.
    room = [TeammateStatus(gsis_id="rb1", pos_rank=1, availability_status="unavailable")]
    assert compute_effective_pos_rank("rb2", 2, room) == 2


def test_unknown_teammate_availability_treated_as_available_not_promoted():
    # rb1's status was never resolved (e.g. no Player row for a non-rostered starter) --
    # treated as available, so rb2 is NOT wrongly promoted off an absence of evidence.
    room = [
        TeammateStatus(gsis_id="rb1", pos_rank=1, availability_status="unknown"),
        TeammateStatus(gsis_id="rb2", pos_rank=2, availability_status="healthy"),
    ]
    assert compute_effective_pos_rank("rb2", 2, room) == 2


def test_dropped_from_depth_chart_entirely_teammate_still_counted_if_present():
    # A teammate with no resolvable pos_rank at all is excluded from the ranked pool, but
    # doesn't block ranking everyone else.
    room = [
        TeammateStatus(gsis_id="rb1", pos_rank=None, availability_status="healthy"),
        TeammateStatus(gsis_id="rb2", pos_rank=2, availability_status="healthy"),
    ]
    assert compute_effective_pos_rank("rb2", 2, room) == 1


def _snapshot_row(dt, team, gsis_id, pos_abb, pos_rank):
    return {"dt": dt, "team": team, "gsis_id": gsis_id, "pos_abb": pos_abb, "pos_rank": pos_rank}


def test_load_same_position_groups_groups_by_team_and_position():
    rows = [
        _snapshot_row("2025-09-01T00:00:00Z", "SF", "rb1", "RB", 1),
        _snapshot_row("2025-09-01T00:00:00Z", "SF", "rb2", "RB", 2),
        _snapshot_row("2025-09-01T00:00:00Z", "SF", "wr1", "WR", 1),
        _snapshot_row("2025-09-01T00:00:00Z", "KC", "rb9", "RB", 1),
    ]
    groups = load_same_position_groups(pd.DataFrame(rows), "2025-09-04")

    assert set(groups[("SF", "RB")]) == {"rb1", "rb2"}
    assert groups[("SF", "WR")] == ["wr1"]
    assert groups[("KC", "RB")] == ["rb9"]


def test_load_same_position_groups_empty_depth_charts_returns_empty():
    assert load_same_position_groups(pd.DataFrame(), "2025-09-04") == {}


def test_load_same_position_groups_respects_leak_safe_snapshot_cutoff():
    rows = [
        _snapshot_row("2025-09-01T00:00:00Z", "SF", "rb1", "RB", 1),  # before cutoff -- eligible
        _snapshot_row("2025-09-04T00:00:00Z", "SF", "rb2", "RB", 2),  # on/after cutoff -- must be ignored
    ]
    groups = load_same_position_groups(pd.DataFrame(rows), "2025-09-04")
    assert groups[("SF", "RB")] == ["rb1"]
