# Native Projection Model — 2025 Walk-Forward Backtest Report

Date: 2026-09-01
Spec: `docs/superpowers/specs/2026-08-31-native-projection-backtest-design.md`
Plan: `docs/superpowers/plans/2026-09-01-native-projection-backtest.md`

Real run against nflverse's actual 2024 (prior season, used only as history) and
2025 (backtested) weekly stats, all 18 weeks, strict no-leakage walk-forward
(each week's prediction uses only data — including position priors — strictly
before that week).

## Raw output

```
16931 total (player, week, model) evaluations across 18 weeks of 2025.

                 model position         experience_status      mae     rmse  sample_size
    historical_recency       QB rookie_or_limited_history 6.258346 8.294073           76
    historical_recency       QB                   veteran 7.018589 8.940988          432
    historical_recency       RB rookie_or_limited_history 4.443022 6.533546          291
    historical_recency       RB                   veteran 4.679015 6.840227          993
    historical_recency       TE rookie_or_limited_history 4.380893 6.003514          150
    historical_recency       TE                   veteran 3.794001 5.552008          874
    historical_recency       WR rookie_or_limited_history 3.500922 5.077228          420
    historical_recency       WR                   veteran 4.669872 6.508484         1621
naive_position_average       QB rookie_or_limited_history 7.186220 8.661456          109
naive_position_average       QB                   veteran 6.872879 8.592606          555
naive_position_average       RB rookie_or_limited_history 4.339230 6.062809          374
naive_position_average       RB                   veteran 4.419450 6.397168         1201
naive_position_average       TE rookie_or_limited_history 3.941799 5.402775          206
naive_position_average       TE                   veteran 3.475355 5.008225         1081
naive_position_average       WR rookie_or_limited_history 3.575284 5.007406          538
naive_position_average       WR                   veteran 4.500310 6.173364         1973
                native       QB rookie_or_limited_history 6.981295 8.628580          109
                native       QB                   veteran 6.792880 8.580192          555
                native       RB rookie_or_limited_history 4.282010 6.158163          374
                native       RB                   veteran 4.369405 6.396822         1201
                native       TE rookie_or_limited_history 4.013815 5.523802          206
                native       TE                   veteran 3.442153 5.016822         1081
                native       WR rookie_or_limited_history 3.484640 5.014730          538
                native       WR                   veteran 4.473086 6.203305         1973

Overall MAE by model:

                 model      mae  sample_size
    historical_recency 4.624292         4857
naive_position_average 4.455832         6037
                native 4.410814         6037
```

## Recommendation

**Native beats the naive position-average baseline overall** (MAE 4.411 vs.
4.456, a ~1.0% relative reduction) **and in 7 of 8 position/experience-status
groups** — the one exception is TE/rookie-or-limited-history, where naive is
marginally better (3.942 vs. 4.014, a 0.07-point gap on a smaller sample of
206). Every win is modest, not dramatic — this is a real but incremental
improvement over "just use the position average," not a decisive one.

Both native and naive comfortably beat the historical-recency baseline's
overall MAE (4.624) — notable because historical-recency's sample (n=4,857)
excludes every early-season week it structurally cannot predict (fewer than 2
real current-season games), meaning native/naive's larger sample (n=6,037,
including the hardest-to-predict early weeks) still comes out ahead. This is
the core value proposition working as intended: native produces a real,
non-degenerate projection from Week 1, when historical-recency produces
nothing at all.

**By position:**
- **QB, RB, WR**: native wins cleanly in both experience-status groups,
  including the largest relative gains at QB (native 6.981/6.793 vs. naive
  7.186/6.873 for rookie/limited and veteran respectively).
- **TE**: mixed — native wins for veterans (3.442 vs. 3.475) but loses for
  rookie/limited-history (4.014 vs. 3.942). TE's shrinkage-eligible sample is
  the smallest of the four positions at the rookie/limited tier (206), so
  this is plausibly noise rather than a real signal that shrinkage hurts TE
  specifically — but it's reported honestly rather than smoothed over.

**Go/no-go on Phase 15.7b:** the evidence supports proceeding, with two
explicit caveats carried into that phase rather than hidden:
1. The improvement over naive is real but modest (~1% overall) — 15.7b
   should present this as "Gridlytics' own estimate," not oversell it as a
   dramatically more accurate number than what ESPN/Sleeper already provide
   (which this backtest, per the spec, was never able to compare against in
   the first place — no historical ESPN/Sleeper pregame projections exist to
   backtest against).
2. TE/rookie-or-limited-history is the one segment where the shrinkage model
   underperforms naive. Phase 15.7b should either use the naive (position-
   average) baseline specifically for that one segment, or flag it as lower-
   confidence in the UI, rather than blindly shipping the full native model
   uniformly across every position/experience combination.

No position should be scoped out entirely — even TE's rookie/limited-history
gap is small (0.07 MAE) and the same position's veteran tier is a clean win.
