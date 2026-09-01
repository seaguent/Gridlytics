import pandas as pd

from app.nflverse.crosswalk import (
    build_espn_lookup,
    build_name_position_lookup,
    build_pfr_lookup,
    build_sleeper_lookup,
    normalize_name,
    normalize_team,
)


def test_normalize_name_lowercases_and_strips_suffixes():
    assert normalize_name("Puka Nacua") == "puka nacua"
    assert normalize_name("Marvin Harrison Jr.") == "marvin harrison"
    assert normalize_name("Odell Beckham III") == "odell beckham"


def test_build_espn_lookup_maps_espn_id_to_gsis_id():
    crosswalk = pd.DataFrame(
        [
            {"espn_id": 4426515.0, "gsis_id": "00-0039075", "display_name": "Puka Nacua"},
            {"espn_id": float("nan"), "gsis_id": "00-0000001", "display_name": "No ESPN Id"},
        ]
    )
    lookup = build_espn_lookup(crosswalk)
    assert lookup == {"4426515": "00-0039075"}


def test_normalize_team_maps_sleeper_rams_alias():
    assert normalize_team("LAR") == "LA"
    assert normalize_team("kc") == "KC"
    assert normalize_team(None) is None


def test_build_pfr_lookup_maps_pfr_id_to_gsis_id():
    crosswalk = pd.DataFrame(
        [
            {"pfr_id": "NacuPu00", "gsis_id": "00-0039075"},
            {"pfr_id": float("nan"), "gsis_id": "00-0000001"},
        ]
    )
    lookup = build_pfr_lookup(crosswalk)
    assert lookup == {"NacuPu00": "00-0039075"}


def test_build_sleeper_lookup_maps_sleeper_id_to_gsis_id():
    dp_crosswalk = pd.DataFrame(
        [
            {"sleeper_id": 9493.0, "gsis_id": "00-0039075", "name": "Puka Nacua"},
            {"sleeper_id": float("nan"), "gsis_id": "00-0000001", "name": "No Sleeper Id"},
        ]
    )
    lookup = build_sleeper_lookup(dp_crosswalk)
    assert lookup == {"9493": "00-0039075"}


def test_build_name_position_lookup_maps_normalized_name_and_position_to_gsis_id():
    crosswalk = pd.DataFrame(
        [
            {"display_name": "Puka Nacua", "gsis_id": "00-0039075", "position": "WR"},
        ]
    )
    lookup = build_name_position_lookup(crosswalk)
    assert lookup == {("puka nacua", "WR"): "00-0039075"}


def test_build_name_position_lookup_drops_ambiguous_collisions():
    crosswalk = pd.DataFrame(
        [
            {"display_name": "Tony Brown", "gsis_id": "00-0002067", "position": "CB"},
            {"display_name": "Tony Brown", "gsis_id": "00-0034540", "position": "CB"},
            {"display_name": "Puka Nacua", "gsis_id": "00-0039075", "position": "WR"},
        ]
    )
    lookup = build_name_position_lookup(crosswalk)
    assert ("tony brown", "CB") not in lookup
    assert lookup[("puka nacua", "WR")] == "00-0039075"
