from dataclasses import dataclass

import pandas as pd

ROLE_CHANGE_LOOKBACK_DAYS = 21


@dataclass
class RoleInfo:
    pos_rank: int | None
    role_confidence: str  # "high" | "low" | "unknown"
    role_changed_recently: bool


def _latest_snapshot_before(depth_charts: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    if depth_charts.empty:
        return depth_charts
    eligible = depth_charts[depth_charts["dt"] < as_of_date]
    if eligible.empty:
        return eligible
    latest_dt = eligible["dt"].max()
    return eligible[eligible["dt"] == latest_dt]


def _rank_at(depth_charts: pd.DataFrame, as_of_date: str, gsis_id: str, position: str) -> int | None:
    snapshot = _latest_snapshot_before(depth_charts, as_of_date)
    if snapshot.empty:
        return None
    rows = snapshot[(snapshot["gsis_id"] == gsis_id) & (snapshot["pos_abb"] == position)]
    if rows.empty:
        return None
    return int(rows.iloc[0]["pos_rank"])


def load_current_role(
    depth_charts: pd.DataFrame, gsis_id: str, position: str, as_of_date: str
) -> RoleInfo:
    snapshot = _latest_snapshot_before(depth_charts, as_of_date)
    if snapshot.empty:
        return RoleInfo(pos_rank=None, role_confidence="unknown", role_changed_recently=False)

    pos_rank = _rank_at(depth_charts, as_of_date, gsis_id, position)
    if pos_rank is None:
        return RoleInfo(pos_rank=None, role_confidence="low", role_changed_recently=False)

    earlier_cutoff = (pd.Timestamp(as_of_date) - pd.Timedelta(days=ROLE_CHANGE_LOOKBACK_DAYS)).isoformat()
    earlier_rank = _rank_at(depth_charts, earlier_cutoff, gsis_id, position)
    role_changed = earlier_rank is not None and earlier_rank != pos_rank

    return RoleInfo(pos_rank=pos_rank, role_confidence="high", role_changed_recently=role_changed)


def load_current_roles_batch(
    depth_charts: pd.DataFrame, as_of_date: str
) -> dict[tuple[str, str], RoleInfo]:
    """Batched load_current_role: computes the shared cutoff+lookback snapshots once per as_of_date instead of per player."""
    snapshot = _latest_snapshot_before(depth_charts, as_of_date)
    if snapshot.empty:
        return {}

    earlier_cutoff = (pd.Timestamp(as_of_date) - pd.Timedelta(days=ROLE_CHANGE_LOOKBACK_DAYS)).isoformat()
    earlier_snapshot = _latest_snapshot_before(depth_charts, earlier_cutoff)
    earlier_rank_by_key = (
        {(row["gsis_id"], row["pos_abb"]): int(row["pos_rank"]) for _, row in earlier_snapshot.iterrows()}
        if not earlier_snapshot.empty else {}
    )

    result: dict[tuple[str, str], RoleInfo] = {}
    for _, row in snapshot.iterrows():
        key = (row["gsis_id"], row["pos_abb"])
        pos_rank = int(row["pos_rank"])
        earlier_rank = earlier_rank_by_key.get(key)
        role_changed = earlier_rank is not None and earlier_rank != pos_rank
        result[key] = RoleInfo(pos_rank=pos_rank, role_confidence="high", role_changed_recently=role_changed)
    return result
