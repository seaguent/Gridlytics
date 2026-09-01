from app.sleeper.scoring import detect_custom_scoring

STANDARD_HALF_PPR = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -1.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rec": 0.5,
    "rec_yd": 0.1,
    "rec_td": 6.0,
}


def test_real_sean_league_scoring_is_not_flagged_as_custom():
    # Sean's actual Sunday Funday scoring_settings, pulled live from Sleeper.
    real_scoring = {
        "pass_yd": 0.04, "pass_td": 4.0, "pass_int": -1.0, "rush_yd": 0.1, "rush_td": 6.0,
        "rec": 0.5, "rec_yd": 0.1, "rec_td": 6.0, "rec_2pt": 2.0, "rush_2pt": 2.0, "pass_2pt": 2.0,
        "fum": -1.0, "fum_lost": -2.0,
    }
    is_custom, reasons = detect_custom_scoring(real_scoring)
    assert is_custom is False
    assert reasons == []


def test_standard_half_ppr_is_not_flagged_as_custom():
    is_custom, reasons = detect_custom_scoring(STANDARD_HALF_PPR)
    assert is_custom is False


def test_bonus_scoring_is_flagged_as_custom():
    scoring = {**STANDARD_HALF_PPR, "bonus_rec_te": 0.5}
    is_custom, reasons = detect_custom_scoring(scoring)
    assert is_custom is True
    assert any("bonus_rec_te" in r for r in reasons)


def test_zero_valued_bonus_key_is_not_flagged():
    # Sleeper includes many bonus_* keys at 0 by default even in standard leagues -- only nonzero counts.
    scoring = {**STANDARD_HALF_PPR, "bonus_rush_yd_100": 0}
    is_custom, reasons = detect_custom_scoring(scoring)
    assert is_custom is False


def test_six_point_passing_tds_is_flagged_as_custom():
    scoring = {**STANDARD_HALF_PPR, "pass_td": 6.0}
    is_custom, reasons = detect_custom_scoring(scoring)
    assert is_custom is True
    assert any("pass_td" in r for r in reasons)


def test_unusual_yardage_rate_is_flagged_as_custom():
    scoring = {**STANDARD_HALF_PPR, "rec_yd": 0.2}
    is_custom, reasons = detect_custom_scoring(scoring)
    assert is_custom is True
    assert any("rec_yd" in r for r in reasons)
