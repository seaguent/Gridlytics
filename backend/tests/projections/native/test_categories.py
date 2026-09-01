import pandas as pd
import pytest

from app.projections.native.categories import (
    POSITION_CATEGORIES,
    add_rate_columns,
    extract_player_rate_series,
)


def test_position_categories_cover_qb_rb_wr_te_only():
    assert set(POSITION_CATEGORIES.keys()) == {"QB", "RB", "WR", "TE"}


def test_qb_has_passing_and_rushing_categories():
    names = {category.name for category in POSITION_CATEGORIES["QB"]}
    assert names == {"passing", "rushing"}


def test_wr_and_te_share_the_same_receiving_category_definition():
    assert POSITION_CATEGORIES["WR"] == POSITION_CATEGORIES["TE"]


def test_add_rate_columns_derives_per_opportunity_ratios():
    receiving = next(c for c in POSITION_CATEGORIES["WR"] if c.name == "receiving")
    df = pd.DataFrame(
        [
            {"targets": 10, "receiving_yards": 100, "receiving_tds": 1, "receptions": 7},
            {"targets": 0, "receiving_yards": 0, "receiving_tds": 0, "receptions": 0},  # no opportunities
        ]
    )
    result = add_rate_columns(df, receiving)
    assert len(result) == 1  # the zero-target row must be excluded, not divide-by-zero'd
    assert result.iloc[0]["yards_per_target"] == pytest.approx(10.0)
    assert result.iloc[0]["td_rate"] == pytest.approx(0.1)
    assert result.iloc[0]["reception_rate"] == pytest.approx(0.7)


def test_extract_player_rate_series_skips_zero_opportunity_games():
    receiving = next(c for c in POSITION_CATEGORIES["WR"] if c.name == "receiving")
    games = [
        {"targets": 10, "receiving_yards": 100},
        {"targets": 0, "receiving_yards": 0},
    ]
    result = extract_player_rate_series(games, receiving, "yards_per_target")
    assert result == [10.0]
