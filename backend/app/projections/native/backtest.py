import pandas as pd

from app.projections.native.categories import POSITION_CATEGORIES
from app.projections.native.historical_baseline import project_historical_recency
from app.projections.native.model import compute_all_position_priors, project_player_points

MODEL_NATIVE = "native"
MODEL_NAIVE = "naive_position_average"
MODEL_HISTORICAL = "historical_recency"


def _index_games_by_player_season(df: pd.DataFrame) -> dict[tuple, list[dict]]:
    """Pure performance change: materializes each (player_id, season) game list once instead of re-filtering per lookup."""
    regular_season = df[df["season_type"] == "REG"].sort_values("week")
    grouped: dict[tuple, list[dict]] = {}
    # One large to_dict("records") call, then group in plain Python -- pandas' to_dict("records")
    # has enough fixed per-call overhead that calling it once per (player, season) group (thousands
    # of small calls) is slower in aggregate than one call over the whole frame. Global sort by
    # week above means each player's appended list ends up week-ascending without a per-group sort.
    for row in regular_season.to_dict("records"):
        grouped.setdefault((row["player_id"], row["season"]), []).append(row)
    return grouped


def _player_games(
    indexed_games: dict[tuple, list[dict]], player_id: str, season: int, before_week: int | None
) -> list[dict]:
    games = indexed_games.get((player_id, season), [])
    if before_week is None:
        return games
    return [g for g in games if g["week"] < before_week]


def _team_changed(prior_games: list[dict], actual_row: dict) -> bool:
    if not prior_games:
        return False
    return prior_games[-1].get("team") != actual_row.get("team")


def run_backtest(
    weekly_stats: pd.DataFrame,
    season: int,
    weeks: list[int],
    td_shrinkage_opportunities: dict[str, float] | None = None,
) -> list[dict]:
    regular_season = weekly_stats[weekly_stats["season_type"] == "REG"]
    indexed_games = _index_games_by_player_season(weekly_stats)
    rows: list[dict] = []

    for week in weeks:
        position_priors = compute_all_position_priors(weekly_stats, season=season, before_week=week)
        actual_rows = regular_season[(regular_season["season"] == season) & (regular_season["week"] == week)]

        for actual_row in actual_rows.to_dict("records"):
            position = actual_row["position"]
            if position not in POSITION_CATEGORIES:
                continue

            player_id = actual_row["player_id"]
            actual_points = actual_row.get("fantasy_points_ppr")
            if actual_points is None or pd.isna(actual_points):
                continue

            current_games = _player_games(indexed_games, player_id, season, before_week=week)
            prior_games = _player_games(indexed_games, player_id, season - 1, before_week=None)
            experience_status = "veteran" if prior_games else "rookie_or_limited_history"
            team_changed = _team_changed(prior_games, actual_row)

            native_points = project_player_points(
                position, current_games, prior_games or None, position_priors[position], team_changed,
                td_shrinkage_opportunities=td_shrinkage_opportunities,
            )
            naive_points = project_player_points(
                position, current_games, prior_games or None, position_priors[position], team_changed,
                use_player_efficiency=False,
            )
            historical_points = project_historical_recency(
                [g["fantasy_points_ppr"] for g in current_games if g.get("fantasy_points_ppr") is not None]
            )

            for model, projected in (
                (MODEL_NATIVE, native_points),
                (MODEL_NAIVE, naive_points),
                (MODEL_HISTORICAL, historical_points),
            ):
                if projected is None:
                    continue
                rows.append(
                    {
                        "week": week,
                        "player_id": player_id,
                        "position": position,
                        "experience_status": experience_status,
                        "model": model,
                        "projected": projected,
                        "actual": actual_points,
                    }
                )

    return rows


def summarize_backtest(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["model", "position", "experience_status", "mae", "rmse", "sample_size"])

    df = pd.DataFrame(rows)
    df["abs_error"] = (df["projected"] - df["actual"]).abs()
    df["sq_error"] = (df["projected"] - df["actual"]) ** 2

    grouped = df.groupby(["model", "position", "experience_status"]).agg(
        mae=("abs_error", "mean"),
        rmse=("sq_error", lambda values: values.mean() ** 0.5),
        sample_size=("abs_error", "count"),
    )
    return grouped.reset_index()
