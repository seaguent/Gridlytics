import asyncio

import pandas as pd

from app.nflverse.client import NflverseClient
from app.projections.context_aware.career_prior import compute_career_prior
from app.projections.context_aware.career_prior_sync import fetch_season_stats_range
from app.projections.context_aware.depth_chart import RoleInfo, load_current_roles_batch
from app.projections.context_aware.model import (
    add_share_columns,
    compute_share_priors_by_rank,
    project_context_aware_points_detailed_v2,
)
from app.projections.context_aware.qb_context import compute_qb_context
from app.projections.context_aware.team_context import TeamTendencies, compute_team_tendencies_v2
from app.projections.context_aware.team_prior import LOOKBACK_SEASONS as TEAM_PRIOR_LOOKBACK, RECENCY_DECAY as TEAM_PRIOR_DECAY, TeamPrior, team_weight
from app.projections.native.backtest import _index_games_by_player_season, _player_games, _team_changed
from app.projections.native.categories import POSITION_CATEGORIES, SCORING_FIELD_BY_CATEGORY_RATE
from app.projections.native.model import compute_all_position_priors, project_player_points_detailed
from app.projections.scoring_rules import STANDARD_PPR
from scripts.run_career_prior_validation import build_career_seasons
from scripts.run_four_arm_validation import MODEL_15_7A, MODEL_A_PLUS_B, _week_as_of_date
from scripts.run_team_prior_validation import _build_seasons_for_prediction, _real_team_seasons, _weighted_average_with_fn


def _component_rows_for_category(
    model: str,
    position: str,
    week: int,
    player_id: str,
    category_name: str,
    opportunity_column: str,
    rate_specs: dict[str, tuple[str, float]],
    expected_opportunities: float | None,
    shrunk_rates: dict[str, float],
    actual_row: dict,
) -> list[dict]:
    """Abstains are skipped entirely -- never fabricated as a zero projection."""
    if expected_opportunities is None:
        return []

    rows = [{
        "model": model, "position": position, "category": category_name, "component": opportunity_column,
        "week": week, "player_id": player_id,
        "projected": expected_opportunities, "actual": actual_row.get(opportunity_column),
        "points_per_unit": None,
    }]
    for rate_name, (raw_column, _default_ppu) in rate_specs.items():
        shrunk_rate = shrunk_rates.get(rate_name)
        if shrunk_rate is None:
            continue
        points_per_unit = getattr(STANDARD_PPR, SCORING_FIELD_BY_CATEGORY_RATE[(category_name, rate_name)])
        rows.append({
            "model": model, "position": position, "category": category_name, "component": raw_column,
            "week": week, "player_id": player_id,
            "projected": expected_opportunities * shrunk_rate, "actual": actual_row.get(raw_column),
            "points_per_unit": points_per_unit,
        })
    return rows


