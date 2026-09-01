import pandas as pd
import pytest

from app.projections.native.backtest import run_backtest, summarize_backtest


def _wr_row(player_id, season, week, targets, receiving_yards, receiving_tds, receptions, fantasy_points_ppr, team="SF"):
    return {
        "player_id": player_id, "position": "WR", "season": season, "week": week, "season_type": "REG",
        "team": team, "targets": targets, "receiving_yards": receiving_yards, "receiving_tds": receiving_tds,
        "receptions": receptions, "carries": 0, "rushing_yards": 0, "rushing_tds": 0,
        "attempts": 0, "passing_yards": 0, "passing_tds": 0, "passing_interceptions": 0,
        "fantasy_points_ppr": fantasy_points_ppr,
    }


def _synthetic_dataset() -> pd.DataFrame:
    rows = []
    # A consistent veteran WR across 2024 and several 2025 weeks.
    for week in range(1, 9):
        rows.append(_wr_row("wr-1", 2024, week, 10, 100, 1, 7, 17.0))
    for week in range(1, 4):
        rows.append(_wr_row("wr-1", 2025, week, 10, 100, 1, 7, 17.0))
    return pd.DataFrame(rows)


def test_run_backtest_produces_rows_for_every_model_and_eligible_player_week():
    df = _synthetic_dataset()
    rows = run_backtest(df, season=2025, weeks=[1, 2, 3])

    models = {row["model"] for row in rows}
    assert models == {"native", "naive_position_average", "historical_recency"}

    week1_native = [r for r in rows if r["week"] == 1 and r["model"] == "native" and r["player_id"] == "wr-1"]
    assert len(week1_native) == 1
    assert week1_native[0]["actual"] == pytest.approx(17.0)

    # historical_recency needs >= 2 real current-season weeks -- must be absent for week 1.
    week1_historical = [r for r in rows if r["week"] == 1 and r["model"] == "historical_recency" and r["player_id"] == "wr-1"]
    assert week1_historical == []
    week3_historical = [r for r in rows if r["week"] == 3 and r["model"] == "historical_recency" and r["player_id"] == "wr-1"]
    assert len(week3_historical) == 1


def test_leakage_future_weeks_never_affect_an_earlier_weeks_prediction():
    df = _synthetic_dataset()
    baseline_rows = run_backtest(df, season=2025, weeks=[1])

    df_mutated = df.copy()
    df_mutated.loc[(df_mutated["season"] == 2025) & (df_mutated["week"] == 3), "receiving_yards"] = 99999
    mutated_rows = run_backtest(df_mutated, season=2025, weeks=[1])

    def _projected_by_model(rows):
        return {row["model"]: row["projected"] for row in rows if row["week"] == 1 and row["player_id"] == "wr-1"}

    assert _projected_by_model(baseline_rows) == _projected_by_model(mutated_rows)


def test_summarize_backtest_reports_mae_rmse_and_sample_size_per_group():
    rows = [
        {"week": 1, "player_id": "a", "position": "WR", "experience_status": "veteran", "model": "native", "projected": 10.0, "actual": 12.0},
        {"week": 2, "player_id": "a", "position": "WR", "experience_status": "veteran", "model": "native", "projected": 8.0, "actual": 6.0},
    ]
    summary = summarize_backtest(rows)
    row = summary[
        (summary["model"] == "native") & (summary["position"] == "WR") & (summary["experience_status"] == "veteran")
    ].iloc[0]
    assert row["mae"] == pytest.approx(2.0)
    assert row["rmse"] == pytest.approx(2.0)
    assert row["sample_size"] == 2
