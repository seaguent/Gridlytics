import asyncio

import pandas as pd

from app.nflverse.client import NflverseClient
from app.projections.comparative_backtest import (
    common_sample_comparison,
    pairwise_ranking_accuracy,
    summarize_accuracy,
    summarize_coverage,
    summarize_elite_segment,
    summarize_segment,
)
from app.projections.context_aware.career_prior import compute_career_prior
from app.projections.context_aware.career_prior_sync import fetch_season_stats_range
from app.projections.context_aware.depth_chart import RoleInfo, load_current_roles_batch
from app.projections.context_aware.model import (
    add_share_columns,
    compute_share_priors_by_rank,
    project_context_aware_points_detailed,
    project_context_aware_points_detailed_v2,
)
from app.projections.context_aware.qb_context import compute_qb_context
from app.projections.context_aware.team_context import TeamTendencies, compute_team_tendencies, compute_team_tendencies_v2
from app.projections.context_aware.team_prior import TeamPrior, team_weight
from app.projections.native.backtest import _index_games_by_player_season, _player_games, _team_changed
from app.projections.native.categories import POSITION_CATEGORIES
from app.projections.context_aware.team_prior import LOOKBACK_SEASONS as TEAM_PRIOR_LOOKBACK, RECENCY_DECAY as TEAM_PRIOR_DECAY
from app.projections.native.model import compute_all_position_priors, project_player_points
from scripts.run_career_prior_validation import build_career_seasons
from scripts.run_team_prior_validation import _build_seasons_for_prediction, _real_team_seasons, _weighted_average_with_fn

MODEL_15_7A = "native_15_7a"
MODEL_CONTEXT_AWARE_OLD = "context_aware_15_7c"
MODEL_A_ONLY = "career_prior_a_only"
MODEL_A_PLUS_B = "context_aware_15_7c_b"


def _week_as_of_date(schedule: pd.DataFrame, season: int, week: int) -> str | None:
    week_games = schedule[(schedule["season"] == season) & (schedule["week"] == week)]
    if week_games.empty:
        return None
    return str(week_games["gameday"].min())


