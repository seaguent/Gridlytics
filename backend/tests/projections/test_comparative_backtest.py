import pandas as pd
import pytest

from app.projections.comparative_backtest import (
    MODEL_15_7A,
    MODEL_CONTEXT_AWARE,
    MODEL_HISTORICAL,
    MODEL_NAIVE,
    common_sample_comparison,
    pairwise_ranking_accuracy,
    run_comparative_backtest,
    summarize_accuracy,
    summarize_coverage,
)


def _wr_row(player_id, season, week, targets, receiving_yards, receiving_tds, receptions, fantasy_points_ppr, team="SF"):
    return {
        "player_id": player_id, "position": "WR", "season": season, "week": week, "season_type": "REG",
        "team": team, "targets": targets, "receiving_yards": receiving_yards, "receiving_tds": receiving_tds,
        "receptions": receptions, "carries": 0, "rushing_yards": 0, "rushing_tds": 0,
        "attempts": 0, "passing_yards": 0, "passing_tds": 0, "passing_interceptions": 0,
        "target_share": receptions / max(targets, 1) * 0.0 + 0.3, "fantasy_points_ppr": fantasy_points_ppr,
    }


def _depth_chart_row(dt, team, gsis_id, pos_abb, pos_rank):
    return {"dt": dt, "team": team, "gsis_id": gsis_id, "pos_abb": pos_abb, "pos_rank": pos_rank}


def _schedule_row(season, week, gameday, home_team="SF", away_team="LA"):
    return {"season": season, "week": week, "gameday": gameday, "home_team": home_team, "away_team": away_team}


def _synthetic_dataset() -> pd.DataFrame:
    rows = []
    for week in range(1, 9):
        rows.append(_wr_row("wr-1", 2024, week, 10, 100, 1, 7, 17.0))
    for week in range(1, 4):
        rows.append(_wr_row("wr-1", 2025, week, 10, 100, 1, 7, 17.0))
    return pd.DataFrame(rows)


def _synthetic_depth_charts() -> pd.DataFrame:
    return pd.DataFrame([_depth_chart_row("2025-08-01T00:00:00Z", "SF", "wr-1", "WR", 1)])


def _synthetic_schedule() -> pd.DataFrame:
    return pd.DataFrame([_schedule_row(2025, w, f"2025-09-{w:02d}") for w in range(1, 5)])


def test_run_comparative_backtest_records_all_four_models_including_abstentions():
    df = _synthetic_dataset()
    depth_charts = _synthetic_depth_charts()
    schedule = _synthetic_schedule()

    rows = run_comparative_backtest(df, depth_charts, schedule, season=2025, weeks=[1])

    models_present = {r["model"] for r in rows}
    assert models_present == {MODEL_15_7A, MODEL_CONTEXT_AWARE, MODEL_NAIVE, MODEL_HISTORICAL}
    # Every model gets a row for this eligible player-week, even ones that abstain (projected=None).
    week1_rows = {r["model"]: r for r in rows if r["week"] == 1 and r["player_id"] == "wr-1"}
    assert len(week1_rows) == 4
    assert week1_rows[MODEL_HISTORICAL]["projected"] is None  # <2 current-season weeks -- abstains


def test_summarize_accuracy_excludes_abstained_rows_never_scores_them_as_zero():
    rows = [
        {"model": "m1", "position": "WR", "experience_status": "veteran", "projected": 10.0, "actual": 12.0},
        {"model": "m1", "position": "WR", "experience_status": "veteran", "projected": None, "actual": 20.0},
    ]
    result = summarize_accuracy(rows)
    row = result[result["model"] == "m1"].iloc[0]
    assert row["sample_size"] == 1  # the abstained row must not count, and must not be scored as |0-20|
    assert row["mae"] == pytest.approx(2.0)


def test_summarize_coverage_reports_fraction_of_eligible_weeks_covered():
    rows = [
        {"model": "m1", "projected": 10.0},
        {"model": "m1", "projected": None},
        {"model": "m1", "projected": 8.0},
        {"model": "m1", "projected": 9.0},
    ]
    result = summarize_coverage(rows)
    row = result[result["model"] == "m1"].iloc[0]
    assert row["eligible"] == 4
    assert row["covered"] == 3
    assert row["coverage"] == pytest.approx(0.75)


