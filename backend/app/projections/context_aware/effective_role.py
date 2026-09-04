from dataclasses import dataclass

import pandas as pd

from app.projections.context_aware.depth_chart import _latest_snapshot_before


@dataclass
class TeammateStatus:
    gsis_id: str
    pos_rank: int | None
    availability_status: str


def load_same_position_groups(depth_charts: pd.DataFrame, as_of_date: str) -> dict[tuple[str, str], list[str]]:
    """(team, position) -> gsis_ids sharing that room, from the same snapshot load_current_roles_batch uses."""
    snapshot = _latest_snapshot_before(depth_charts, as_of_date)
    if snapshot.empty:
        return {}

    groups: dict[tuple[str, str], list[str]] = {}
    for _, row in snapshot.iterrows():
        groups.setdefault((row["team"], row["pos_abb"]), []).append(row["gsis_id"])
    return groups


def compute_effective_pos_rank(
    gsis_id: str,
    original_pos_rank: int | None,
    teammates: list[TeammateStatus],
) -> int | None:
    """Only "unavailable" teammates trigger a promotion; unknown availability is treated as available, never promoted away from."""
    if original_pos_rank is None:
        return None

    ranked = [t for t in teammates if t.pos_rank is not None]
    if not any(t.gsis_id == gsis_id for t in ranked):
        return original_pos_rank

    available = sorted((t for t in ranked if t.availability_status != "unavailable"), key=lambda t: t.pos_rank)
    for new_rank, teammate in enumerate(available, start=1):
        if teammate.gsis_id == gsis_id:
            return new_rank

    # This player itself is the one who's unavailable -- their own projection is already
    # hard-gated to zero elsewhere (availability_status == "unavailable" short-circuits
    # project_context_aware_points_detailed_v2), so the rank returned here is moot either way.
    return original_pos_rank