def run_four_arm_backtest(
    weekly_stats: pd.DataFrame,
    season_stats_by_year: dict[int, pd.DataFrame],
    depth_charts: pd.DataFrame,
    schedule: pd.DataFrame,
    season: int,
    weeks: list[int],
    multi_year_team_prior_by_team: dict[str, TeamPrior],
) -> list[dict]:
    """One row per (player, week, model) for all four arms, matching comparative_backtest.py's
    existing row shape exactly (model/projected/actual/position/experience_status/team_changed/
    role_changed_recently) plus two new columns (qb_changed, established_veteran) so the existing
    summarize_* helpers work unmodified, and the two new segments this phase needs are available."""
    weekly_with_shares = add_share_columns(weekly_stats)
    regular_season = weekly_with_shares[weekly_with_shares["season_type"] == "REG"]
    indexed_games = _index_games_by_player_season(weekly_with_shares)
    rows: list[dict] = []

    for week in weeks:
        as_of_date = _week_as_of_date(schedule, season, week)
        position_priors = compute_all_position_priors(weekly_with_shares, season=season, before_week=week)
        team_tendencies = compute_team_tendencies(weekly_with_shares, season=season, before_week=week)
        # A+B specifically uses the validated multi-year team prior instead of the brittle
        # single-season carry-forward -- 15.7a and old 15.7c above are completely unaffected.
        team_tendencies_v2 = compute_team_tendencies_v2(
            weekly_with_shares, multi_year_team_prior_by_team, season=season, before_week=week,
        )
        share_priors = (
            compute_share_priors_by_rank(weekly_with_shares, depth_charts, season=season, before_week=week, as_of_date=as_of_date)
            if as_of_date is not None else {}
        )
        roles_batch = load_current_roles_batch(depth_charts, as_of_date) if as_of_date is not None else {}

        actual_rows = regular_season[(regular_season["season"] == season) & (regular_season["week"] == week)]
        teams_this_week = actual_rows["team"].dropna().unique()
        qb_context_by_team = (
            {
                team: compute_qb_context(
                    current_team=team, prior_season_team=team,
                    weekly_stats=weekly_stats, prior_weekly_stats=weekly_stats,
                    depth_charts=depth_charts, as_of_date=as_of_date, season=season, before_week=week,
                )
                for team in teams_this_week
            }
            if as_of_date is not None else {}
        )

        for actual_row in actual_rows.to_dict("records"):
            position = actual_row["position"]
            if position not in POSITION_CATEGORIES:
                continue

            player_id = actual_row["player_id"]
            team = actual_row.get("team")
            actual_points = actual_row.get("fantasy_points_ppr")
            if actual_points is None or pd.isna(actual_points):
                continue

            current_games = _player_games(indexed_games, player_id, season, before_week=week)
            prior_games = _player_games(indexed_games, player_id, season - 1, before_week=None)
            experience_status = "veteran" if prior_games else "rookie_or_limited_history"
            team_changed = _team_changed(prior_games, actual_row)

            native_points = project_player_points(
                position, current_games, prior_games or None, position_priors[position], team_changed
            )

            role_confidence = "unknown"
            role_changed_recently = False
            context_points_old = None
            context_points_new = None
            qb_changed = False
            established_veteran = False
            a_only_points = None

            limited_seasons = {s: df for s, df in season_stats_by_year.items() if season - 4 <= s < season}
            career_seasons = build_career_seasons(limited_seasons, player_id, season)
            established_veteran = len(career_seasons) >= 3

            # A-only: 15.7c-A's own validated output, completely untouched by any B-layer context
            # (no team_changed/role_changed/qb multiplier) -- a true "career prior alone" baseline.
            a_only_prior = compute_career_prior(career_seasons)
            a_only_points = a_only_prior.workload.get("fantasy_points_per_game")

            if as_of_date is not None:
                role = roles_batch.get((player_id, position))
                if role is None:
                    fallback_confidence = "low" if roles_batch else "unknown"
                    role = RoleInfo(pos_rank=None, role_confidence=fallback_confidence, role_changed_recently=False)
                role_confidence = role.role_confidence
                role_changed_recently = role.role_changed_recently
                tendencies = team_tendencies.get(team, TeamTendencies(None, None))

                breakdown_old = project_context_aware_points_detailed(
                    position, current_games, prior_games or None, tendencies, role,
                    share_priors, position_priors[position],
                    team_changed, platform_points=None, availability_status="healthy",
                )
                context_points_old = breakdown_old.total_points if breakdown_old is not None else None

                qb_context = qb_context_by_team.get(team)
                if qb_context is not None:
                    qb_changed = qb_context.qb_changed
                    # No workload_confidence_multiplier from qb_changed anymore -- the real
                    # directional test found no consistent effect, so qb_changed stays purely
                    # informational (still passed into qb_context below for explainability/
                    # conflict detection, never into the math).
                    career_prior_b = compute_career_prior(
                        career_seasons, team_changed=team_changed, role_changed_recently=role_changed_recently,
                    )
                    tendencies_v2 = team_tendencies_v2.get(team, TeamTendencies(None, None))
                    breakdown_new = project_context_aware_points_detailed_v2(
                        position, current_games, prior_games or None, career_prior_b, career_seasons,
                        tendencies_v2, role, qb_context, share_priors, position_priors[position],
                        current_team=team, prior_season_team=team,
                        platform_points=None, availability_status="healthy",
                    )
                    context_points_new = breakdown_new.total_points if breakdown_new is not None else None

            for model, projected in (
                (MODEL_15_7A, native_points),
                (MODEL_CONTEXT_AWARE_OLD, context_points_old),
                (MODEL_A_ONLY, a_only_points),
                (MODEL_A_PLUS_B, context_points_new),
            ):
                rows.append({
                    "week": week, "player_id": player_id, "position": position,
                    "experience_status": experience_status, "team_changed": team_changed,
                    "role_changed_recently": role_changed_recently, "role_confidence": role_confidence,
                    "qb_changed": qb_changed, "established_veteran": established_veteran,
                    "model": model, "projected": projected, "actual": actual_points,
                })

    return rows


