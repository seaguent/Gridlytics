import pandas as pd
import pytest

from scripts.run_career_prior_validation import build_career_seasons


def _season_row(gsis_id, season, games, targets, receiving_yards, receiving_tds, target_share, fantasy_points_ppr):
    return {
        "player_id": gsis_id, "season": season, "season_type": "REG", "recent_team": "MIN",
        "games": games, "targets": targets, "receptions": 0, "receiving_yards": receiving_yards,
        "receiving_tds": receiving_tds, "carries": 0, "rushing_yards": 0, "rushing_tds": 0,
        "attempts": 0, "passing_yards": 0, "passing_tds": 0,
        "target_share": target_share, "fantasy_points_ppr": fantasy_points_ppr,
    }


def test_build_career_seasons_never_includes_the_held_out_season_itself():
    # held_out_season=2025 -- only 2024/2023/... may appear, 2025's own real row must be excluded
    # even though it's present in the fetched data (mirrors this project's other leakage tests).
    season_stats_by_year = {
        2025: pd.DataFrame([_season_row("00-1", 2025, 17, 150, 1200, 8, 0.29, 250.0)]),
        2024: pd.DataFrame([_season_row("00-1", 2024, 17, 140, 1000, 5, 0.27, 210.0)]),
    }
    seasons = build_career_seasons(season_stats_by_year, gsis_id="00-1", held_out_season=2025)
    assert len(seasons) == 1
    assert seasons[0].season == 2024
    assert seasons[0].season_offset == 0  # most recent AVAILABLE season, not the held-out one


def test_build_career_seasons_assigns_offsets_in_order():
    season_stats_by_year = {
        2024: pd.DataFrame([_season_row("00-1", 2024, 17, 140, 1000, 5, 0.27, 210.0)]),
        2023: pd.DataFrame([_season_row("00-1", 2023, 16, 130, 950, 6, 0.26, 200.0)]),
        2022: pd.DataFrame([_season_row("00-1", 2022, 15, 100, 800, 4, 0.22, 170.0)]),
    }
    seasons = build_career_seasons(season_stats_by_year, gsis_id="00-1", held_out_season=2025)
    offsets_by_season = {s.season: s.season_offset for s in seasons}
    assert offsets_by_season == {2024: 0, 2023: 1, 2022: 2}
