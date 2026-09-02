import pytest

from app.projections.context_aware.career_prior import CareerSeason, TALENT_STATS, _average_talent


def _season(season, offset, games, yards_per_target=None, catch_rate=None, receiving_td_rate=None):
    return CareerSeason(
        season=season, season_offset=offset, games=games, team="MIN",
        targets=None, receptions=None, receiving_yards=None, receiving_tds=None,
        carries=None, rushing_yards=None, rushing_tds=None,
        attempts=None, passing_yards=None, passing_tds=None, fantasy_points_ppr=None,
        target_share=None, carry_share=None,
        yards_per_target=yards_per_target, yards_per_carry=None, catch_rate=catch_rate,
        receiving_td_rate=receiving_td_rate, rushing_td_rate=None,
    )


def test_talent_stats_covers_exactly_the_spec_list():
    assert TALENT_STATS == [
        "yards_per_target", "catch_rate", "yards_per_carry",
        "yards_per_attempt", "receiving_td_rate", "rushing_td_rate",
        "passing_td_rate", "passing_int_rate",
    ]


def _qb_season(season, offset, games, attempts, passing_tds=None, passing_interceptions=None):
    return CareerSeason(
        season=season, season_offset=offset, games=games, team="BUF",
        targets=None, receptions=None, receiving_yards=None, receiving_tds=None,
        carries=None, rushing_yards=None, rushing_tds=None,
        attempts=attempts, passing_yards=None, passing_tds=passing_tds, fantasy_points_ppr=None,
        target_share=None, carry_share=None,
        yards_per_target=None, yards_per_carry=None, catch_rate=None,
        receiving_td_rate=None, rushing_td_rate=None,
        passing_interceptions=passing_interceptions,
    )


def test_passing_td_rate_derived_from_raw_passing_tds_and_attempts():
    season = _qb_season(2025, 0, 17, attempts=550, passing_tds=35)
    assert season.passing_td_rate == pytest.approx(35 / 550)


def test_passing_int_rate_derived_from_raw_passing_interceptions_and_attempts():
    season = _qb_season(2025, 0, 17, attempts=550, passing_interceptions=11)
    assert season.passing_int_rate == pytest.approx(11 / 550)


def test_passing_td_rate_and_int_rate_none_when_attempts_missing():
    season = _qb_season(2025, 0, 17, attempts=None, passing_tds=35, passing_interceptions=11)
    assert season.passing_td_rate is None
    assert season.passing_int_rate is None


def test_passing_td_rate_none_when_raw_td_count_missing_even_with_attempts():
    season = _qb_season(2025, 0, 17, attempts=550, passing_tds=None)
    assert season.passing_td_rate is None


def test_average_talent_pools_passing_td_and_int_rate_across_seasons():
    from app.projections.context_aware.career_prior import career_weight
    seasons = [
        _qb_season(2025, 0, 17, attempts=550, passing_tds=35, passing_interceptions=11),
        _qb_season(2024, 1, 16, attempts=500, passing_tds=25, passing_interceptions=14),
    ]
    w0 = career_weight(0, 17)
    w1 = career_weight(1, 16)
    result = _average_talent(seasons)
    expected_td_rate = (w0 * (35 / 550) + w1 * (25 / 500)) / (w0 + w1)
    expected_int_rate = (w0 * (11 / 550) + w1 * (14 / 500)) / (w0 + w1)
    assert result["passing_td_rate"] == pytest.approx(expected_td_rate)
    assert result["passing_int_rate"] == pytest.approx(expected_int_rate)


def test_average_talent_ignores_none_values_per_stat_independently():
    # Values below are recency/sample-size WEIGHTED (career_weight, added in Task 5), not a plain
    # average. Expected weights computed from the real career_weight function (not a hardcoded
    # literal) so this test stays correct regardless of RECENCY_DECAY's current chosen value.
    from app.projections.context_aware.career_prior import career_weight
    seasons = [
        _season(2025, 0, 17, yards_per_target=8.0, catch_rate=0.6, receiving_td_rate=0.05),
        _season(2024, 1, 16, yards_per_target=10.0, catch_rate=None, receiving_td_rate=0.03),
    ]
    w0 = career_weight(0, 17)
    w1 = career_weight(1, 16)
    result = _average_talent(seasons)
    assert result["yards_per_target"] == pytest.approx((w0 * 8.0 + w1 * 10.0) / (w0 + w1))
    assert result["catch_rate"] == pytest.approx(0.6)  # only one real value -- average of just that one
    assert result["receiving_td_rate"] == pytest.approx((w0 * 0.05 + w1 * 0.03) / (w0 + w1))
    assert result["yards_per_carry"] is None  # no season has this stat -- stays unknown, not 0.0


def test_average_talent_empty_seasons_returns_all_none():
    result = _average_talent([])
    assert all(value is None for value in result.values())


