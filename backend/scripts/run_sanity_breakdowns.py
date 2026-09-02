import asyncio

import pandas as pd

from app.nflverse.client import NflverseClient
from app.projections.context_aware.career_prior import compute_career_prior
from app.projections.context_aware.career_prior_sync import fetch_season_stats_range
from app.projections.context_aware.depth_chart import RoleInfo, load_current_roles_batch
from app.projections.context_aware.explain import explain_projection
from app.projections.context_aware.model import compute_share_priors_by_rank, project_context_aware_points_detailed_v2
from app.projections.context_aware.qb_context import compute_qb_context
from app.projections.context_aware.team_context import compute_team_tendencies_v2
from app.projections.context_aware.team_prior import LOOKBACK_SEASONS as TEAM_PRIOR_LOOKBACK, RECENCY_DECAY as TEAM_PRIOR_DECAY, TeamPrior, team_weight
from scripts.run_career_prior_validation import build_career_seasons
from scripts.run_team_prior_validation import _build_seasons_for_prediction, _real_team_seasons, _weighted_average_with_fn

NAMED_PLAYERS = [
    ("Justin Jefferson", "WR"), ("Ja'Marr Chase", "WR"), ("Puka Nacua", "WR"), ("CeeDee Lamb", "WR"),
    ("Jonathan Taylor", "RB"), ("Bijan Robinson", "RB"),
    ("Josh Allen", "QB"), ("Patrick Mahomes", "QB"),
    ("Sam LaPorta", "TE"),
]


def _find_gsis_id(season_data: pd.DataFrame, name: str) -> str | None:
    matches = season_data[season_data["player_display_name"] == name]
    return matches.iloc[0]["player_id"] if not matches.empty else None


async def main():
    client = NflverseClient()
    season = 2026
    prior_season_data = 2025  # real 2025 season already complete -- most recent real prior season
    weekly_2025 = await client.get_weekly_stats("2025")
    weekly_2024 = await client.get_weekly_stats("2024")
    weekly_2023 = await client.get_weekly_stats("2023")
    weekly_2022 = await client.get_weekly_stats("2022")
    season_stats_by_year = await fetch_season_stats_range(client, current_season=season, lookback=4)
    depth_charts = await client.get_depth_charts("2025")
    schedule_2025 = await client.get_schedule("2025")
    await client.aclose()

    weekly_combined = pd.concat([weekly_2024, weekly_2025], ignore_index=True)
    season_2025_df = season_stats_by_year.get(2025)
    if season_2025_df is None or season_2025_df.empty:
        print("No real 2025 season-stats data available -- cannot proceed with real sanity examples.")
        return

    as_of_date = "2026-08-01"  # real preseason cutoff, after all of 2025's real depth-chart snapshots
    role_by_player = load_current_roles_batch(depth_charts, as_of_date)

    # Validated multi-year team prior (team_prior.py), same mechanism as run_four_arm_validation.py
    # -- replaces the brittle single-season carry-forward compute_team_tendencies used before.
    team_weekly_by_year = {2022: weekly_2022, 2023: weekly_2023, 2024: weekly_2024, 2025: weekly_2025}
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
    tendencies_by_team = compute_team_tendencies_v2(
        weekly_combined, multi_year_team_prior_by_team, season=prior_season_data + 1, before_week=1,
    )
    share_priors_by_rank = compute_share_priors_by_rank(
        weekly_combined, depth_charts, season=prior_season_data + 1, before_week=1, as_of_date=as_of_date,
    )

    from app.projections.native.model import compute_all_position_priors
    position_priors = compute_all_position_priors(weekly_combined, season=prior_season_data + 1, before_week=1)

    def _breakdown_for(gsis_id: str, position: str, team: str, prior_team: str | None):
        limited_seasons = {s: df for s, df in season_stats_by_year.items() if 2022 <= s <= 2025}
        career_seasons = build_career_seasons(limited_seasons, gsis_id, season)
        team_changed = bool(team and prior_team and team != prior_team)
        role = role_by_player.get((gsis_id, position), RoleInfo(pos_rank=None, role_confidence="unknown", role_changed_recently=False))

        qb_context = compute_qb_context(
            current_team=team, prior_season_team=prior_team,
            weekly_stats=weekly_combined, prior_weekly_stats=weekly_combined,
            depth_charts=depth_charts, as_of_date=as_of_date, season=prior_season_data + 1, before_week=1,
        )
        # No QB-change workload discount -- a directional test found no consistent effect on team
        # pass volume, so qb_changed stays purely informational (qb_context is still passed
        # through below for explainability only).
        career_prior = compute_career_prior(
            career_seasons, team_changed=team_changed, role_changed_recently=role.role_changed_recently,
        )
        tendencies = tendencies_by_team.get(team)
        if tendencies is None:
            from app.projections.context_aware.team_context import TeamTendencies
            tendencies = TeamTendencies(None, None)

        breakdown = project_context_aware_points_detailed_v2(
            position, [], None, career_prior, career_seasons, tendencies, role, qb_context,
            share_priors_by_rank, position_priors.get(position, {}),
            current_team=team, prior_season_team=prior_team,
            platform_points=None, availability_status="healthy",
        )
        return breakdown, career_prior, career_seasons, role, qb_context

    print("=== Named elite players ===\n")
    for name, position in NAMED_PLAYERS:
        gsis_id = _find_gsis_id(season_2025_df, name)
        if gsis_id is None:
            print(f"{name}: not found in real 2025 season data\n")
            continue
        row = season_2025_df[season_2025_df["player_id"] == gsis_id].iloc[0]
        team = row.get("recent_team")
        breakdown, career_prior, career_seasons, role, qb_context = _breakdown_for(gsis_id, position, team, team)
        print(f"--- {name} ({position}, team={team}) ---")
        print(f"seasons_used={career_prior.seasons_used}, real seasons: {[s.season for s in career_seasons]}")
        print(f"current role: pos_rank={role.pos_rank}, confidence={role.role_confidence}, role_changed_recently={role.role_changed_recently}")
        print(f"QB context: current={qb_context.current_qb_gsis_id}, prior={qb_context.prior_qb_gsis_id}, "
              f"changed={qb_context.qb_changed}, confidence={qb_context.confidence}")
        if breakdown is not None:
            print(explain_projection(breakdown))
            if breakdown.career_talent_prior:
                print("Talent priors:")
                for key, ep in breakdown.career_talent_prior.items():
                    print(f"  {key}: career={ep.career_value}, weight={ep.career_evidence_weight:.3f}, "
                          f"fallback={ep.fallback_value}, effective={ep.effective_value}")
            if breakdown.career_workload_prior:
                print("Workload priors:")
                for key, ep in breakdown.career_workload_prior.items():
                    print(f"  {key}: career={ep.career_value}, weight={ep.career_evidence_weight:.3f}, "
                          f"fallback={ep.fallback_value}, effective={ep.effective_value}")
        else:
            print("No projection produced.")
        print()


asyncio.run(main())
