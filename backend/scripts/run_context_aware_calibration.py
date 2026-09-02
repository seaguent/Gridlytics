import asyncio

import pandas as pd

from app.nflverse.client import NflverseClient
from app.projections.context_aware.career_prior import compute_career_prior
from app.projections.context_aware.career_prior_sync import fetch_season_stats_range
from app.projections.context_aware.depth_chart import RoleInfo, load_current_roles_batch
from app.projections.context_aware.model import compute_share_priors_by_rank, project_context_aware_points_detailed_v2
from app.projections.context_aware.qb_context import compute_qb_context
from app.projections.context_aware.team_context import TeamTendencies, compute_team_tendencies
from app.projections.native.backtest import _index_games_by_player_season, _player_games
from app.projections.native.categories import POSITION_CATEGORIES
from app.projections.native.model import compute_all_position_priors
from scripts.run_career_prior_validation import build_career_seasons


def build_and_evaluate_v2(
    weekly_stats: pd.DataFrame,
    season_stats_by_year: dict[int, pd.DataFrame],
    season: int,
    weeks: list[int],
    talent_full_confidence: dict[str, float],
    workload_full_confidence: dict[str, float],
    qb_change_workload_multiplier: float,
    disagreement_ratio_threshold: float,
    depth_charts: pd.DataFrame | None = None,
    week_to_as_of_date: dict[int, str] | None = None,
) -> pd.DataFrame:
    """Real walk-forward evaluation of v2 with a given candidate parameter set. Temporarily
    monkeypatches the module-level PLACEHOLDER dicts/constants for the duration of this call --
    isolated per-call, never leaves a mutated global state behind. weekly_stats is real
    per-game data (current_games, QB pass-attempt inference); season_stats_by_year is real
    per-season data (CareerSeason construction) -- kept separate on purpose, never conflated.

    depth_charts/week_to_as_of_date default to empty/synthetic when omitted (keeps the unit
    tests in test_calibration.py minimal and self-contained); real calibration runs (main())
    pass real nflverse depth-chart data and real schedule-derived dates so share_priors_by_rank
    actually resolves real role-rank fallbacks -- an empty depth_charts silently collapses
    EVERY workload fallback to None, which bypasses the workload confidence weight entirely
    (compute_effective_prior trusts the career value alone when there's no fallback to blend
    toward) and makes the workload calibration dimension meaningless. Caught via a real first
    grid-search run where varying workload_full_confidence changed nothing -- confirmed as a
    harness bug, not a real finding, before trusting any calibration result.
    """
    import app.projections.context_aware.model as model_module
    import app.projections.context_aware.conflict as conflict_module

    original_talent = model_module.TALENT_FULL_CONFIDENCE_OPPORTUNITIES
    original_workload = model_module.WORKLOAD_FULL_CONFIDENCE_OPPORTUNITIES
    original_ratio = conflict_module.DISAGREEMENT_RATIO_THRESHOLD
    model_module.TALENT_FULL_CONFIDENCE_OPPORTUNITIES = talent_full_confidence
    model_module.WORKLOAD_FULL_CONFIDENCE_OPPORTUNITIES = workload_full_confidence
    conflict_module.DISAGREEMENT_RATIO_THRESHOLD = disagreement_ratio_threshold
    if depth_charts is None:
        depth_charts = pd.DataFrame(columns=["dt", "team", "gsis_id", "pos_abb", "pos_rank"])

    try:
        regular_season = weekly_stats[weekly_stats["season_type"] == "REG"]
        indexed_games = _index_games_by_player_season(weekly_stats)
        rows = []

        for week in weeks:
            as_of_date = (
                week_to_as_of_date[week] if week_to_as_of_date and week in week_to_as_of_date
                else f"{season}-01-01"
            )
            position_priors = compute_all_position_priors(weekly_stats, season=season, before_week=week)
            actual_rows = regular_season[(regular_season["season"] == season) & (regular_season["week"] == week)]
            tendencies_by_team = compute_team_tendencies(weekly_stats, season=season, before_week=week)
            share_priors_by_rank = compute_share_priors_by_rank(
                weekly_stats, depth_charts, season=season, before_week=week, as_of_date=as_of_date,
            )
            # Real per-player depth-chart rank, computed once per week (batch, not per player) --
            # without this, role.pos_rank stayed None for every player, which made
            # role_rank_prior_share always resolve to an empty lookup (share_priors_by_rank["WR"]
            # has no entry for pos_rank=-1) and silently disabled the entire workload confidence
            # weighting mechanism: with fallback_value=None, compute_effective_prior always took
            # its "no fallback to blend toward -- trust career value alone" branch, making
            # effective_value == career_value regardless of the confidence threshold. Caught via
            # direct per-player debug instrumentation after the aggregate MAE showed zero
            # variation across a wide, correctly-scaled candidate range.
            role_by_player = load_current_roles_batch(depth_charts, as_of_date)

            # QB context depends only on (team, week), not on the individual player -- computing
            # it once per team here (not once per player below) cut a real, profiled ~26s/53s of
            # redundant per-player recomputation down to a handful of real team lookups.
            teams_this_week = actual_rows["team"].dropna().unique()
            qb_context_by_team = {
                team: compute_qb_context(
                    current_team=team, prior_season_team=team,
                    weekly_stats=weekly_stats, prior_weekly_stats=weekly_stats,
                    depth_charts=depth_charts,
                    as_of_date=as_of_date, season=season, before_week=week,
                )
                for team in teams_this_week
            }

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
                qb_context = qb_context_by_team[team]

                limited_seasons = {s: df for s, df in season_stats_by_year.items() if season - 4 <= s < season}
                career_seasons = build_career_seasons(limited_seasons, player_id, season)
                career_prior = compute_career_prior(
                    career_seasons,
                    workload_confidence_multiplier=(
                        qb_change_workload_multiplier if qb_context.qb_changed else 1.0
                    ),
                )

                tendencies = tendencies_by_team.get(team, TeamTendencies(None, None))
                role = role_by_player.get(
                    (player_id, position), RoleInfo(pos_rank=None, role_confidence="unknown", role_changed_recently=False)
                )

                breakdown = project_context_aware_points_detailed_v2(
                    position, current_games, None, career_prior, career_seasons, tendencies, role,
                    qb_context, share_priors_by_rank, position_priors.get(position, {}),
                    current_team=team, prior_season_team=team,
                    platform_points=None, availability_status="healthy",
                )
                if breakdown is None or breakdown.total_points is None:
                    continue
                rows.append({"week": week, "player_id": player_id, "position": position,
                             "projected": breakdown.total_points, "actual": actual_points})

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["abs_error"] = (df["projected"] - df["actual"]).abs()
        return df.groupby("position").agg(mae=("abs_error", "mean"), n=("abs_error", "count")).reset_index()
    finally:
        model_module.TALENT_FULL_CONFIDENCE_OPPORTUNITIES = original_talent
        model_module.WORKLOAD_FULL_CONFIDENCE_OPPORTUNITIES = original_workload
        conflict_module.DISAGREEMENT_RATIO_THRESHOLD = original_ratio


