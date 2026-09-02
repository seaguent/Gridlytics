import pandas as pd

from app.projections.context_aware.depth_chart import RoleInfo, load_current_roles_batch
from app.projections.context_aware.model import add_share_columns, compute_share_priors_by_rank, project_context_aware_points_detailed
from app.projections.context_aware.team_context import TeamTendencies, compute_team_tendencies
from app.projections.native.backtest import _player_games, _team_changed
from app.projections.native.categories import POSITION_CATEGORIES
from app.projections.native.historical_baseline import project_historical_recency
from app.projections.native.model import compute_all_position_priors, project_player_points

MODEL_15_7A = "native_15_7a"
MODEL_CONTEXT_AWARE = "context_aware_15_7c"
MODEL_NAIVE = "naive_position_average"
MODEL_HISTORICAL = "historical_recency"


def _week_as_of_date(schedule: pd.DataFrame, season: int, week: int) -> str | None:
    if schedule.empty:
        return None
    week_games = schedule[(schedule["season"] == season) & (schedule["week"] == week)]
    if week_games.empty:
        return None
    return str(week_games["gameday"].min())


def run_comparative_backtest(
    weekly_stats: pd.DataFrame,
    depth_charts: pd.DataFrame,
    schedule: pd.DataFrame,
    season: int,
    weeks: list[int],
) -> list[dict]:
    """Returns one row per (player, week, model) for every eligible player-week, for all four
    models -- including an explicit row with projected=None when a model abstains, rather than
    silently dropping it. This is what makes coverage/abstention reportable at all: a model that
    quietly skips difficult cases must not look identical to one with nothing to say about them."""
    weekly_with_shares = add_share_columns(weekly_stats)
    regular_season = weekly_with_shares[weekly_with_shares["season_type"] == "REG"]
    rows: list[dict] = []

    for week in weeks:
        as_of_date = _week_as_of_date(schedule, season, week)
        position_priors = compute_all_position_priors(weekly_with_shares, season=season, before_week=week)
        team_tendencies = compute_team_tendencies(weekly_with_shares, season=season, before_week=week)
        share_priors = (
            compute_share_priors_by_rank(weekly_with_shares, depth_charts, season=season, before_week=week, as_of_date=as_of_date)
            if as_of_date is not None else {}
        )
        # Computed once per week (as_of_date is the same for every player that week), not once
        # per player -- re-filtering the full multi-season depth_charts DataFrame per player is
        # the real bottleneck a real backtest run exposed (~60s/week vs. ~2s/week batched).
        roles_batch = load_current_roles_batch(depth_charts, as_of_date) if as_of_date is not None else {}

        actual_rows = regular_season[(regular_season["season"] == season) & (regular_season["week"] == week)]

        for actual_row in actual_rows.to_dict("records"):
            position = actual_row["position"]
            if position not in POSITION_CATEGORIES:
                continue

            player_id = actual_row["player_id"]
            actual_points = actual_row.get("fantasy_points_ppr")
            if actual_points is None or pd.isna(actual_points):
                continue

            current_games = _player_games(weekly_with_shares, player_id, season, before_week=week)
            prior_games = _player_games(weekly_with_shares, player_id, season - 1, before_week=None)
            experience_status = "veteran" if prior_games else "rookie_or_limited_history"
            team_changed = _team_changed(prior_games, actual_row)

            native_points = project_player_points(
                position, current_games, prior_games or None, position_priors[position], team_changed
            )
            naive_points = project_player_points(
                position, current_games, prior_games or None, position_priors[position], team_changed,
                use_player_efficiency=False,
            )
            historical_points = project_historical_recency(
                [g["fantasy_points_ppr"] for g in current_games if g.get("fantasy_points_ppr") is not None]
            )

            role_confidence = "unknown"
            role_changed_recently = False
            context_points = None
            if as_of_date is not None:
                role = roles_batch.get((player_id, position))
                if role is None:
                    # Distinguish "no snapshot existed at all before this cutoff" (unknown,
                    # matches load_current_role's empty-snapshot case) from "a snapshot existed
                    # but this specific player wasn't in it" (low, matches its not-found case).
                    fallback_confidence = "low" if roles_batch else "unknown"
                    role = RoleInfo(pos_rank=None, role_confidence=fallback_confidence, role_changed_recently=False)
                role_confidence = role.role_confidence
                role_changed_recently = role.role_changed_recently
                tendencies = team_tendencies.get(actual_row.get("team"), TeamTendencies(None, None))
                breakdown = project_context_aware_points_detailed(
                    position, current_games, prior_games or None, tendencies, role,
                    share_priors, position_priors[position],
                    team_changed, platform_points=None, availability_status="healthy",
                )
                context_points = breakdown.total_points if breakdown is not None else None

            for model, projected in (
                (MODEL_15_7A, native_points),
                (MODEL_CONTEXT_AWARE, context_points),
                (MODEL_NAIVE, naive_points),
                (MODEL_HISTORICAL, historical_points),
            ):
                rows.append(
                    {
                        "week": week,
                        "player_id": player_id,
                        "position": position,
                        "experience_status": experience_status,
                        "team_changed": team_changed,
                        "role_changed_recently": role_changed_recently,
                        "role_confidence": role_confidence,
                        "model": model,
                        "projected": projected,
                        "actual": actual_points,
                    }
                )

    return rows