def run_bias_forensic_audit(
    weekly_stats: pd.DataFrame,
    season_stats_by_year: dict[int, pd.DataFrame],
    depth_charts: pd.DataFrame,
    schedule: pd.DataFrame,
    season: int,
    weeks: list[int],
    multi_year_team_prior_by_team: dict[str, TeamPrior],
) -> list[dict]:
    weekly_with_shares = add_share_columns(weekly_stats)
    regular_season = weekly_with_shares[weekly_with_shares["season_type"] == "REG"]
    indexed_games = _index_games_by_player_season(weekly_with_shares)
    rows: list[dict] = []

    for week in weeks:
        as_of_date = _week_as_of_date(schedule, season, week)
        if as_of_date is None:
            continue

        position_priors = compute_all_position_priors(weekly_with_shares, season=season, before_week=week)
        team_tendencies_v2 = compute_team_tendencies_v2(
            weekly_with_shares, multi_year_team_prior_by_team, season=season, before_week=week,
        )
        share_priors = compute_share_priors_by_rank(
            weekly_with_shares, depth_charts, season=season, before_week=week, as_of_date=as_of_date
        )
        roles_batch = load_current_roles_batch(depth_charts, as_of_date)

        actual_rows = regular_season[(regular_season["season"] == season) & (regular_season["week"] == week)]
        teams_this_week = actual_rows["team"].dropna().unique()
        qb_context_by_team = {
            team: compute_qb_context(
                current_team=team, prior_season_team=team,
                weekly_stats=weekly_stats, prior_weekly_stats=weekly_stats,
                depth_charts=depth_charts, as_of_date=as_of_date, season=season, before_week=week,
            )
            for team in teams_this_week
        }

        for actual_row in actual_rows.to_dict("records"):
            position = actual_row["position"]
            categories = POSITION_CATEGORIES.get(position)
            if not categories:
                continue

            player_id = actual_row["player_id"]
            team = actual_row.get("team")
            actual_points = actual_row.get("fantasy_points_ppr")
            if actual_points is None or pd.isna(actual_points):
                continue

            current_games = _player_games(indexed_games, player_id, season, before_week=week)
            prior_games = _player_games(indexed_games, player_id, season - 1, before_week=None)
            team_changed = _team_changed(prior_games, actual_row)

            # native_15_7a: real per-rate shrunk values now exposed via CategoryBreakdown.shrunk_rates.
            native_breakdown = project_player_points_detailed(
                position, current_games, prior_games or None, position_priors[position], team_changed
            )
            if native_breakdown is not None:
                for category in native_breakdown.categories:
                    rate_specs = next(c.rate_specs for c in categories if c.name == category.name)
                    opportunity_column = next(c.opportunity_column for c in categories if c.name == category.name)
                    rows.extend(_component_rows_for_category(
                        MODEL_15_7A, position, week, player_id, category.name, opportunity_column,
                        rate_specs, category.expected_opportunities, category.shrunk_rates, actual_row,
                    ))

            # context_aware_15_7c_b (A+B): same diagnostic surfaced via CategoryShareBreakdown.shrunk_rates.
            role = roles_batch.get((player_id, position))
            if role is None:
                fallback_confidence = "low" if roles_batch else "unknown"
                role = RoleInfo(pos_rank=None, role_confidence=fallback_confidence, role_changed_recently=False)

            qb_context = qb_context_by_team.get(team)
            if qb_context is None:
                continue

            limited_seasons = {s: df for s, df in season_stats_by_year.items() if season - 4 <= s < season}
            career_seasons = build_career_seasons(limited_seasons, player_id, season)
            career_prior_b = compute_career_prior(
                career_seasons, team_changed=team_changed, role_changed_recently=role.role_changed_recently,
            )
            tendencies_v2 = team_tendencies_v2.get(team, TeamTendencies(None, None))
            breakdown_new = project_context_aware_points_detailed_v2(
                position, current_games, prior_games or None, career_prior_b, career_seasons,
                tendencies_v2, role, qb_context, share_priors, position_priors[position],
                current_team=team, prior_season_team=team,
                platform_points=None, availability_status="healthy",
            )
            if breakdown_new is not None:
                for category in breakdown_new.categories:
                    rate_specs = next(c.rate_specs for c in categories if c.name == category.name)
                    opportunity_column = next(c.opportunity_column for c in categories if c.name == category.name)
                    rows.extend(_component_rows_for_category(
                        MODEL_A_PLUS_B, position, week, player_id, category.name, opportunity_column,
                        rate_specs, category.expected_opportunities, category.shrunk_rates, actual_row,
                    ))

    return rows


def summarize_component_bias(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    scored = df[df["projected"].notna() & df["actual"].notna()].copy()
    if scored.empty:
        return pd.DataFrame(columns=[
            "model", "position", "category", "component",
            "mean_projected", "mean_actual", "mean_error", "fantasy_point_contribution", "n",
        ])
    scored["error"] = scored["projected"] - scored["actual"]
    grouped = scored.groupby(["model", "position", "category", "component"]).agg(
        mean_projected=("projected", "mean"),
        mean_actual=("actual", "mean"),
        mean_error=("error", "mean"),
        points_per_unit=("points_per_unit", "first"),
        n=("error", "count"),
    ).reset_index()
    grouped["fantasy_point_contribution"] = grouped["mean_error"] * grouped["points_per_unit"]
    return grouped.drop(columns=["points_per_unit"])


async def main() -> None:
    client = NflverseClient()
    season = 2025
    prior = await client.get_weekly_stats(str(season - 1))
    current = await client.get_weekly_stats(str(season))
    season_stats_by_year = await fetch_season_stats_range(client, current_season=season, lookback=4)
    depth_charts = await client.get_depth_charts(str(season))
    schedule = await client.get_schedule(str(season))

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

    weeks = list(range(1, 9))
    rows = run_bias_forensic_audit(
        weekly_stats, season_stats_by_year, depth_charts, schedule, season, weeks, multi_year_team_prior_by_team,
    )

    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 220)

    summary = summarize_component_bias(rows)
    print(f"\n=== Component-level bias audit ({len(rows)} raw component rows) ===")
    print(summary.sort_values(["position", "category", "component", "model"]).to_string(index=False))

    pd.DataFrame(rows).to_csv("bias_forensic_audit_raw.csv", index=False)
    summary.to_csv("bias_forensic_audit_summary.csv", index=False)
    print("\nRaw rows written to bias_forensic_audit_raw.csv, summary to bias_forensic_audit_summary.csv")


if __name__ == "__main__":
    asyncio.run(main())
