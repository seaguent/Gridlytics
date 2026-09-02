import pandas as pd
import pytest

from app.projections.context_aware.team_prior import (
    TeamSeason,
    build_team_seasons_for_prediction,
    compute_team_prior,
    compute_team_prior_by_team,
    real_team_seasons,
    team_weight,
)


def _team_season(season, offset, games=17, pass_attempts=None, rush_attempts=None):
    return TeamSeason(
        team="MIN", season=season, season_offset=offset, games=games,
        pass_attempts_per_game=pass_attempts, rush_attempts_per_game=rush_attempts,
    )


def test_team_weight_most_recent_season_weighs_more_than_older():
    most_recent = team_weight(season_offset=0, games_played=17)
    older = team_weight(season_offset=1, games_played=17)
    assert most_recent > older


def test_team_weight_zero_games_is_zero_weight():
    assert team_weight(season_offset=0, games_played=0) == pytest.approx(0.0)


def test_team_weight_short_season_weighs_less_than_full_season():
    short = team_weight(season_offset=0, games_played=4)
    full = team_weight(season_offset=0, games_played=17)
    assert short < full


def test_compute_team_prior_no_seasons_is_fully_unknown():
    result = compute_team_prior([])
    assert result.pass_attempts_per_game is None
    assert result.rush_attempts_per_game is None
    assert result.seasons_used == 0


def test_compute_team_prior_single_season_is_that_seasons_value():
    seasons = [_team_season(2025, 0, pass_attempts=28.47, rush_attempts=24.0)]
    result = compute_team_prior(seasons)
    assert result.pass_attempts_per_game == pytest.approx(28.47)
    assert result.rush_attempts_per_game == pytest.approx(24.0)
    assert result.seasons_used == 1


def test_compute_team_prior_multi_season_weights_recent_more_but_includes_older():
    seasons = [
        _team_season(2025, 0, pass_attempts=28.0),
        _team_season(2024, 1, pass_attempts=36.0),
    ]
    result = compute_team_prior(seasons)
    w0 = team_weight(0, 17)
    w1 = team_weight(1, 17)
    expected = (w0 * 28.0 + w1 * 36.0) / (w0 + w1)
    assert result.pass_attempts_per_game == pytest.approx(expected)
    # Real check: the older, higher season must pull the estimate up from the single-season
    # baseline (28.0) -- proving multi-year evidence is genuinely used, not ignored.
    assert result.pass_attempts_per_game > 28.0


def test_compute_team_prior_missing_value_in_one_season_ignored_not_treated_as_zero():
    seasons = [
        _team_season(2025, 0, pass_attempts=28.0, rush_attempts=None),
        _team_season(2024, 1, pass_attempts=None, rush_attempts=25.0),
    ]
    result = compute_team_prior(seasons)
    assert result.pass_attempts_per_game == pytest.approx(28.0)  # only real value, not averaged with 0
    assert result.rush_attempts_per_game == pytest.approx(25.0)


def _weekly_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_real_team_seasons_computes_real_per_game_averages_from_weekly_rows():
    weekly_2024 = _weekly_df([
        {"team": "MIN", "week": 1, "season_type": "REG", "attempts": 30, "carries": 20},
        {"team": "MIN", "week": 2, "season_type": "REG", "attempts": 40, "carries": 30},
    ])
    result = real_team_seasons({2024: weekly_2024})
    season = result[("MIN", 2024)]
    assert season.pass_attempts_per_game == pytest.approx(35.0)
    assert season.rush_attempts_per_game == pytest.approx(25.0)
    assert season.games == 2
    assert season.season_offset == 0


def test_real_team_seasons_excludes_post_season_rows():
    weekly = _weekly_df([
        {"team": "MIN", "week": 1, "season_type": "REG", "attempts": 30, "carries": 20},
        {"team": "MIN", "week": 19, "season_type": "POST", "attempts": 999, "carries": 999},
    ])
    result = real_team_seasons({2024: weekly})
    assert result[("MIN", 2024)].pass_attempts_per_game == pytest.approx(30.0)


def test_real_team_seasons_keeps_teams_separate():
    weekly = _weekly_df([
        {"team": "MIN", "week": 1, "season_type": "REG", "attempts": 30, "carries": 20},
        {"team": "KC", "week": 1, "season_type": "REG", "attempts": 40, "carries": 25},
    ])
    result = real_team_seasons({2024: weekly})
    assert result[("MIN", 2024)].pass_attempts_per_game == pytest.approx(30.0)
    assert result[("KC", 2024)].pass_attempts_per_game == pytest.approx(40.0)


def test_build_team_seasons_for_prediction_excludes_target_season_and_assigns_offsets():
    all_seasons = {
        ("MIN", 2025): TeamSeason(team="MIN", season=2025, season_offset=0, games=17,
                                   pass_attempts_per_game=99.0, rush_attempts_per_game=99.0),
        ("MIN", 2024): TeamSeason(team="MIN", season=2024, season_offset=0, games=17,
                                   pass_attempts_per_game=36.0, rush_attempts_per_game=24.0),
        ("MIN", 2023): TeamSeason(team="MIN", season=2023, season_offset=0, games=17,
                                   pass_attempts_per_game=34.0, rush_attempts_per_game=23.0),
    }
    result = build_team_seasons_for_prediction(all_seasons, "MIN", target_season=2025, lookback=4)
    assert [s.season for s in result] == [2024, 2023]  # 2025 itself never included -- leak-safe
    assert [s.season_offset for s in result] == [0, 1]  # most recent real prior season -> offset 0


def test_build_team_seasons_for_prediction_respects_lookback_window():
    all_seasons = {
        ("MIN", 2024): TeamSeason(team="MIN", season=2024, season_offset=0, games=17,
                                   pass_attempts_per_game=36.0, rush_attempts_per_game=24.0),
        ("MIN", 2018): TeamSeason(team="MIN", season=2018, season_offset=0, games=17,
                                   pass_attempts_per_game=30.0, rush_attempts_per_game=20.0),
    }
    result = build_team_seasons_for_prediction(all_seasons, "MIN", target_season=2025, lookback=2)
    assert [s.season for s in result] == [2024]  # 2018 falls outside the 2-season lookback window


def test_compute_team_prior_by_team_returns_one_prior_per_team_with_real_history():
    weekly_2024 = _weekly_df([
        {"team": "MIN", "week": 1, "season_type": "REG", "attempts": 30, "carries": 20},
        {"team": "KC", "week": 1, "season_type": "REG", "attempts": 40, "carries": 25},
    ])
    result = compute_team_prior_by_team({2024: weekly_2024}, target_season=2025, lookback=4, decay=0.55)
    assert result["MIN"].pass_attempts_per_game == pytest.approx(30.0)
    assert result["KC"].pass_attempts_per_game == pytest.approx(40.0)


def test_compute_team_prior_by_team_never_includes_the_target_season_itself():
    # A real leak-safety regression: if 2025's own weekly data is present in the same multi-year
    # frame, predicting 2025 must never use 2025's own real values.
    weekly = {
        2025: _weekly_df([{"team": "MIN", "week": 1, "season_type": "REG", "attempts": 999, "carries": 999}]),
        2024: _weekly_df([{"team": "MIN", "week": 1, "season_type": "REG", "attempts": 30, "carries": 20}]),
    }
    result = compute_team_prior_by_team(weekly, target_season=2025, lookback=4, decay=0.55)
    assert result["MIN"].pass_attempts_per_game == pytest.approx(30.0)
