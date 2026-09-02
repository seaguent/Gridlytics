from app.projections.context_aware.model import CareerAwareBreakdown


def explain_projection(breakdown: CareerAwareBreakdown) -> str:
    if breakdown.total_points is None:
        return f"No projection ({breakdown.availability_status})."

    lines = [f"Gridlytics: {breakdown.total_points:.1f}", ""]

    for category in breakdown.categories:
        if category.expected_opportunities is None:
            continue
        lines.append("Expected:")
        if category.expected_team_opportunities is not None:
            lines.append(f"  {category.expected_team_opportunities:.1f} team {category.name} volume")
        if category.expected_share is not None:
            lines.append(f"  {category.expected_share * 100:.1f}% share")
        lines.append(f"  {category.expected_opportunities:.1f} expected opportunities")

    lines.append(f"\nRole: pos_rank={breakdown.role_confidence}")
    if breakdown.career_talent_prior:
        first_talent = next(iter(breakdown.career_talent_prior.values()))
        lines.append(f"Career talent evidence weight: {first_talent.career_evidence_weight:.2f}")
    lines.append(f"QB change: {'yes' if breakdown.qb_context.qb_changed else 'no'}")
    lines.append(f"Confidence: {breakdown.role_confidence}")

    if breakdown.projection_conflict and breakdown.conflict_reason:
        lines.append(f"\nConflict: {breakdown.conflict_reason}")

    return "\n".join(lines)