def test_common_sample_comparison_restricted_to_shared_covered_player_weeks():
    rows = [
        {"model": "a", "player_id": "p1", "week": 1, "projected": 10.0, "actual": 12.0},
        {"model": "b", "player_id": "p1", "week": 1, "projected": 11.0, "actual": 12.0},
        {"model": "a", "player_id": "p2", "week": 2, "projected": 8.0, "actual": 6.0},
        {"model": "b", "player_id": "p2", "week": 2, "projected": None, "actual": 6.0},  # b abstained here
    ]
    result = common_sample_comparison(rows, "a", "b")
    by_model = {r["model"]: r for r in result.to_dict("records")}
    assert by_model["a"]["sample_size"] == 1  # only p1/week1 is common -- p2/week2 excluded (b abstained)
    assert by_model["b"]["sample_size"] == 1
    assert by_model["a"]["mae"] == pytest.approx(2.0)
    assert by_model["b"]["mae"] == pytest.approx(1.0)


def test_pairwise_ranking_accuracy_scores_correctly_ordered_same_position_pairs():
    rows = [
        {"model": "m1", "week": 1, "position": "WR", "projected": 15.0, "actual": 20.0},  # correctly higher
        {"model": "m1", "week": 1, "position": "WR", "projected": 10.0, "actual": 5.0},
        {"model": "m1", "week": 1, "position": "WR", "projected": 8.0, "actual": 25.0},  # projected LOWEST, actually HIGHEST
    ]
    result = pairwise_ranking_accuracy(rows, "m1")
    assert result["total"] == 3  # 3 pairs among 3 players
    assert result["correct"] == 1  # only the (15/20) vs (10/5) pair is correctly ordered
    assert result["accuracy"] == pytest.approx(1 / 3)


def test_leakage_future_weeks_never_affect_an_earlier_weeks_prediction():
    df = _synthetic_dataset()
    depth_charts = _synthetic_depth_charts()
    schedule = _synthetic_schedule()
    baseline_rows = run_comparative_backtest(df, depth_charts, schedule, season=2025, weeks=[1])

    df_mutated = df.copy()
    df_mutated.loc[(df_mutated["season"] == 2025) & (df_mutated["week"] == 3), "receiving_yards"] = 99999
    depth_charts_mutated = pd.concat(
        [depth_charts, pd.DataFrame([_depth_chart_row("2025-09-10T00:00:00Z", "SF", "wr-1", "WR", 3)])],
        ignore_index=True,
    )
    mutated_rows = run_comparative_backtest(df_mutated, depth_charts_mutated, schedule, season=2025, weeks=[1])

    def _by_model(rows):
        return {r["model"]: r["projected"] for r in rows if r["week"] == 1 and r["player_id"] == "wr-1"}

    assert _by_model(baseline_rows) == _by_model(mutated_rows)


def test_pairwise_ranking_accuracy_ignores_tied_actual_outcomes():
    rows = [
        {"model": "m1", "week": 1, "position": "WR", "projected": 15.0, "actual": 10.0},
        {"model": "m1", "week": 1, "position": "WR", "projected": 10.0, "actual": 10.0},  # tie -- no signal
    ]
    result = pairwise_ranking_accuracy(rows, "m1")
    assert result["total"] == 0
    assert result["accuracy"] is None


def test_summarize_elite_segment_filters_to_top_quartile_actual_per_week_position():
    from app.projections.comparative_backtest import summarize_elite_segment
    rows = [
        {"week": 1, "position": "WR", "model": "native", "projected": 10.0, "actual": 25.0},
        {"week": 1, "position": "WR", "model": "native", "projected": 8.0, "actual": 5.0},
        {"week": 1, "position": "WR", "model": "native", "projected": 12.0, "actual": 20.0},
        {"week": 1, "position": "WR", "model": "native", "projected": 6.0, "actual": 4.0},
    ]
    result = summarize_elite_segment(rows, "native")
    assert result["n"].iloc[0] <= 2  # top quartile of 4 rows
