import pytest

from app.projections.head_to_head import compare_players
from app.projections.models import PlayerMetrics, PlayerProjection


def test_compare_players_states_projection_gap_favoring_the_higher_projection():
    a = PlayerProjection("a", "Player A", "WR", 18.0, ["espn"])
    b = PlayerProjection("b", "Player B", "WR", 16.7, ["espn"])
    result = compare_players(a, None, b, None)

    assert result["projection_gap"] == pytest.approx(1.3, abs=0.01)
    assert any("+1.3 projected points" in r for r in result["favors_this_player"])
    assert result["favors_opponent"] == []


def test_compare_players_flags_close_call_within_threshold():
    a = PlayerProjection("a", "A", "WR", 17.0, ["espn"])
    b = PlayerProjection("b", "B", "WR", 16.0, ["espn"])
    assert compare_players(a, None, b, None)["is_close_call"] is True

    c = PlayerProjection("c", "C", "WR", 20.0, ["espn"])
    assert compare_players(a, None, c, None)["is_close_call"] is False


def test_compare_players_compares_usage_metrics_both_directions():
    a = PlayerProjection("a", "A", "WR", 15.0, ["espn"])
    b = PlayerProjection("b", "B", "WR", 14.0, ["espn"])
    metrics_a = PlayerMetrics("a", recent_target_share=0.28, snap_share=0.86, red_zone_opportunities=4)
    metrics_b = PlayerMetrics("b", recent_target_share=0.19, snap_share=0.63, red_zone_opportunities=1)

    result = compare_players(a, metrics_a, b, metrics_b)

    assert any("28% recent target share vs 19%" in r for r in result["favors_this_player"])
    assert any("86% snap share vs 63%" in r for r in result["favors_this_player"])
    assert any("4 red zone opportunities vs 1" in r for r in result["favors_this_player"])
    assert result["favors_opponent"] == []


def test_compare_players_flags_availability_risk():
    a = PlayerProjection("a", "A", "WR", 15.0, ["espn"])
    b = PlayerProjection("b", "B", "WR", 14.0, ["espn"])
    metrics_a = PlayerMetrics("a", availability="questionable")
    metrics_b = PlayerMetrics("b", availability="healthy")

    result = compare_players(a, metrics_a, b, metrics_b)

    assert result["this_player_risks"] == ["Questionable"]
    assert result["opponent_risks"] == []


def test_compare_players_labels_safer_floor_and_higher_upside_separately():
    # A has the safer floor, B has the higher ceiling -- a genuine boom/bust tradeoff.
    a = PlayerProjection("a", "A", "WR", 15.0, ["espn"], floor=13.2, ceiling=18.0)
    b = PlayerProjection("b", "B", "WR", 14.2, ["espn"], floor=6.0, ceiling=25.8)

    result = compare_players(a, None, b, None)

    assert "Safer floor" in result["this_player_labels"]
    assert "Higher upside" in result["opponent_labels"]


def test_compare_players_labels_usage_trend_and_limited_history():
    a = PlayerProjection("a", "A", "WR", 15.0, ["espn"])
    b = PlayerProjection("b", "B", "WR", 14.0, ["espn"])
    metrics_a = PlayerMetrics("a", usage_trend="rising")
    metrics_b = PlayerMetrics("b", usage_trend="falling", experience_status="rookie_or_limited_history", games_played=1)

    result = compare_players(a, metrics_a, b, metrics_b)

    assert "Usage rising" in result["this_player_labels"]
    assert "Role declining" in result["opponent_labels"]
    assert "Limited history" in result["opponent_labels"]


def test_compare_players_labels_matchup_difficulty():
    a = PlayerProjection("a", "A", "WR", 15.0, ["espn"])
    b = PlayerProjection("b", "B", "WR", 14.0, ["espn"])
    metrics_a = PlayerMetrics("a", matchup_rating=80.0)
    metrics_b = PlayerMetrics("b", matchup_rating=10.0)

    result = compare_players(a, metrics_a, b, metrics_b)

    assert "Favorable matchup" in result["this_player_labels"]
    assert "Tough matchup" in result["opponent_labels"]
