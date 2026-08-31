import pytest

from app.projections.models import PlayerProjection
from app.projections.value import compute_value_over_replacement


def _proj(player_id: str, position: str, points: float) -> PlayerProjection:
    return PlayerProjection(player_id, f"Player {player_id}", position, points, ["test"])


def test_value_over_replacement_matches_hand_calculation():
    projections = [
        _proj("qb1", "QB", 25),
        _proj("qb2", "QB", 18),
        _proj("rb1", "RB", 20),
        _proj("rb2", "RB", 15),
        _proj("rb3", "RB", 10),
        _proj("rb4", "RB", 5),
    ]
    # 2 teams, roster has 1 QB slot and 2 RB slots (+ non-positional slots
    # that don't affect replacement level calculation).
    roster_positions = ["QB", "RB", "RB", "WR", "TE", "BN", "BN"]
    num_teams = 2

    vor = compute_value_over_replacement(projections, roster_positions, num_teams)

    # QB: 1 slot x 2 teams = 2 startable QBs -> replacement = QB2's 18 pts
    assert vor["qb1"] == pytest.approx(25 - 18)
    assert vor["qb2"] == pytest.approx(0.0)

    # RB: 2 slots x 2 teams = 4 startable RBs -> replacement = RB4's 5 pts
    assert vor["rb1"] == pytest.approx(20 - 5)
    assert vor["rb2"] == pytest.approx(15 - 5)
    assert vor["rb3"] == pytest.approx(10 - 5)
    assert vor["rb4"] == pytest.approx(0.0)


def test_value_over_replacement_handles_fewer_players_than_replacement_rank():
    # Only 1 TE exists but the league needs 2 -> replacement level is 0,
    # so the lone TE's full projection counts as their VOR.
    projections = [_proj("te1", "TE", 12)]
    roster_positions = ["TE", "TE", "BN"]
    num_teams = 1

    vor = compute_value_over_replacement(projections, roster_positions, num_teams)

    assert vor["te1"] == pytest.approx(12.0)
