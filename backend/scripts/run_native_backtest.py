import asyncio

import pandas as pd

from app.nflverse.client import NflverseClient
from app.projections.native.backtest import run_backtest, summarize_backtest

SEASON = 2025
WEEKS = list(range(1, 19))


async def main() -> None:
    client = NflverseClient()
    try:
        prior = await client.get_weekly_stats(str(SEASON - 1))
        current = await client.get_weekly_stats(str(SEASON))
    finally:
        await client.aclose()

    weekly_stats = pd.concat([prior, current], ignore_index=True)

    rows = run_backtest(weekly_stats, season=SEASON, weeks=WEEKS)
    summary = summarize_backtest(rows)

    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 200)
    print(f"\n{len(rows)} total (player, week, model) evaluations across {len(WEEKS)} weeks of {SEASON}.\n")
    print(summary.sort_values(["model", "position", "experience_status"]).to_string(index=False))

    overall = (
        pd.DataFrame(rows)
        .assign(abs_error=lambda d: (d["projected"] - d["actual"]).abs())
        .groupby("model")["abs_error"]
        .agg(mae="mean", sample_size="count")
        .reset_index()
    )
    print("\nOverall MAE by model:\n")
    print(overall.to_string(index=False))


if __name__ == "__main__":
    asyncio.run(main())
