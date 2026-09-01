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

    # RB takes rb1 (20); FLEX then picks wr1 (18) over rb2 (15), the best remaining eligible player.
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


def test_bench_and_ir_slots_are_ignored_not_filled():
    players = [
        {"player_id": "qb1", "position": "QB", "points": 20},
        {"player_id": "rb1", "position": "RB", "points": 15},
        {"player_id": "rb2", "position": "RB", "points": 10},
    ]
    # BN/IR are real slot strings both platforms emit, but they're not scoring slots.
    slots = ["QB", "RB", "BN", "BN", "IR"]

    assignment, total = find_optimal_lineup(players, slots)

    slot_names = [slot for slot, _ in assignment]
    assert "BN" not in slot_names
    assert "IR" not in slot_names
    assert total == 20 + 15


def test_real_sleeper_roster_shape_fills_correctly():
    # Sean's actual Sunday Funday roster_positions from the DB.
    slots = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF", "BN", "BN", "BN", "BN", "BN", "BN"]
    players = [
        {"player_id": "qb1", "position": "QB", "points": 22},
        {"player_id": "rb1", "position": "RB", "points": 18},
        {"player_id": "rb2", "position": "RB", "points": 14},
        {"player_id": "wr1", "position": "WR", "points": 16},
        {"player_id": "wr2", "position": "WR", "points": 12},
        {"player_id": "te1", "position": "TE", "points": 9},
        {"player_id": "rb3", "position": "RB", "points": 11},
        {"player_id": "wr3", "position": "WR", "points": 10},
        {"player_id": "k1", "position": "K", "points": 8},
        {"player_id": "def1", "position": "DEF", "points": 7},
    ]

    assignment, total = find_optimal_lineup(players, slots)

    filled_slots = {slot for slot, _ in assignment}
    assert filled_slots == {"QB", "RB", "WR", "TE", "FLEX", "K", "DEF"}
    # Both FLEX slots should be filled by the best remaining RB/WR/TE (rb3=11, wr3=10), not left empty.
    flex_players = {pid for slot, pid in assignment if slot == "FLEX"}
    assert flex_players == {"rb3", "wr3"}
    assert total == 22 + 18 + 14 + 16 + 12 + 9 + 11 + 10 + 8 + 7


def test_real_espn_roster_shape_fills_correctly():
    # Sean's actual ESPN Harrisburg League roster_positions from the DB.
    slots = ["QB", "RB", "RB", "WR", "WR", "TE", "DEF", "K", "BN", "BN", "BN", "BN", "BN", "BN", "IR", "IR", "FLEX", "FLEX"]
    players = [
        {"player_id": "qb1", "position": "QB", "points": 20},
        {"player_id": "rb1", "position": "RB", "points": 15},
        {"player_id": "rb2", "position": "RB", "points": 12},
        {"player_id": "wr1", "position": "WR", "points": 14},
        {"player_id": "wr2", "position": "WR", "points": 10},
        {"player_id": "te1", "position": "TE", "points": 8},
        {"player_id": "def1", "position": "DEF", "points": 6},
        {"player_id": "k1", "position": "K", "points": 5},
    ]

    assignment, total = find_optimal_lineup(players, slots)

    filled_slots = {slot for slot, _ in assignment}
    assert filled_slots == {"QB", "RB", "WR", "TE", "DEF", "K"}
    # Only 8 real players for 8 real starting slots -- both FLEX spots go unfilled, not crash.
    assert total == 20 + 15 + 12 + 14 + 10 + 8 + 6 + 5


def test_slot_left_unfilled_when_no_eligible_player_remains():
    players = [{"player_id": "wr1", "position": "WR", "points": 12}]
    slots = ["QB", "WR"]

    assignment, total = find_optimal_lineup(players, slots)

    slot_names = [slot for slot, _ in assignment]
    assert "QB" not in slot_names
    assert ("WR", "wr1") in assignment
    assert total == 12
