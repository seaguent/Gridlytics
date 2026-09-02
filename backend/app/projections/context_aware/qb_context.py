from dataclasses import dataclass

import pandas as pd

from app.projections.context_aware.depth_chart import _latest_snapshot_before


@dataclass(frozen=True)
class QBContext:
    current_qb_gsis_id: str | None
    prior_qb_gsis_id: str | None
    qb_changed: bool
    confidence: str  # "depth_chart" | "pass_attempts" | "prior_starter" | "unknown"


def _depth_chart_qb1(depth_charts: pd.DataFrame, team: str, as_of_date: str) -> str | None:
    snapshot = _latest_snapshot_before(depth_charts, as_of_date)
    if snapshot.empty:
        return None
    rows = snapshot[(snapshot["team"] == team) & (snapshot["pos_abb"] == "QB") & (snapshot["pos_rank"] == 1)]
    if rows.empty:
        return None
    return rows.iloc[0]["gsis_id"]


def _pass_attempt_leader(
    weekly_stats: pd.DataFrame, team: str, season: int, before_week: int | None
) -> str | None:
    if weekly_stats.empty:
        return None
    reg = weekly_stats[
        (weekly_stats["season_type"] == "REG") & (weekly_stats["team"] == team) & (weekly_stats["season"] == season)
    ]
    if before_week is not None:
        reg = reg[reg["week"] < before_week]
    if reg.empty:
        return None
    totals = reg.groupby("player_id")["attempts"].sum()
    totals = totals[totals > 0]
    if totals.empty:
        return None
    return totals.idxmax()


def infer_starting_qb(
    team: str,
    weekly_stats: pd.DataFrame,
    prior_weekly_stats: pd.DataFrame,
    depth_charts: pd.DataFrame,
    as_of_date: str,
    season: int,
    before_week: int | None,
) -> tuple[str | None, str]:
    qb1 = _depth_chart_qb1(depth_charts, team, as_of_date)
    if qb1 is not None:
        return qb1, "depth_chart"

    current_leader = _pass_attempt_leader(weekly_stats, team, season, before_week)
    if current_leader is not None:
        return current_leader, "pass_attempts"

    prior_leader = _pass_attempt_leader(prior_weekly_stats, team, season - 1, None)
    if prior_leader is not None:
        return prior_leader, "prior_starter"

    return None, "unknown"


def compute_qb_context(
    current_team: str,
    prior_season_team: str | None,
    weekly_stats: pd.DataFrame,
    prior_weekly_stats: pd.DataFrame,
    depth_charts: pd.DataFrame,
    as_of_date: str,
    season: int,
    before_week: int | None,
) -> QBContext:
    current_qb, current_confidence = infer_starting_qb(
        current_team, weekly_stats, prior_weekly_stats, depth_charts, as_of_date, season, before_week
    )
    prior_qb = (
        _pass_attempt_leader(prior_weekly_stats, prior_season_team, season - 1, None)
        if prior_season_team is not None else None
    )
    # Never a false positive: both sides must be real, known identities to flag a real change.
    qb_changed = current_qb is not None and prior_qb is not None and current_qb != prior_qb

    return QBContext(
        current_qb_gsis_id=current_qb, prior_qb_gsis_id=prior_qb,
        qb_changed=qb_changed, confidence=current_confidence,
    )
