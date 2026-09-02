import asyncio

import pandas as pd

from app.nflverse.client import NflverseClient
from app.projections.context_aware.qb_context import _pass_attempt_leader
from app.projections.context_aware.team_prior import TeamSeason, compute_team_prior, team_weight
# _real_team_seasons/_build_seasons_for_prediction moved to team_prior.py (production module,
# shared with the live sync) -- re-exported here under their original names so this script's own
# callers/tests keep working unchanged.
from app.projections.context_aware.team_prior import (
    build_team_seasons_for_prediction as _build_seasons_for_prediction,
    real_team_seasons as _real_team_seasons,
)

SEASONS = list(range(2018, 2026))  # real nflverse weekly data, 2018-2025


def evaluate_lookback_and_decay(
    all_team_seasons: dict[tuple[str, int], TeamSeason],
    target_seasons: list[int],
    lookback_candidates: list[int],
    decay_candidates: list[float],
) -> pd.DataFrame:
    teams = sorted({t for (t, s) in all_team_seasons})
    rows = []
    for target_season in target_seasons:
        for team in teams:
            actual = all_team_seasons.get((team, target_season))
            if actual is None or actual.pass_attempts_per_game is None:
                continue

            # BASELINE: single most-recent prior season alone -- what team_context.py effectively
            # does today with zero current-season games (prior_season_weight(0) == 1.0, no other
            # season contributes at all).
            baseline_seasons = _build_seasons_for_prediction(all_team_seasons, team, target_season, lookback=1)
            baseline_pred = compute_team_prior(baseline_seasons).pass_attempts_per_game
            if baseline_pred is not None:
                rows.append({"target_season": target_season, "team": team, "model": "baseline_1yr",
                             "lookback": 1, "decay": None,
                             "predicted": baseline_pred, "actual": actual.pass_attempts_per_game})

            for lookback in lookback_candidates:
                seasons = _build_seasons_for_prediction(all_team_seasons, team, target_season, lookback)
                if not seasons:
                    continue
                for decay in decay_candidates:
                    weight_fn = lambda offset, g, d=decay: team_weight(offset, g, recency_decay=d)
                    pred = _weighted_average_with_fn(seasons, "pass_attempts_per_game", weight_fn)
                    if pred is None:
                        continue
                    rows.append({"target_season": target_season, "team": team,
                                 "model": f"multi_year", "lookback": lookback, "decay": decay,
                                 "predicted": pred, "actual": actual.pass_attempts_per_game})

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["abs_error"] = (df["predicted"] - df["actual"]).abs()
    return df


def _weighted_average_with_fn(seasons, stat_name, weight_fn):
    weighted_sum = 0.0
    total_weight = 0.0
    for season in seasons:
        value = getattr(season, stat_name)
        if value is None:
            continue
        weight = weight_fn(season.season_offset, season.games)
        weighted_sum += weight * value
        total_weight += weight
    return weighted_sum / total_weight if total_weight > 0 else None


async def main() -> None:
    client = NflverseClient()
    weekly_by_year = {}
    for season in SEASONS:
        df = await client.get_weekly_stats(str(season))
        if not df.empty:
            weekly_by_year[season] = df
    await client.aclose()
    print(f"Real seasons fetched: {sorted(weekly_by_year.keys())}")

    all_team_seasons = _real_team_seasons(weekly_by_year)
    target_seasons = [s for s in SEASONS if s - 1 in weekly_by_year][1:]  # need >=1 real prior season
    print(f"Held-out target seasons for validation: {target_seasons}\n")

    raw = evaluate_lookback_and_decay(
        all_team_seasons, target_seasons,
        lookback_candidates=[2, 3, 4], decay_candidates=[0.4, 0.55, 0.65, 0.75, 0.85, 1.0],
    )

    print("=== Baseline (current live behavior: single most-recent prior season) ===")
    baseline = raw[raw["model"] == "baseline_1yr"]
    print(f"  MAE={baseline['abs_error'].mean():.4f}  n={len(baseline)}")

    print("\n=== Multi-year candidates (lookback x decay) ===")
    multi = raw[raw["model"] == "multi_year"]
    summary = multi.groupby(["lookback", "decay"])["abs_error"].agg(["mean", "count"]).reset_index()
    summary = summary.rename(columns={"mean": "mae", "count": "n"}).sort_values("mae")
    print(summary.to_string(index=False))

    best = summary.iloc[0]
    print(f"\nBest multi-year candidate: lookback={best['lookback']}, decay={best['decay']}, "
          f"MAE={best['mae']:.4f} (baseline MAE={baseline['abs_error'].mean():.4f})")

    # --- QB-change directional test ---
    print("\n=== QB-change directional effect on real team pass-attempt DELTA (season N vs N-1) ===")
    qb_change_deltas = []
    no_change_deltas = []
    for target_season in target_seasons:
        prior_season = target_season - 1
        if prior_season not in weekly_by_year or target_season not in weekly_by_year:
            continue
        for team in sorted({t for (t, s) in all_team_seasons if s == target_season}):
            prior_row = all_team_seasons.get((team, prior_season))
            current_row = all_team_seasons.get((team, target_season))
            if prior_row is None or current_row is None:
                continue
            if prior_row.pass_attempts_per_game is None or current_row.pass_attempts_per_game is None:
                continue
            prior_qb = _pass_attempt_leader(weekly_by_year[prior_season], team, prior_season, None)
            current_qb = _pass_attempt_leader(weekly_by_year[target_season], team, target_season, None)
            if prior_qb is None or current_qb is None:
                continue
            delta = current_row.pass_attempts_per_game - prior_row.pass_attempts_per_game
            if prior_qb != current_qb:
                qb_change_deltas.append(delta)
            else:
                no_change_deltas.append(delta)

    qb_change_series = pd.Series(qb_change_deltas)
    no_change_series = pd.Series(no_change_deltas)
    print(f"  QB-changed team-seasons:    mean delta={qb_change_series.mean():+.3f}, "
          f"std={qb_change_series.std():.3f}, n={len(qb_change_series)}")
    print(f"  QB-unchanged team-seasons:  mean delta={no_change_series.mean():+.3f}, "
          f"std={no_change_series.std():.3f}, n={len(no_change_series)}")

    # --- MIN case study ---
    print("\n=== Minnesota (MIN) case study ===")
    for season in sorted(s for (t, s) in all_team_seasons if t == "MIN"):
        ts = all_team_seasons[("MIN", season)]
        print(f"  {season}: pass_attempts_per_game={ts.pass_attempts_per_game:.2f}, games={ts.games}")

    best_lookback = int(best["lookback"])
    best_decay = float(best["decay"])
    min_seasons = _build_seasons_for_prediction(all_team_seasons, "MIN", 2026, best_lookback)
    weight_fn = lambda offset, g, d=best_decay: team_weight(offset, g, recency_decay=d)
    min_prediction = _weighted_average_with_fn(min_seasons, "pass_attempts_per_game", weight_fn)
    print(f"\n  Validated model (lookback={best_lookback}, decay={best_decay}) 2026 prediction: "
          f"{min_prediction:.2f} pass attempts/game")
    print(f"  (current live baseline would use: {all_team_seasons[('MIN', 2025)].pass_attempts_per_game:.2f})")


if __name__ == "__main__":
    asyncio.run(main())