def test_average_workload_covers_exactly_the_spec_list():
    from app.projections.context_aware.career_prior import WORKLOAD_STATS
    assert WORKLOAD_STATS == [
        "targets_per_game", "target_share", "carries_per_game", "carry_share", "fantasy_points_per_game",
    ]


def test_average_workload_ignores_none_and_uses_per_game_properties():
    from app.projections.context_aware.career_prior import _average_workload
    seasons = [
        CareerSeason(
            season=2025, season_offset=0, games=17, team="MIN",
            targets=170, receptions=None, receiving_yards=None, receiving_tds=None,
            carries=None, rushing_yards=None, rushing_tds=None,
            attempts=None, passing_yards=None, passing_tds=None, fantasy_points_ppr=204.0,
            target_share=0.28, carry_share=None,
            yards_per_target=None, yards_per_carry=None, catch_rate=None,
            receiving_td_rate=None, rushing_td_rate=None,
        ),
    ]
    result = _average_workload(seasons)
    assert result["targets_per_game"] == pytest.approx(10.0)  # 170/17
    assert result["target_share"] == pytest.approx(0.28)
    assert result["fantasy_points_per_game"] == pytest.approx(12.0)  # 204/17
    assert result["carries_per_game"] is None


def test_career_weight_most_recent_full_season_has_highest_weight():
    from app.projections.context_aware.career_prior import career_weight
    most_recent = career_weight(season_offset=0, games_played_that_season=17)
    older = career_weight(season_offset=1, games_played_that_season=17)
    assert most_recent > older


def test_career_weight_short_season_weighs_less_than_full_season_at_same_offset():
    from app.projections.context_aware.career_prior import career_weight
    short = career_weight(season_offset=0, games_played_that_season=3)
    full = career_weight(season_offset=0, games_played_that_season=17)
    assert short < full


def test_career_weight_zero_games_is_zero_weight():
    from app.projections.context_aware.career_prior import career_weight
    assert career_weight(season_offset=0, games_played_that_season=0) == pytest.approx(0.0)


def test_weighted_average_matches_hand_computed_value():
    from app.projections.context_aware.career_prior import career_weight, _weighted_average
    seasons = [
        CareerSeason(
            season=2025, season_offset=0, games=17, team="MIN",
            targets=None, receptions=None, receiving_yards=None, receiving_tds=None,
            carries=None, rushing_yards=None, rushing_tds=None,
            attempts=None, passing_yards=None, passing_tds=None, fantasy_points_ppr=None,
            target_share=None, carry_share=None,
            yards_per_target=10.0, yards_per_carry=None, catch_rate=None,
            receiving_td_rate=None, rushing_td_rate=None,
        ),
        CareerSeason(
            season=2024, season_offset=1, games=17, team="MIN",
            targets=None, receptions=None, receiving_yards=None, receiving_tds=None,
            carries=None, rushing_yards=None, rushing_tds=None,
            attempts=None, passing_yards=None, passing_tds=None, fantasy_points_ppr=None,
            target_share=None, carry_share=None,
            yards_per_target=6.0, yards_per_carry=None, catch_rate=None,
            receiving_td_rate=None, rushing_td_rate=None,
        ),
    ]
    result = _weighted_average(seasons, "yards_per_target", career_weight)
    w0 = career_weight(0, 17)
    w1 = career_weight(1, 17)
    expected = (w0 * 10.0 + w1 * 6.0) / (w0 + w1)
    assert result == pytest.approx(expected)
    assert result > 8.0  # more recent season, weighted higher, pulls the blend above the plain average


def _wr_season(season, offset, games, ypt, td_rate, target_share):
    return CareerSeason(
        season=season, season_offset=offset, games=games, team="MIN",
        targets=None, receptions=None, receiving_yards=None, receiving_tds=None,
        carries=None, rushing_yards=None, rushing_tds=None,
        attempts=None, passing_yards=None, passing_tds=None, fantasy_points_ppr=None,
        target_share=target_share, carry_share=None,
        yards_per_target=ypt, yards_per_carry=None, catch_rate=None,
        receiving_td_rate=td_rate, rushing_td_rate=None,
    )


def test_compute_career_prior_no_seasons_is_fully_unknown():
    from app.projections.context_aware.career_prior import compute_career_prior
    result = compute_career_prior([])
    assert result.seasons_used == 0
    assert all(v is None for v in result.talent.values())
    assert all(v is None for v in result.workload.values())


def test_team_changed_zeroes_workload_but_leaves_talent_untouched():
    from app.projections.context_aware.career_prior import compute_career_prior
    seasons = [_wr_season(2025, 0, 17, ypt=9.0, td_rate=0.06, target_share=0.28)]

    baseline = compute_career_prior(seasons)
    after_team_change = compute_career_prior(seasons, team_changed=True)

    assert after_team_change.talent["yards_per_target"] == pytest.approx(baseline.talent["yards_per_target"])
    assert after_team_change.talent["receiving_td_rate"] == pytest.approx(baseline.talent["receiving_td_rate"])
    assert after_team_change.workload["target_share"] is None  # hard zero -- fully discounted


