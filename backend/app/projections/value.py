from app.projections.models import PlayerProjection

FIXED_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


def compute_value_over_replacement(
    projections: list[PlayerProjection], roster_positions: list[str], num_teams: int
) -> dict[str, float]:
    slots_per_team: dict[str, int] = {}
    for slot in roster_positions:
        if slot in FIXED_POSITIONS:
            slots_per_team[slot] = slots_per_team.get(slot, 0) + 1

    by_position: dict[str, list[PlayerProjection]] = {}
    for projection in projections:
        by_position.setdefault(projection.position, []).append(projection)

    replacement_level: dict[str, float] = {}
    for position, players in by_position.items():
        ranked = sorted(players, key=lambda p: p.projected_points, reverse=True)
        replacement_rank = slots_per_team.get(position, 0) * num_teams
        if replacement_rank == 0 or replacement_rank > len(ranked):
            replacement_level[position] = 0.0
        else:
            replacement_level[position] = ranked[replacement_rank - 1].projected_points

    return {
        p.platform_player_id: p.projected_points - replacement_level.get(p.position, 0.0)
        for p in projections
    }
