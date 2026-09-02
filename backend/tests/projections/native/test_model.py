import pandas as pd
import pytest

from app.projections.native.model import (
    compute_all_position_priors,
    project_player_points,
    project_player_points_detailed,
)
from app.projections.scoring_rules import STANDARD_PPR, ScoringRules


def _wr_game(targets, receiving_yards, receiving_tds, receptions):
    return {"targets": targets, "receiving_yards": receiving_yards, "receiving_tds": receiving_tds, "receptions": receptions}


def test_unknown_position_returns_none():
    assert project_player_points("DEF", [], None, {}) is None


def test_no_history_and_no_priors_returns_zero_for_that_category():
    # Position priors present but empty (no opportunity/rate data at all) -> nothing to project.
    result = project_player_points("WR", [], None, {"receiving": {"opportunity": None}})
    assert result == pytest.approx(0.0)


def test_rookie_with_no_history_falls_back_entirely_to_position_priors():
    priors = {
        "receiving": {
            "opportunity": 5.0,
            "yards_per_target": 8.0,
            "td_rate": 0.05,
            "reception_rate": 0.6,
        }
    }
    result = project_player_points("WR", [], None, priors)
    # 5.0 targets * (8.0*0.1 + 0.05*6.0 + 0.6*1.0) = 5.0 * (0.8 + 0.3 + 0.6) = 5.0 * 1.7 = 8.5
    assert result == pytest.approx(8.5)


def test_established_player_blends_own_rate_into_position_prior():
    # 8 real games (full confidence) with a personal rate well above the position average.
    games = [_wr_game(10, 100, 1, 7) for _ in range(8)]  # yards_per_target=10.0, td_rate=0.1, reception_rate=0.7
    priors = {
        "receiving": {
            "opportunity": 5.0,  # irrelevant here -- real history drives expected volume instead
            "yards_per_target": 8.0,
            "td_rate": 0.05,
            "reception_rate": 0.6,
        }
    }
    result = project_player_points("WR", games, None, priors)
    # expected_opportunities: project_expected_volume([10]*8, None) -- season/recent avg both 10.0
    # efficiency (8 games, weight=1.0, fully own rate): yards_per_target=10.0, td_rate=0.1, reception_rate=0.7
    # points = 10.0 * (10.0*0.1 + 0.1*6.0 + 0.7*1.0) = 10.0 * (1.0 + 0.6 + 0.7) = 10.0 * 2.3 = 23.0
    assert result == pytest.approx(23.0)