async def main() -> None:
    client = NflverseClient()
    season = 2025
    prior = await client.get_weekly_stats(str(season - 1))
    current = await client.get_weekly_stats(str(season))
    season_stats_by_year = await fetch_season_stats_range(client, current_season=season, lookback=4)
    depth_charts = await client.get_depth_charts(str(season))
    schedule = await client.get_schedule(str(season))
    await client.aclose()
    weekly_stats = pd.concat([prior, current], ignore_index=True)

    # Real schedule-derived as_of_date per week (that week's earliest real game date) --
    # leak-safe cutoff for both the depth-chart snapshot and the share-priors-by-rank pool,
    # same pattern already proven in context_aware/depth_chart.py's own tests.
    week_to_as_of_date = {
        int(week): str(group["gameday"].min())
        for week, group in schedule.groupby("week")
    }
    print(f"Real depth_charts rows: {len(depth_charts)}, week_to_as_of_date: {week_to_as_of_date}")

    # Candidates scaled to REAL observed 4-season career opportunity totals (verified via direct
    # inspection of real players before picking these -- an established WR/RB routinely accrues
    # 300-700+ targets/carries across 4 seasons, a starting QB 1500-2500+ attempts; the first
    # calibration attempt used candidates an order of magnitude too small (50-300), which
    # saturated every candidate's confidence weight at 1.0 identically and made the grid search
    # meaningless -- caught by noticing zero variation across the whole workload dimension).
    # Final chosen values (see context_aware/model.py for the full narrowing history):
    # talent=250 (real interior optimum, beats both 150 and 400), workload=1 (MAE kept improving
    # all the way down -- the discount mechanism doesn't add value for workload in the tested
    # range; kept a real >0 range here for anyone re-running this to confirm/challenge that).
    talent_candidates = [150, 250, 400]
    workload_candidates = [1, 5, 30]
    results = []
    for t in talent_candidates:
        for w in workload_candidates:
            summary = build_and_evaluate_v2(
                weekly_stats, season_stats_by_year, season=season, weeks=list(range(1, 5)),
                talent_full_confidence={"receiving": t, "rushing": t, "passing": t * 3},
                workload_full_confidence={"receiving": w, "rushing": w},
                qb_change_workload_multiplier=0.7, disagreement_ratio_threshold=0.4,
                depth_charts=depth_charts, week_to_as_of_date=week_to_as_of_date,
            )
            if not summary.empty:
                overall_mae = (summary["mae"] * summary["n"]).sum() / summary["n"].sum()
                results.append({"talent": t, "workload": w, "mae": overall_mae, "n": summary["n"].sum()})
                print(f"talent={t} workload={w}: MAE={overall_mae:.4f} n={summary['n'].sum()}")

    pd.DataFrame(results).sort_values("mae").to_csv("context_aware_calibration_results.csv", index=False)


if __name__ == "__main__":
    asyncio.run(main())
