SLOT_ELIGIBILITY = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "DEF": {"DEF"},
    "K": {"K"},
    "FLEX": {"RB", "WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}


def find_optimal_lineup(players: list[dict], slots: list[str]) -> tuple[list[tuple[str, str]], float]:
    eligible_slots = [slot for slot in slots if slot in SLOT_ELIGIBILITY]
    eligible_slots.sort(key=lambda slot: len(SLOT_ELIGIBILITY[slot]))

    available = list(players)
    assignment: list[tuple[str, str]] = []
    total_points = 0.0

    for slot in eligible_slots:
        eligible_positions = SLOT_ELIGIBILITY[slot]
        candidates = [p for p in available if p["position"] in eligible_positions]
        if not candidates:
            continue

        best = max(candidates, key=lambda p: p["points"])
        assignment.append((slot, best["player_id"]))
        total_points += best["points"]
        available.remove(best)

    return assignment, total_points
