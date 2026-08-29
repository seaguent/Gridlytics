from app.analytics.lineup import find_optimal_lineup


def test_fixed_slots_pick_best_player_at_each_position():
    players = [
        {"player_id": "qb1", "position": "QB", "points": 20},
        {"player_id": "rb1", "position": "RB", "points": 15},
        {"player_id": "rb2", "position": "RB", "points": 10},
    ]
    slots = ["QB", "RB"]

    assignment, total = find_optimal_lineup(players, slots)

    assert total == 35
    assert ("QB", "qb1") in assignment
    assert ("RB", "rb1") in assignment


def test_duplicate_slot_types_both_get_filled_with_distinct_players():
    players = [
        {"player_id": "rb1", "position": "RB", "points": 20},
        {"player_id": "rb2", "position": "RB", "points": 15},
        {"player_id": "rb3", "position": "RB", "points": 5},
    ]
    slots = ["RB", "RB"]

    assignment, total = find_optimal_lineup(players, slots)

    assigned_players = [player_id for _, player_id in assignment]
    assert len(assignment) == 2
    assert set(assigned_players) == {"rb1", "rb2"}
    assert total == 35


def test_flex_picks_best_remaining_regardless_of_position():
    players = [
        {"player_id": "rb1", "position": "RB", "points": 20},
        {"player_id": "rb2", "position": "RB", "points": 15},
        {"player_id": "wr1", "position": "WR", "points": 18},
    ]
    slots = ["RB", "FLEX"]

    assignment, total = find_optimal_lineup(players, slots)

    # RB slot takes the best RB (rb1=20); FLEX then picks the best remaining
    # ELIGIBLE player: wr1 (18) beats rb2 (15), even though rb2 is a "pure" RB.
    assert ("RB", "rb1") in assignment
    assert ("FLEX", "wr1") in assignment
    assert total == 38


def test_qb_is_ineligible_for_flex():
    players = [
        {"player_id": "qb1", "position": "QB", "points": 50},
        {"player_id": "rb1", "position": "RB", "points": 10},
    ]
    slots = ["FLEX"]

    assignment, total = find_optimal_lineup(players, slots)

    # QB scores far more, but FLEX can't legally use a QB.
    assert ("FLEX", "rb1") in assignment
    assert total == 10


def test_super_flex_can_use_a_qb_flex_cannot():
    players = [
        {"player_id": "rb1", "position": "RB", "points": 30},
        {"player_id": "rb2", "position": "RB", "points": 25},
        {"player_id": "wr1", "position": "WR", "points": 10},
        {"player_id": "qb1", "position": "QB", "points": 28},
    ]
    slots = ["RB", "FLEX", "SUPER_FLEX"]

    assignment, total = find_optimal_lineup(players, slots)

    assert ("RB", "rb1") in assignment
    assert ("FLEX", "rb2") in assignment
    assert ("SUPER_FLEX", "qb1") in assignment
    assert total == 30 + 25 + 28


def test_slot_left_unfilled_when_no_eligible_player_remains():
    players = [{"player_id": "wr1", "position": "WR", "points": 12}]
    slots = ["QB", "WR"]

    assignment, total = find_optimal_lineup(players, slots)

    slot_names = [slot for slot, _ in assignment]
    assert "QB" not in slot_names
    assert ("WR", "wr1") in assignment
    assert total == 12
