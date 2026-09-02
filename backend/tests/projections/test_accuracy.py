import pytest

from app.projections.accuracy import compute_projection_accuracy


def _row(source, player_id, week, projected, actual):
    return {"source": source, "platform_player_id": player_id, "week": week, "projected_points": projected, "actual_points": actual}


def test_empty_input_returns_empty_report():
    report = compute_projection_accuracy([])
    assert report.all_available == []
    assert report.common_sample == []


def test_single_source_mae_and_sample_size():
    records = [_row("espn", "p1", 1, 10.0, 12.0), _row("espn", "p1", 2, 8.0, 6.0)]
    report = compute_projection_accuracy(records)
    assert len(report.all_available) == 1
    assert report.all_available[0].source == "espn"
    assert report.all_available[0].mae == pytest.approx(2.0)
    assert report.all_available[0].sample_size == 2


def test_all_available_reports_each_sources_own_full_sample_independently():
    records = [
        _row("espn", "p1", 1, 10.0, 12.0),
        _row("espn", "p1", 2, 8.0, 6.0),
        _row("espn", "p2", 3, 20.0, 20.0),
        _row("gridlytics", "p1", 1, 11.0, 12.0),
    ]
    report = compute_projection_accuracy(records)
    by_source = {s.source: s for s in report.all_available}
    assert by_source["espn"].sample_size == 3
    assert by_source["gridlytics"].sample_size == 1


def test_common_sample_restricted_to_shared_player_weeks_only():
    records = [
        _row("espn", "p1", 1, 10.0, 12.0),  # shared with gridlytics
        _row("espn", "p2", 2, 20.0, 18.0),  # espn-only, no gridlytics row for (p2, 2)
        _row("gridlytics", "p1", 1, 11.0, 12.0),  # shared with espn
    ]
    report = compute_projection_accuracy(records)
    by_source = {s.source: s for s in report.common_sample}
    assert by_source["espn"].sample_size == 1
    assert by_source["gridlytics"].sample_size == 1
    assert by_source["espn"].mae == pytest.approx(2.0)
    assert by_source["gridlytics"].mae == pytest.approx(1.0)


def test_common_sample_empty_when_sources_never_overlap():
    records = [_row("espn", "p1", 1, 10.0, 12.0), _row("gridlytics", "p2", 2, 8.0, 6.0)]
    report = compute_projection_accuracy(records)
    assert report.common_sample == []
    # all_available still reports each source's own real numbers -- not hidden just because
    # they don't overlap.
    assert len(report.all_available) == 2
