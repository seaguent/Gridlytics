import pandas as pd
import pytest

from app.projections.context_aware.team_context import compute_team_tendencies


def _row(team, season, week, attempts, carries, season_type="REG"):
    return {"team": team, "season": season, "week": week, "season_type": season_type, "attempts": attempts, "carries": carries}


def test_team_tendencies_derives_rates_and_plays_per_game():
    from app.projections.context_aware.team_context import TeamTendencies
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    assert tendencies.plays_per_game == pytest.approx(60.0)
    assert tendencies.pass_rate == pytest.approx(35.0 / 60.0)
    assert tendencies.rush_rate == pytest.approx(25.0 / 60.0)


def test_team_tendencies_derived_fields_are_none_when_either_input_is_none():
    from app.projections.context_aware.team_context import TeamTendencies
    tendencies = TeamTendencies(pass_attempts_per_game=None, rush_attempts_per_game=25.0)
    assert tendencies.plays_per_game is None
    assert tendencies.pass_rate is None
    assert tendencies.rush_rate is None


def test_prior_season_only_when_no_current_season_games():
    rows = [_row("SF", 2024, w, 30, 25) for w in range(1, 4)]
    result = compute_team_tendencies(pd.DataFrame(rows), season=2025, before_week=1)
    assert result["SF"].pass_attempts_per_game == pytest.approx(30.0)
    assert result["SF"].rush_attempts_per_game == pytest.approx(25.0)


def test_blends_prior_and_current_season_by_team_games_observed():
    rows = [_row("SF", 2024, w, 30, 25) for w in range(1, 4)]
    rows += [_row("SF", 2025, w, 40, 20) for w in range(1, 3)]  # 2 real current-season games
    result = compute_team_tendencies(pd.DataFrame(rows), season=2025, before_week=3)
    # prior_season_weight(2) = 1 - 2/8 = 0.75 -> mostly prior still
    expected_pass = 0.75 * 30.0 + 0.25 * 40.0
    assert result["SF"].pass_attempts_per_game == pytest.approx(expected_pass)


def test_full_current_season_ignores_prior():
    rows = [_row("SF", 2024, w, 30, 25) for w in range(1, 4)]
    rows += [_row("SF", 2025, w, 40, 20) for w in range(1, 9)]  # 8 real current-season games
    result = compute_team_tendencies(pd.DataFrame(rows), season=2025, before_week=9)
    assert result["SF"].pass_attempts_per_game == pytest.approx(40.0)


def test_excludes_non_regular_season_games():
    rows = [_row("SF", 2024, w, 30, 25) for w in range(1, 4)]
    rows.append(_row("SF", 2024, 19, 999, 999, season_type="POST"))
    result = compute_team_tendencies(pd.DataFrame(rows), season=2025, before_week=1)
    assert result["SF"].pass_attempts_per_game == pytest.approx(30.0)


def test_leakage_future_weeks_never_affect_an_earlier_cutoff():
    rows = [_row("SF", 2024, w, 30, 25) for w in range(1, 4)]
    rows += [_row("SF", 2025, w, 40, 20) for w in range(1, 4)]
    df = pd.DataFrame(rows)
    before = compute_team_tendencies(df, season=2025, before_week=2)

    df_mutated = df.copy()
    df_mutated.loc[(df_mutated["season"] == 2025) & (df_mutated["week"] == 3), "attempts"] = 99999
    after = compute_team_tendencies(df_mutated, season=2025, before_week=2)

    assert before["SF"] == after["SF"]


def _row2(team, season, week, attempts, carries, season_type="REG"):
    return {"team": team, "season": season, "week": week, "season_type": season_type, "attempts": attempts, "carries": carries}


def test_compute_team_tendencies_v2_uses_multi_year_prior_when_no_current_season_games():
    from app.projections.context_aware.team_context import compute_team_tendencies_v2
    from app.projections.context_aware.team_prior import TeamPrior

    multi_year_prior_by_team = {"MIN": TeamPrior(pass_attempts_per_game=31.70, rush_attempts_per_game=24.0, seasons_used=4)}
    empty_weekly = pd.DataFrame(columns=["team", "season", "week", "season_type", "attempts", "carries"])
    result = compute_team_tendencies_v2(empty_weekly, multi_year_prior_by_team, season=2026, before_week=1)
    # Zero real 2026 games -> fully the multi-year prior, not any single season's raw value.
    assert result["MIN"].pass_attempts_per_game == pytest.approx(31.70)
    assert result["MIN"].rush_attempts_per_game == pytest.approx(24.0)


def test_compute_team_tendencies_v2_blends_toward_current_season_by_games_observed():
    from app.projections.context_aware.team_context import compute_team_tendencies_v2
    from app.projections.context_aware.team_prior import TeamPrior

    multi_year_prior_by_team = {"MIN": TeamPrior(pass_attempts_per_game=30.0, rush_attempts_per_game=None, seasons_used=4)}
    rows = [_row2("MIN", 2026, w, 40, 20) for w in range(1, 9)]  # 8 real current-season games, all at 40
    result = compute_team_tendencies_v2(pd.DataFrame(rows), multi_year_prior_by_team, season=2026, before_week=9)
    # 8 real games -> prior_season_weight(8) == 0 -> fully current-season, ignoring the multi-year prior
    assert result["MIN"].pass_attempts_per_game == pytest.approx(40.0)


def test_compute_team_tendencies_v2_missing_multi_year_prior_falls_back_to_current_only():
    from app.projections.context_aware.team_context import compute_team_tendencies_v2

    rows = [_row2("SF", 2026, w, 35, 22) for w in range(1, 3)]
    result = compute_team_tendencies_v2(pd.DataFrame(rows), {}, season=2026, before_week=3)
    assert result["SF"].pass_attempts_per_game is not None  # real current-season data alone still resolves


def test_compute_team_tendencies_v2_leakage_future_weeks_never_affect_earlier_cutoff():
    from app.projections.context_aware.team_context import compute_team_tendencies_v2
    from app.projections.context_aware.team_prior import TeamPrior

    multi_year_prior_by_team = {"SF": TeamPrior(pass_attempts_per_game=30.0, rush_attempts_per_game=25.0, seasons_used=4)}
    rows = [_row2("SF", 2026, w, 30, 25) for w in range(1, 4)]
    df = pd.DataFrame(rows)
    before = compute_team_tendencies_v2(df, multi_year_prior_by_team, season=2026, before_week=2)

    mutated = df.copy()
    mutated.loc[mutated["week"] == 3, "attempts"] = 99999
    after = compute_team_tendencies_v2(mutated, multi_year_prior_by_team, season=2026, before_week=2)
    assert before["SF"] == after["SF"]
