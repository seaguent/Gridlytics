import pytest

from app.projections.scoring_rules import (
    STANDARD_PPR,
    ScoringRules,
    scoring_rules_for_league,
    scoring_rules_from_espn,
    scoring_rules_from_sleeper,
)


def test_standard_ppr_defaults():
    assert STANDARD_PPR.reception_points == 1.0
    assert STANDARD_PPR.pass_int_points == -2.0
    assert STANDARD_PPR.pass_yard_points == pytest.approx(0.04)
    assert STANDARD_PPR.rush_yard_points == pytest.approx(0.1)
    assert STANDARD_PPR.rec_yard_points == pytest.approx(0.1)
    assert STANDARD_PPR.pass_td_points == 4.0
    assert STANDARD_PPR.rush_td_points == 6.0
    assert STANDARD_PPR.rec_td_points == 6.0


def test_scoring_rules_from_sleeper_reads_real_half_ppr_and_custom_int_settings():
    # Matches a real Sleeper league's scoring_settings shape exactly.
    settings = {"rec": 0.5, "pass_int": -1.0, "pass_yd": 0.04, "pass_td": 4.0, "rush_yd": 0.1, "rush_td": 6.0, "rec_yd": 0.1, "rec_td": 6.0}
    rules = scoring_rules_from_sleeper(settings)
    assert rules.reception_points == 0.5
    assert rules.pass_int_points == -1.0
    assert rules.pass_yard_points == pytest.approx(0.04)


def test_scoring_rules_from_sleeper_falls_back_to_standard_ppr_for_missing_keys():
    rules = scoring_rules_from_sleeper({})
    assert rules == STANDARD_PPR


def test_scoring_rules_from_sleeper_standard_scoring_no_ppr():
    settings = {"rec": 0.0}
    rules = scoring_rules_from_sleeper(settings)
    assert rules.reception_points == 0.0


def test_scoring_rules_from_sleeper_full_ppr():
    settings = {"rec": 1.0}
    rules = scoring_rules_from_sleeper(settings)
    assert rules.reception_points == 1.0


def test_same_stat_line_produces_different_points_under_different_league_settings():
    # 10 receptions, otherwise identical -- must produce genuinely different totals.
    def _reception_points(rules: ScoringRules, receptions: int) -> float:
        return receptions * rules.reception_points

    ppr = scoring_rules_from_sleeper({"rec": 1.0})
    half_ppr = scoring_rules_from_sleeper({"rec": 0.5})
    standard = scoring_rules_from_sleeper({"rec": 0.0})

    assert _reception_points(ppr, 10) == pytest.approx(10.0)
    assert _reception_points(half_ppr, 10) == pytest.approx(5.0)
    assert _reception_points(standard, 10) == pytest.approx(0.0)


def test_scoring_rules_from_espn_parses_real_verified_stat_ids():
    # statId mapping verified against a real, community-maintained ESPN API reference
    # (cwendt94/espn-api) -- 3=passingYards, 4=passingTouchdowns, 20=passingInterceptions,
    # 24=rushingYards, 25=rushingTouchdowns, 41=receivingReceptions, 42=receivingYards,
    # 43=receivingTouchdowns. Not yet confirmed against a live raw ESPN response.
    settings = {
        "scoring_items": [
            {"stat_id": 3, "points": 0.04},
            {"stat_id": 4, "points": 4.0},
            {"stat_id": 20, "points": -2.0},
            {"stat_id": 24, "points": 0.1},
            {"stat_id": 25, "points": 6.0},
            {"stat_id": 41, "points": 1.0},
            {"stat_id": 42, "points": 0.1},
            {"stat_id": 43, "points": 6.0},
        ]
    }
    rules = scoring_rules_from_espn(settings)
    assert rules.reception_points == 1.0
    assert rules.pass_int_points == -2.0
    assert rules.pass_yard_points == pytest.approx(0.04)


def test_scoring_rules_from_espn_missing_settings_falls_back_to_standard_ppr_explicitly():
    # This is the real, current state of every ESPN league in the DB today (scoring_settings={}).
    # Must fall back cleanly to standard PPR -- never silently guess or claim league-specific
    # accuracy it doesn't have.
    rules = scoring_rules_from_espn({})
    assert rules == STANDARD_PPR


def test_scoring_rules_from_espn_partial_settings_falls_back_per_missing_field_only():
    # Only reception scoring present -- everything else should still fall back to standard,
    # not zero out or break.
    settings = {"scoring_items": [{"stat_id": 41, "points": 0.5}]}
    rules = scoring_rules_from_espn(settings)
    assert rules.reception_points == 0.5
    assert rules.pass_td_points == STANDARD_PPR.pass_td_points


def test_scoring_rules_for_league_dispatches_by_platform():
    sleeper_rules = scoring_rules_for_league("sleeper", {"rec": 0.5})
    assert sleeper_rules.reception_points == 0.5

    espn_rules = scoring_rules_for_league("espn", {})
    assert espn_rules == STANDARD_PPR
