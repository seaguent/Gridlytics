NEAR_ZERO_THRESHOLD = 1.0

# Heuristic default, not backtest-calibrated. Fraction: platform and context-aware projections
# disagree when the smaller is less than this fraction of the larger (e.g. 0.4 means "less than
# 40% of the other side"). This is diagnostic-only (never enters context_aware_points math), so
# miscalibration only affects how often the conflict flag fires, not projection accuracy.
DISAGREEMENT_RATIO_THRESHOLD = 0.4


def _magnitude_disagreement(context_aware_points: float, platform_points: float) -> bool:
    if context_aware_points <= NEAR_ZERO_THRESHOLD or platform_points <= NEAR_ZERO_THRESHOLD:
        return False  # near-zero cases are handled by the existing dedicated path below
    smaller, larger = sorted([context_aware_points, platform_points])
    return (smaller / larger) < DISAGREEMENT_RATIO_THRESHOLD


def detect_projection_conflict(
    context_aware_points: float,
    platform_points: float | None,
    availability_status: str,
    team_changed: bool,
    role_confidence: str,
    qb_changed: bool = False,
) -> tuple[bool, str | None]:
    if platform_points is None:
        return False, None  # no platform data to compare -- missing, not a conflict

    reasons = []
    if availability_status in ("questionable", "doubtful"):
        reasons.append(f"{availability_status} status")
    if team_changed:
        reasons.append("recent team change")
    if role_confidence in ("low", "unknown"):
        reasons.append("role unclear")
    if qb_changed:
        reasons.append("QB change")

    if platform_points <= NEAR_ZERO_THRESHOLD and context_aware_points > NEAR_ZERO_THRESHOLD:
        if not reasons:
            return False, None
        return True, f"platform near-zero + {' + '.join(reasons)}"

    if _magnitude_disagreement(context_aware_points, platform_points):
        if not reasons:
            return False, None
        return True, f"projections diverge + {' + '.join(reasons)}"

    return False, None