def test_role_changed_softly_discounts_workload_only():
    from app.projections.context_aware.career_prior import compute_career_prior, ROLE_CHANGE_WORKLOAD_DISCOUNT
    seasons = [_wr_season(2025, 0, 17, ypt=9.0, td_rate=0.06, target_share=0.28)]

    baseline = compute_career_prior(seasons)
    after_role_change = compute_career_prior(seasons, role_changed_recently=True)

    assert after_role_change.talent["yards_per_target"] == pytest.approx(baseline.talent["yards_per_target"])
    assert after_role_change.workload["target_share"] == pytest.approx(
        baseline.workload["target_share"] * ROLE_CHANGE_WORKLOAD_DISCOUNT
    )
    assert after_role_change.workload["target_share"] > 0  # softened, not erased


def test_qb_change_seam_reduces_confidence_without_hard_zeroing():
    # This is the exact correction from the design review: a QB change alone must never zero
    # out career workload the way a team change does -- it only ever reduces confidence via the
    # multiplier 15.7c-B will supply from qb_changed.
    from app.projections.context_aware.career_prior import compute_career_prior
    seasons = [_wr_season(2025, 0, 17, ypt=9.0, td_rate=0.06, target_share=0.28)]

    baseline = compute_career_prior(seasons)
    with_qb_change_discount = compute_career_prior(seasons, workload_confidence_multiplier=0.7)

    assert with_qb_change_discount.talent["yards_per_target"] == pytest.approx(baseline.talent["yards_per_target"])
    assert with_qb_change_discount.workload["target_share"] == pytest.approx(
        baseline.workload["target_share"] * 0.7
    )
    assert with_qb_change_discount.workload["target_share"] > 0


def test_jefferson_style_case_talent_preserved_workload_rebuilt():
    # Real-shaped regression case: multiple elite seasons, then team_changed=True (simulating a
    # scenario where his workload needs to be rebuilt from the new team's context, per 15.7c-B) --
    # talent (his proven target-earning/efficiency ability) must still show up as elite-caliber.
    from app.projections.context_aware.career_prior import compute_career_prior
    seasons = [
        _wr_season(2025, 0, 17, ypt=7.4, td_rate=0.014, target_share=0.286),  # real 2025: down TD year
        _wr_season(2024, 1, 17, ypt=9.8, td_rate=0.065, target_share=0.30),
        _wr_season(2023, 2, 17, ypt=9.1, td_rate=0.058, target_share=0.29),
    ]
    result = compute_career_prior(seasons, team_changed=True)
    # Multi-year talent should sit meaningfully above the single down season's own 7.4 --
    # older elite seasons pull it up, exactly the "one bad season shouldn't fully redefine him" fix.
    assert result.talent["yards_per_target"] > 7.4
    assert result.talent["receiving_td_rate"] > 0.014
    assert result.workload["target_share"] is None  # team changed -- workload correctly discarded
    assert result.seasons_used == 3


def test_classify_talent_tier_boundaries():
    from app.projections.context_aware.career_prior import classify_talent_tier
    cutoffs = (6.0, 7.5, 9.0, 10.5)  # p20, p40, p60, p80
    assert classify_talent_tier(11.0, cutoffs) == "elite"          # above p80
    assert classify_talent_tier(9.5, cutoffs) == "above_average"   # p60-p80
    assert classify_talent_tier(8.0, cutoffs) == "average"         # p40-p60
    assert classify_talent_tier(6.5, cutoffs) == "below_average"   # p20-p40
    assert classify_talent_tier(3.0, cutoffs) == "below_average"   # below p20


def test_classify_talent_tier_missing_value_or_cutoffs_is_unknown():
    from app.projections.context_aware.career_prior import classify_talent_tier
    assert classify_talent_tier(None, (6.0, 7.5, 9.0, 10.5)) == "unknown"
    assert classify_talent_tier(9.0, None) == "unknown"


def test_compute_career_prior_reports_unknown_tier_with_no_seasons():
    from app.projections.context_aware.career_prior import compute_career_prior
    result = compute_career_prior([])
    assert result.talent_tier == "unknown"


def test_compute_career_prior_classifies_real_elite_profile():
    from app.projections.context_aware.career_prior import compute_career_prior
    seasons = [_wr_season(2025, 0, 17, ypt=11.0, td_rate=0.06, target_share=0.28)]
    result = compute_career_prior(seasons, key_stat_percentile_cutoffs=(6.0, 7.5, 9.0, 10.5))
    assert result.talent_tier == "elite"