def summarize_signed_bias(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    scored = df[df["projected"].notna()].copy()
    if scored.empty:
        return pd.DataFrame(columns=["model", "signed_bias", "n"])
    scored["signed_error"] = scored["projected"] - scored["actual"]
    grouped = scored.groupby("model").agg(signed_bias=("signed_error", "mean"), n=("signed_error", "count"))
    return grouped.reset_index()


async def main() -> None:
    client = NflverseClient()
    season = 2025
    prior = await client.get_weekly_stats(str(season - 1))
    current = await client.get_weekly_stats(str(season))
    season_stats_by_year = await fetch_season_stats_range(client, current_season=season, lookback=4)
    depth_charts = await client.get_depth_charts(str(season))
    schedule = await client.get_schedule(str(season))

    # Real multi-year team-volume history for the validated team prior -- strictly seasons BEFORE
    # `season` (leak-safe: this backtest predicts 2025, so only 2021-2024 real data feeds the
    # team prior, exactly matching the "for Week 1 / zero current-season games" validated scenario).
    team_history_years = list(range(season - TEAM_PRIOR_LOOKBACK, season))
    team_weekly_by_year = {}
    for year in team_history_years:
        df = await client.get_weekly_stats(str(year))
        if not df.empty:
            team_weekly_by_year[year] = df
    await client.aclose()
    weekly_stats = pd.concat([prior, current], ignore_index=True)

    all_team_seasons = _real_team_seasons(team_weekly_by_year)
    teams = sorted({t for (t, s) in all_team_seasons})
    weight_fn = lambda offset, g, d=TEAM_PRIOR_DECAY: team_weight(offset, g, recency_decay=d)
    multi_year_team_prior_by_team: dict[str, TeamPrior] = {}
    for team in teams:
        team_seasons = _build_seasons_for_prediction(all_team_seasons, team, season, TEAM_PRIOR_LOOKBACK)
        if not team_seasons:
            continue
        multi_year_team_prior_by_team[team] = TeamPrior(
            pass_attempts_per_game=_weighted_average_with_fn(team_seasons, "pass_attempts_per_game", weight_fn),
            rush_attempts_per_game=_weighted_average_with_fn(team_seasons, "rush_attempts_per_game", weight_fn),
            seasons_used=len(team_seasons),
        )
    print(f"Real multi-year team priors computed for {len(multi_year_team_prior_by_team)} teams "
          f"(lookback={TEAM_PRIOR_LOOKBACK}, decay={TEAM_PRIOR_DECAY}), "
          f"e.g. MIN={multi_year_team_prior_by_team.get('MIN')}")

    weeks = list(range(1, 9))
    rows = run_four_arm_backtest(
        weekly_stats, season_stats_by_year, depth_charts, schedule, season, weeks, multi_year_team_prior_by_team,
    )

    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 220)

    print(f"\n=== Coverage ({len(rows)} total rows) ===")
    print(summarize_coverage(rows).to_string(index=False))

    print("\n=== Overall MAE/RMSE by model x position x experience_status ===")
    print(summarize_accuracy(rows).sort_values(["model", "position"]).to_string(index=False))

    print("\n=== Signed bias overall ===")
    print(summarize_signed_bias(rows).to_string(index=False))

    for model in (MODEL_15_7A, MODEL_CONTEXT_AWARE_OLD, MODEL_A_ONLY, MODEL_A_PLUS_B):
        print(f"\n=== Elite/startable segment: {model} ===")
        print(summarize_elite_segment(rows, model).to_string(index=False))

    print("\n=== Team-changer segment ===")
    print(summarize_segment(rows, "team_changed").to_string(index=False))

    print("\n=== QB-changer segment ===")
    print(summarize_segment(rows, "qb_changed").to_string(index=False))

    print("\n=== Role-changer segment ===")
    print(summarize_segment(rows, "role_changed_recently").to_string(index=False))

    print("\n=== Established-veteran segment (seasons_used >= 3) ===")
    print(summarize_segment(rows, "established_veteran").to_string(index=False))

    print("\n=== Pairwise Start/Sit ranking accuracy ===")
    for model in (MODEL_15_7A, MODEL_CONTEXT_AWARE_OLD, MODEL_A_ONLY, MODEL_A_PLUS_B):
        result = pairwise_ranking_accuracy(rows, model)
        print(f"  {model}: accuracy={result['accuracy']}, n={result['total']}")

    print("\n=== Common-sample comparison: 15.7a vs A+B (same player-weeks only) ===")
    print(common_sample_comparison(rows, MODEL_15_7A, MODEL_A_PLUS_B).to_string(index=False))

    pd.DataFrame(rows).to_csv("four_arm_validation_raw.csv", index=False)
    print("\nRaw rows written to four_arm_validation_raw.csv")


if __name__ == "__main__":
    asyncio.run(main())