def summarize_accuracy(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["model", "position", "experience_status", "mae", "rmse", "sample_size"])

    df = pd.DataFrame(rows)
    scored = df[df["projected"].notna()].copy()
    if scored.empty:
        return pd.DataFrame(columns=["model", "position", "experience_status", "mae", "rmse", "sample_size"])

    scored["abs_error"] = (scored["projected"] - scored["actual"]).abs()
    scored["sq_error"] = (scored["projected"] - scored["actual"]) ** 2
    grouped = scored.groupby(["model", "position", "experience_status"]).agg(
        mae=("abs_error", "mean"),
        rmse=("sq_error", lambda v: v.mean() ** 0.5),
        sample_size=("abs_error", "count"),
    )
    return grouped.reset_index()


def summarize_segment(rows: list[dict], segment_column: str) -> pd.DataFrame:
    """Generic segment breakdown (e.g. team_changed, role_changed_recently), MAE/RMSE/sample_size
    per (model, segment value), scored rows only."""
    if not rows:
        return pd.DataFrame(columns=["model", segment_column, "mae", "rmse", "sample_size"])

    df = pd.DataFrame(rows)
    scored = df[df["projected"].notna()].copy()
    if scored.empty:
        return pd.DataFrame(columns=["model", segment_column, "mae", "rmse", "sample_size"])

    scored["abs_error"] = (scored["projected"] - scored["actual"]).abs()
    scored["sq_error"] = (scored["projected"] - scored["actual"]) ** 2
    grouped = scored.groupby(["model", segment_column]).agg(
        mae=("abs_error", "mean"),
        rmse=("sq_error", lambda v: v.mean() ** 0.5),
        sample_size=("abs_error", "count"),
    )
    return grouped.reset_index()


def summarize_coverage(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["model", "eligible", "covered", "coverage"])

    df = pd.DataFrame(rows)
    grouped = df.groupby("model").agg(
        eligible=("projected", "size"),
        covered=("projected", lambda v: v.notna().sum()),
    )
    grouped["coverage"] = grouped["covered"] / grouped["eligible"]
    return grouped.reset_index()


def summarize_abstention_reasons(rows: list[dict], model: str) -> pd.DataFrame:
    """For a given model's abstained rows only, breaks down by role_confidence -- the closest
    real, honest signal available for *why* the context-aware model had nothing to say."""
    df = pd.DataFrame(rows)
    abstained = df[(df["model"] == model) & df["projected"].isna()]
    if abstained.empty:
        return pd.DataFrame(columns=["role_confidence", "count"])
    return abstained.groupby("role_confidence").size().reset_index(name="count")


def common_sample_comparison(rows: list[dict], model_a: str, model_b: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    pivot = df.pivot_table(index=["player_id", "week"], columns="model", values="projected", aggfunc="first")
    if model_a not in pivot.columns or model_b not in pivot.columns:
        return pd.DataFrame(columns=["model", "mae", "sample_size"])

    common_keys = pivot[pivot[model_a].notna() & pivot[model_b].notna()].index
    df_indexed = df.set_index(["player_id", "week"])
    common_rows = df_indexed[df_indexed.index.isin(common_keys) & df_indexed["model"].isin([model_a, model_b])].copy()
    if common_rows.empty:
        return pd.DataFrame(columns=["model", "mae", "sample_size"])

    common_rows["abs_error"] = (common_rows["projected"] - common_rows["actual"]).abs()
    grouped = common_rows.groupby("model")["abs_error"].agg(mae="mean", sample_size="count")
    return grouped.reset_index()


def pairwise_ranking_accuracy(rows: list[dict], model: str) -> dict:
    """For every same-position, same-week pair of real players where `model` produced a real
    (non-abstained) projection for both, does its relative ordering match the real outcome?
    Pairs with a tied real outcome carry no ranking signal and are excluded."""
    df = pd.DataFrame(rows)
    model_rows = df[(df["model"] == model) & df["projected"].notna()]

    correct = 0
    total = 0
    for _, group in model_rows.groupby(["week", "position"]):
        players = group[["projected", "actual"]].values.tolist()
        for i in range(len(players)):
            for j in range(i + 1, len(players)):
                proj_i, act_i = players[i]
                proj_j, act_j = players[j]
                if act_i == act_j:
                    continue
                total += 1
                if (proj_i > proj_j) == (act_i > act_j):
                    correct += 1

    return {
        "model": model,
        "correct": correct,
        "total": total,
        "accuracy": correct / total if total else None,
    }


def summarize_elite_segment(rows: list[dict], model: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = df[df["model"] == model]
    if df.empty:
        return pd.DataFrame(columns=["model", "mae", "n"])
    df["rank_pct"] = df.groupby(["week", "position"])["actual"].rank(pct=True, ascending=True)
    elite = df[df["rank_pct"] >= 0.75]
    if elite.empty:
        return pd.DataFrame(columns=["model", "mae", "n"])
    elite = elite.assign(abs_error=(elite["projected"] - elite["actual"]).abs())
    return pd.DataFrame([{"model": model, "mae": elite["abs_error"].mean(), "n": len(elite)}])
