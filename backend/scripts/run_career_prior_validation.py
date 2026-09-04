import asyncio

import pandas as pd

from app.nflverse.client import NflverseClient
from app.projections.context_aware.career_prior import CareerSeason, career_weight, compute_career_prior
# build_career_seasons moved to career_prior_sync.py (production module, shared with the live
# sync) -- re-exported here so this script's own callers/tests keep working unchanged.
from app.projections.context_aware.career_prior_sync import build_career_seasons, fetch_season_stats_range


def _float_or_none(value):
    if value is None or pd.isna(value):
        return None
    return float(value)


def evaluate_lookback_and_decay(
    season_stats_by_year: dict[int, pd.DataFrame],
    held_out_season: int,
    lookback_candidates: list[int],
    decay_candidates: list[float],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Raw rows carry seasons_used and actual/predicted so subgroup checks can filter without refetching."""
    held_out_df = season_stats_by_year.get(held_out_season)
    if held_out_df is None or held_out_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    held_out_reg = held_out_df[held_out_df["season_type"] == "REG"]

    rows = []
    for _, actual_row in held_out_reg.iterrows():
        gsis_id = actual_row["player_id"]
        games = actual_row.get("games") or 0
        actual_ppg = (actual_row.get("fantasy_points_ppr") or 0) / games if games else None
        if actual_ppg is None:
            continue

        for lookback in lookback_candidates:
            limited = {s: df for s, df in season_stats_by_year.items() if held_out_season - lookback <= s < held_out_season}
            seasons = build_career_seasons(limited, gsis_id, held_out_season)
            if not seasons:
                continue

            for decay in decay_candidates:
                weight_fn = lambda offset, g, d=decay: career_weight(offset, g, recency_decay=d)
                prior = compute_career_prior_with_weight_fn(seasons, weight_fn)
                predicted = prior.workload.get("fantasy_points_per_game")
                if predicted is None:
                    continue
                rows.append({
                    "lookback": lookback, "decay": decay, "player_id": gsis_id,
                    "seasons_used": len(seasons), "predicted": predicted, "actual": actual_ppg,
                })

    if not rows:
        return pd.DataFrame(), pd.DataFrame()
    raw = pd.DataFrame(rows)
    raw["abs_error"] = (raw["predicted"] - raw["actual"]).abs()
    raw["signed_error"] = raw["predicted"] - raw["actual"]
    summary = raw.groupby(["lookback", "decay"]).agg(mae=("abs_error", "mean"), n=("abs_error", "count")).reset_index()
    return summary, raw


def compute_career_prior_with_weight_fn(seasons, weight_fn):
    # Thin adapter: compute_career_prior always uses the module-level career_weight default:
    # this swaps in a candidate decay value for the grid search without changing the real
    # function's public signature (which stays fixed at its backtest-CHOSEN default afterward).
    from app.projections.context_aware.career_prior import _weighted_average, TALENT_STATS, WORKLOAD_STATS, CareerPrior
    talent = {stat: _weighted_average(seasons, stat, weight_fn) for stat in TALENT_STATS}
    workload = {stat: _weighted_average(seasons, stat, weight_fn) for stat in WORKLOAD_STATS}
    return CareerPrior(talent=talent, workload=workload, seasons_used=len(seasons), talent_tier="unknown")


async def main() -> None:
    client = NflverseClient()
    held_out_season = 2025
    all_seasons = await fetch_season_stats_range(client, current_season=held_out_season + 1, lookback=6)
    all_seasons[held_out_season] = await client.get_season_stats(str(held_out_season))
    await client.aclose()

    summary, raw = evaluate_lookback_and_decay(
        all_seasons, held_out_season=held_out_season,
        lookback_candidates=[1, 2, 3, 4], decay_candidates=[0.4, 0.55, 0.65, 0.75, 0.85, 1.0],
    )
    pd.set_option("display.max_rows", None)
    print("=== Grid search: MAE by (lookback, decay) ===")
    print(summary.sort_values("mae").to_string(index=False))
    raw.to_csv("career_prior_validation_raw.csv", index=False)
    print("\nRaw per-player rows written to career_prior_validation_raw.csv "
          "(seasons_used, predicted, actual, abs_error, signed_error per player per candidate) "
          "-- Task 9 Steps 4-5 filter this file directly.")


if __name__ == "__main__":
    asyncio.run(main())
