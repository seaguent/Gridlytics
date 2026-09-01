import re

import pandas as pd

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Escape hatch for confirmed-wrong automated matches, keyed by Sleeper platform_player_id -> gsis_id.
MANUAL_SLEEPER_OVERRIDES: dict[str, str] = {}

# Sleeper reports "LAR" for the Rams; nflverse (and our ESPN parser) use "LA".
TEAM_ALIASES = {"LAR": "LA"}


def normalize_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", "", name.lower())
    parts = [part for part in cleaned.split() if part not in SUFFIXES]
    return " ".join(parts)


def normalize_team(team: str | None) -> str | None:
    if not team:
        return None
    team = team.upper()
    return TEAM_ALIASES.get(team, team)


def build_espn_lookup(crosswalk: pd.DataFrame) -> dict[str, str]:
    lookup = {}
    for _, row in crosswalk.iterrows():
        espn_id = row.get("espn_id")
        gsis_id = row.get("gsis_id")
        if pd.isna(espn_id) or pd.isna(gsis_id):
            continue
        lookup[str(int(espn_id))] = gsis_id
    return lookup


def build_sleeper_lookup(dp_crosswalk: pd.DataFrame) -> dict[str, str]:
    lookup = {}
    for _, row in dp_crosswalk.iterrows():
        sleeper_id = row.get("sleeper_id")
        gsis_id = row.get("gsis_id")
        if pd.isna(sleeper_id) or pd.isna(gsis_id):
            continue
        lookup[str(int(sleeper_id))] = gsis_id
    return lookup


def build_pfr_lookup(crosswalk: pd.DataFrame) -> dict[str, str]:
    lookup = {}
    for _, row in crosswalk.iterrows():
        pfr_id = row.get("pfr_id")
        gsis_id = row.get("gsis_id")
        if pd.isna(pfr_id) or pd.isna(gsis_id):
            continue
        lookup[pfr_id] = gsis_id
    return lookup


def build_name_position_lookup(crosswalk: pd.DataFrame) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    ambiguous: set[tuple[str, str]] = set()

    for _, row in crosswalk.iterrows():
        display_name = row.get("display_name")
        gsis_id = row.get("gsis_id")
        position = row.get("position")
        if pd.isna(display_name) or pd.isna(gsis_id) or pd.isna(position):
            continue

        key = (normalize_name(display_name), str(position).upper())
        existing = lookup.get(key)
        if existing is not None and existing != gsis_id:
            ambiguous.add(key)
        else:
            lookup[key] = gsis_id

    # A silent wrong match is worse than no match, so drop ambiguous name+position collisions.
    for key in ambiguous:
        lookup.pop(key, None)
    return lookup