def test_use_player_efficiency_false_forces_naive_position_average_baseline():
    games = [_wr_game(10, 100, 1, 7) for _ in range(8)]  # a real, well-above-average personal rate
    priors = {
        "receiving": {"opportunity": 5.0, "yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}
    }
    result = project_player_points("WR", games, None, priors, use_player_efficiency=False)
    # expected_opportunities same as above (10.0), but efficiency always uses position average directly
    # points = 10.0 * (8.0*0.1 + 0.05*6.0 + 0.6*1.0) = 10.0 * (0.8 + 0.3 + 0.6) = 10.0 * 1.7 = 17.0
    assert result == pytest.approx(17.0)


def test_week_one_veteran_blends_prior_season_efficiency_before_any_current_games():
    # No current-season games yet (Week 1), but a real, consistent prior-season track record.
    # targets=10, receiving_yards=120, receiving_tds=1, receptions=8 -> yards_per_target=12.0,
    # td_rate=0.1, reception_rate=0.8 -- deliberately chosen to stay under each rate's 3x outlier
    # cap (position averages 8.0/0.05/0.6 -> caps 24.0/0.15/1.8) so the arithmetic below is exact.
    prior_games = [_wr_game(10, 120, 1, 8) for _ in range(8)]
    priors = {
        "receiving": {"opportunity": 5.0, "yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}
    }
    result = project_player_points("WR", [], prior_games, priors)
    # expected_opportunities: project_expected_volume([], [10]*8) -> prior avg=10.0, no current -> 10.0
    # blend_weight = prior_season_weight(0) = 1.0 (0 current games played)
    # current_shrunk (0 current games) = position average for each rate (no blend needed, this factor
    #   is multiplied by (1 - blend_weight) = 0 below, but must still resolve without erroring)
    # prior_shrunk (8 prior games, full confidence, no team change) = fully the prior rate (12.0, 0.1, 0.8)
    # shrunk_rate = 1.0*prior_shrunk + 0.0*current_shrunk = prior_shrunk exactly
    # points = 10.0 * (12.0*0.1 + 0.1*6.0 + 0.8*1.0) = 10.0 * (1.2 + 0.6 + 0.8) = 10.0 * 2.6 = 26.0
    assert result == pytest.approx(26.0)


def test_team_change_softly_discounts_but_does_not_erase_prior_season_efficiency():
    prior_games = [_wr_game(10, 120, 1, 8) for _ in range(8)]  # same prior rate as the test above
    priors = {
        "receiving": {"opportunity": 5.0, "yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}
    }
    result = project_player_points("WR", [], prior_games, priors, team_changed=True)
    # expected_opportunities: project_expected_volume([], [10]*8, team_changed=True) -> volume-side
    #   handling is a HARD zero-out of the prior -> falls back to the position opportunity prior (5.0)
    # blend_weight = prior_season_weight(0) = 1.0
    # prior_shrunk now gets team_changed=True -> weight = 1.0 * 0.5 (TEAM_CHANGE_DISCOUNT) = 0.5
    #   yards_per_target: 0.5*12.0 + 0.5*8.0 = 10.0; td_rate: 0.5*0.1 + 0.5*0.05 = 0.075;
    #   reception_rate: 0.5*0.8 + 0.5*0.6 = 0.7 -- softly pulled toward the position average, not erased
    # shrunk_rate = blend_weight(1.0) * prior_shrunk = (10.0, 0.075, 0.7) exactly
    # points = 5.0 * (10.0*0.1 + 0.075*6.0 + 0.7*1.0) = 5.0 * (1.0 + 0.45 + 0.7) = 5.0 * 2.15 = 10.75
    assert result == pytest.approx(10.75)


def test_compute_all_position_priors_shape():
    df = pd.DataFrame(
        [
            {
                "position": "WR", "season": 2024, "week": 1, "season_type": "REG",
                "targets": 10, "receiving_yards": 100, "receiving_tds": 1, "receptions": 7,
                "carries": 0, "rushing_yards": 0, "rushing_tds": 0,
                "attempts": 0, "passing_yards": 0, "passing_tds": 0, "passing_interceptions": 0,
            }
        ]
    )
    result = compute_all_position_priors(df, season=2025, before_week=None)
    assert set(result.keys()) == {"QB", "RB", "WR", "TE"}
    assert result["WR"]["receiving"]["opportunity"] == pytest.approx(10.0)
    assert result["WR"]["receiving"]["yards_per_target"] == pytest.approx(10.0)
    # No real QB rows in the synthetic data -- QB's priors must be present but empty, not fabricated.
    assert result["QB"]["passing"]["opportunity"] is None


def test_detailed_breakdown_none_for_unknown_position():
    assert project_player_points_detailed("DEF", [], None, {}) is None


def test_detailed_breakdown_reports_expected_opportunities_and_prior_season_weight():
    # Same scenario as test_established_player_blends_own_rate_into_position_prior:
    # 8 real games, no prior season -- proves the breakdown's numbers match the
    # already-verified total from that test exactly.
    games = [_wr_game(10, 100, 1, 7) for _ in range(8)]
    priors = {
        "receiving": {"opportunity": 5.0, "yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}
    }
    breakdown = project_player_points_detailed("WR", games, None, priors)

    assert breakdown.total_points == pytest.approx(23.0)
    assert len(breakdown.categories) == 1
    category = breakdown.categories[0]
    assert category.name == "receiving"
    assert category.expected_opportunities == pytest.approx(10.0)
    assert category.prior_season_weight == pytest.approx(0.0)  # 8 games played this season -> fully current


def test_detailed_breakdown_exposes_shrunk_rates_per_rate_name():
    # 8 full-confidence games at fixed real rates (10 targets, 7 receptions, 100 yards, 1 TD
    # per game) -> observed rates should fully dominate the position prior with this much
    # volume, so shrunk_rates should read back approximately the player's own real rates.
    games = [_wr_game(10, 100, 1, 7) for _ in range(8)]
    priors = {
        "receiving": {"opportunity": 5.0, "yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}
    }
    breakdown = project_player_points_detailed("WR", games, None, priors)

    category = breakdown.categories[0]
    assert set(category.shrunk_rates.keys()) == {"yards_per_target", "td_rate", "reception_rate"}
    assert category.shrunk_rates["yards_per_target"] == pytest.approx(10.0, abs=0.5)
    assert category.shrunk_rates["td_rate"] == pytest.approx(0.1, abs=0.02)
    assert category.shrunk_rates["reception_rate"] == pytest.approx(0.7, abs=0.02)
    assert category.points == pytest.approx(23.0)


def test_project_player_points_matches_detailed_breakdown_total():
    # Regression check: the wrapper must always agree with the detailed function's total,
    # across a scenario that exercises the prior-season blend path.
    prior_games = [_wr_game(10, 120, 1, 8) for _ in range(8)]
    priors = {
        "receiving": {"opportunity": 5.0, "yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}
    }
    simple_result = project_player_points("WR", [], prior_games, priors)
    detailed_result = project_player_points_detailed("WR", [], prior_games, priors)
    assert simple_result == pytest.approx(detailed_result.total_points)


def test_default_scoring_rules_matches_standard_ppr_exactly():
    # No scoring_rules passed -- must produce byte-for-byte the same total as before this change,
    # proving the refactor is behavior-preserving for every existing caller (backtests included).
    games = [_wr_game(10, 100, 1, 7) for _ in range(8)]
    priors = {"receiving": {"opportunity": 5.0, "yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}}
    default_result = project_player_points("WR", games, None, priors)
    explicit_ppr_result = project_player_points("WR", games, None, priors, scoring_rules=STANDARD_PPR)
    assert default_result == pytest.approx(23.0)  # matches the pre-existing, already-verified total
    assert default_result == pytest.approx(explicit_ppr_result)


def test_half_ppr_scoring_rules_produce_a_genuinely_different_lower_total():
    games = [_wr_game(10, 100, 1, 7) for _ in range(8)]
    priors = {"receiving": {"opportunity": 5.0, "yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}}
    half_ppr = ScoringRules(reception_points=0.5)
    result = project_player_points("WR", games, None, priors, scoring_rules=half_ppr)
    # Full breakdown: expected_opportunities=10.0, yards_per_target=10.0 (own rate), td_rate=0.1,
    # reception_rate=0.7 (all own real rates, 8 games = full confidence).
    # points = 10.0 * (10.0*0.1 + 0.1*6.0 + 0.7*0.5) = 10.0 * (1.0 + 0.6 + 0.35) = 19.5
    assert result == pytest.approx(19.5)
    assert result < 23.0  # strictly less than the PPR total -- half-credit receptions must matter


def test_td_shrinkage_opportunities_omitted_matches_default_games_based_behavior():
    # No td_shrinkage_opportunities passed -- must reproduce the pre-existing total exactly,
    # proving every existing caller (production sync, prior backtests) is untouched.
    games = [_wr_game(10, 100, 1, 7) for _ in range(8)]
    priors = {"receiving": {"opportunity": 5.0, "yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}}
    result = project_player_points("WR", games, None, priors)
    assert result == pytest.approx(23.0)  # matches the pre-existing, already-verified total


def test_td_shrinkage_opportunities_pulls_a_noisy_low_sample_td_rate_toward_position_average():
    # A player with a real, extreme, low-opportunity TD outlier: 3 games, 30 total targets
    # (well above FULL_CONFIDENCE_GAMES=8's implicit games-based confidence), but zero TDs.
    # Under the OLD games-based shrinkage, 3 games = weight 3/8 = 0.375 toward his own (0.0) rate.
    # Under the new opportunity-based shrinkage with a high full_confidence_opportunities, 30
    # targets is still far from full confidence -- the player's real 0.0 TD rate should be
    # trusted LESS (pulled harder toward the position average) than the games-based path would.
    games = [
        {"targets": 10, "receiving_yards": 90, "receiving_tds": 0, "receptions": 7}
        for _ in range(3)
    ]
    priors = {"receiving": {"opportunity": 10.0, "yards_per_target": 9.0, "td_rate": 0.05, "reception_rate": 0.7}}

    games_based = project_player_points_detailed("WR", games, None, priors)
    opportunity_based = project_player_points_detailed(
        "WR", games, None, priors, td_shrinkage_opportunities={"receiving": 200.0},
    )

    games_based_td_component = games_based.categories[0].points
    opportunity_based_td_component = opportunity_based.categories[0].points
    # Both use the same real 0.0 observed TD rate, same expected_opportunities, same yards/reception
    # components -- the only difference is how much the td_rate=0.0 outlier gets trusted. Weaker
    # trust in a 0.0 outlier means MORE points survive (less of his real rate gets zeroed out).
    assert opportunity_based_td_component > games_based_td_component


def test_custom_interception_penalty_changes_qb_total():
    games = [
        {"attempts": 30, "passing_yards": 250, "passing_tds": 2, "passing_interceptions": 2,
         "carries": 0, "rushing_yards": 0, "rushing_tds": 0}
        for _ in range(8)
    ]
    priors = {"passing": {"opportunity": 30.0, "yards_per_attempt": 8.0, "td_rate": 0.05, "int_rate": 0.05}}
    standard_result = project_player_points("QB", games, None, priors)  # -2/INT default
    custom_rules = ScoringRules(pass_int_points=-1.0)  # a real league's softer INT penalty
    custom_result = project_player_points("QB", games, None, priors, scoring_rules=custom_rules)
    assert custom_result > standard_result  # a softer INT penalty must raise the total
