import pytest

from app.projections.blending import prior_season_weight


def test_prior_season_weight_decays_by_games_played_not_calendar_weeks():
    assert prior_season_weight(0) == 1.0
    assert prior_season_weight(4) == pytest.approx(0.5)
    assert prior_season_weight(8) == 0.0
    assert prior_season_weight(12) == 0.0
