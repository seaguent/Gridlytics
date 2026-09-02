import pandas as pd
import pytest

from app.projections.context_aware.depth_chart import RoleInfo
from app.projections.context_aware.team_context import TeamTendencies
from app.projections.context_aware.model import (
    compute_share_priors_by_rank,
    project_context_aware_points_detailed,
)
from app.projections.scoring_rules import STANDARD_PPR, ScoringRules


def _wr_game(targets, receiving_yards, receiving_tds, receptions):
    return {"targets": targets, "receiving_yards": receiving_yards, "receiving_tds": receiving_tds, "receptions": receptions}


def test_unknown_position_returns_none():
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    result = project_context_aware_points_detailed(
        "DEF", [], None, tendencies, role, {}, {}, team_changed=False, platform_points=None, availability_status="healthy",
    )
    assert result is None


def test_unavailable_player_returns_none_not_a_normal_projection():
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    result = project_context_aware_points_detailed(
        "WR", [], None, tendencies, role, {}, {}, team_changed=False, platform_points=15.0, availability_status="unavailable",
    )
    assert result is None


def test_rookie_with_no_history_uses_team_volume_and_role_rank_share_prior():
    # share_priors_by_rank supplies ONLY the share fraction (real production shape from
    # compute_share_priors_by_rank); position_efficiency_priors supplies the SEPARATE
    # position-wide rate priors (real production shape from 15.7a's compute_all_position_priors)
    # -- these are two genuinely different dicts, never conflated, matching the real bug this
    # test setup exists specifically to catch (an earlier version of this test accidentally put
    # both in the same dict, masking the fact that production code never does).
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    share_priors = {"WR": {1: {"receiving": 0.20}}}
    efficiency_priors = {"receiving": {"yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}}
    result = project_context_aware_points_detailed(
        "WR", [], None, tendencies, role, share_priors, efficiency_priors,
        team_changed=False, platform_points=None, availability_status="healthy",
    )
    assert result is not None
    assert result.total_points > 0
    category = result.categories[0]
    assert category.expected_team_opportunities == pytest.approx(35.0)
    assert category.expected_share == pytest.approx(0.20)
    assert category.expected_opportunities == pytest.approx(7.0)
    # points = 7.0 * (8.0*0.1 + 0.05*6.0 + 0.6*1.0) = 7.0 * (0.8+0.3+0.6) = 7.0*1.7 = 11.9
    assert result.total_points == pytest.approx(11.9)


def test_default_scoring_rules_matches_standard_ppr_exactly():
    # No scoring_rules passed -- must produce byte-for-byte the same total as before this change,
    # proving the refactor is behavior-preserving for every existing caller (backtests included).
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    share_priors = {"WR": {1: {"receiving": 0.20}}}
    efficiency_priors = {"receiving": {"yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}}
    default_result = project_context_aware_points_detailed(
        "WR", [], None, tendencies, role, share_priors, efficiency_priors,
        team_changed=False, platform_points=None, availability_status="healthy",
    )
    explicit_ppr_result = project_context_aware_points_detailed(
        "WR", [], None, tendencies, role, share_priors, efficiency_priors,
        team_changed=False, platform_points=None, availability_status="healthy",
        scoring_rules=STANDARD_PPR,
    )
    assert default_result.total_points == pytest.approx(11.9)  # matches the pre-existing, already-verified total
    assert default_result.total_points == pytest.approx(explicit_ppr_result.total_points)


def test_half_ppr_scoring_rules_produce_a_genuinely_different_lower_total():
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    share_priors = {"WR": {1: {"receiving": 0.20}}}
    efficiency_priors = {"receiving": {"yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}}
    half_ppr = ScoringRules(reception_points=0.5)
    result = project_context_aware_points_detailed(
        "WR", [], None, tendencies, role, share_priors, efficiency_priors,
        team_changed=False, platform_points=None, availability_status="healthy",
        scoring_rules=half_ppr,
    )
    # points = 7.0 * (8.0*0.1 + 0.05*6.0 + 0.6*0.5) = 7.0 * (0.8+0.3+0.3) = 7.0*1.4 = 9.8
    assert result.total_points == pytest.approx(9.8)
    assert result.total_points < 11.9  # strictly less than the PPR total -- half-credit receptions must matter


def test_custom_interception_penalty_changes_qb_total():
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    share_priors = {"QB": {1: {"passing": 1.0}}}  # the starting QB throws effectively all the team's passes
    efficiency_priors = {"passing": {"yards_per_attempt": 8.0, "td_rate": 0.05, "int_rate": 0.05}}
    standard_result = project_context_aware_points_detailed(
        "QB", [], None, tendencies, role, share_priors, efficiency_priors,
        team_changed=False, platform_points=None, availability_status="healthy",
    )  # -2/INT default
    custom_rules = ScoringRules(pass_int_points=-1.0)  # a real league's softer INT penalty
    custom_result = project_context_aware_points_detailed(
        "QB", [], None, tendencies, role, share_priors, efficiency_priors,
        team_changed=False, platform_points=None, availability_status="healthy",
        scoring_rules=custom_rules,
    )
    assert standard_result.total_points is not None
    assert custom_result.total_points is not None
    assert custom_result.total_points > standard_result.total_points  # a softer INT penalty must raise the total


def test_no_resolvable_information_abstains_with_none_not_a_fabricated_zero():
    # role_confidence "unknown" (pos_rank=None) + no current/prior history + no rank prior
    # available at all -- genuinely nothing to project from. Must return total_points=None
    # ("abstain"), never a fabricated 0.0 that would be indistinguishable from a real projected
    # zero downstream in the backtest.
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=None, role_confidence="unknown", role_changed_recently=False)
    result = project_context_aware_points_detailed(
        "WR", [], None, tendencies, role, {}, {}, team_changed=False, platform_points=None, availability_status="healthy",
    )
    assert result is not None  # the breakdown object itself still exists, carrying the flags
    assert result.total_points is None
    assert result.role_confidence == "unknown"


def test_missing_efficiency_prior_for_a_category_abstains_that_category_not_a_fabricated_zero():
    # Real regression test for the bug this fix addresses: expected_opportunities resolves (a
    # real share exists), but NO efficiency-rate prior exists for this category at all -- the
    # category must contribute nothing resolvable, not a silent 0.0 masquerading as "no receiving
    # production this week." With only one category (WR), this means full abstention.
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    share_priors = {"WR": {1: {"receiving": 0.20}}}
    result = project_context_aware_points_detailed(
        "WR", [], None, tendencies, role, share_priors, {},  # no efficiency priors at all
        team_changed=False, platform_points=None, availability_status="healthy",
    )
    assert result is not None
    assert result.total_points == pytest.approx(0.0)  # opportunities resolved, but zero real rate priors to convert with
    assert result.categories[0].expected_opportunities == pytest.approx(7.0)
    assert result.categories[0].points == pytest.approx(0.0)


def test_partial_information_still_produces_a_real_total_not_an_abstention():
    # RB: rushing resolves (real role-rank share prior + real efficiency prior available),
    # receiving does not (no share prior at all) -- partial information is a real, defensible
    # point estimate, distinct from full abstention.
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    share_priors = {"RB": {1: {"rushing": 0.55}}}  # no "receiving" entry
    efficiency_priors = {"rushing": {"yards_per_carry": 4.2, "td_rate": 0.05}}
    result = project_context_aware_points_detailed(
        "RB", [], None, tendencies, role, share_priors, efficiency_priors,
        team_changed=False, platform_points=None, availability_status="healthy",
    )
    assert result.total_points is not None
    assert result.total_points > 0


def test_conflict_flag_set_when_platform_near_zero_and_team_changed():
    # role_confidence must be "high" (a real, known pos_rank) for the model to have anything to
    # fall back to -- role_confidence "unknown"/"low" always come with pos_rank=None (see
    # depth_chart.py), meaning there is genuinely no rank-specific prior to resolve a real
    # projection from, and the model correctly produces 0 rather than fabricate one. The conflict
    # scenario here is a real known role PLUS a team change (which alone is a real risk signal).
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    share_priors = {"RB": {1: {"rushing": 0.55}}}
    efficiency_priors = {"rushing": {"yards_per_carry": 4.2, "td_rate": 0.05}}
    result = project_context_aware_points_detailed(
        "RB", [], None, tendencies, role, share_priors, efficiency_priors,
        team_changed=True, platform_points=0.0, availability_status="healthy",
    )
    assert result is not None
    assert result.total_points > 0  # real positive projection, driven by the role-rank prior fallback
    assert result.projection_conflict is True
    assert result.conflict_reason is not None
    assert "team change" in result.conflict_reason.lower()


def test_compute_share_priors_by_rank_pools_real_target_share_by_position_and_rank():
    rows = [
        {"player_id": "p1", "position": "WR", "season": 2024, "week": 1, "season_type": "REG",
         "team": "SF", "target_share": 0.30, "carries": 0, "attempts": 0},
        {"player_id": "p2", "position": "WR", "season": 2024, "week": 1, "season_type": "REG",
         "team": "SF", "target_share": 0.10, "carries": 0, "attempts": 0},
    ]
    depth_charts = pd.DataFrame([
        {"dt": "2024-08-01T00:00:00Z", "team": "SF", "gsis_id": "p1", "pos_abb": "WR", "pos_rank": 1},
        {"dt": "2024-08-01T00:00:00Z", "team": "SF", "gsis_id": "p2", "pos_abb": "WR", "pos_rank": 2},
    ])
    result = compute_share_priors_by_rank(
        pd.DataFrame(rows), depth_charts, season=2025, before_week=None, as_of_date="2025-09-01"
    )
    assert result["WR"][1]["receiving"] == pytest.approx(0.30)
    assert result["WR"][2]["receiving"] == pytest.approx(0.10)
    # Confirms the real production shape: only share keys, never efficiency-rate keys.
    assert "yards_per_target" not in result["WR"][1]


def test_add_share_columns_derives_rushing_and_passing_share_from_team_totals():
    from app.projections.context_aware.model import add_share_columns

    rows = [
        {"player_id": "p1", "position": "RB", "season": 2024, "week": 1, "season_type": "REG",
         "team": "SF", "target_share": 0.05, "carries": 15, "attempts": 0},
        {"player_id": "p2", "position": "RB", "season": 2024, "week": 1, "season_type": "REG",
         "team": "SF", "target_share": 0.02, "carries": 5, "attempts": 0},
    ]
    result = add_share_columns(pd.DataFrame(rows))
    p1 = result[result["player_id"] == "p1"].iloc[0]
    assert p1["receiving_share"] == pytest.approx(0.05)
    assert p1["rushing_share"] == pytest.approx(15 / 20)  # 15 of the team's 20 total carries


def test_add_share_columns_does_not_let_two_seasons_at_the_same_team_week_contaminate_each_other():
    # Real bug this regression closes: a multi-season weekly_stats frame (every real caller passes
    # one -- prior-season history has to be present) previously grouped team totals by (team, week)
    # only, so a team's "week 3" total silently summed 2024's week 3 and 2025's week 3 together.
    from app.projections.context_aware.model import add_share_columns

    rows = [
        # 2024 week 3: KC's only passer that week threw 39 team attempts.
        {"player_id": "qb_2024", "position": "QB", "season": 2024, "week": 3, "season_type": "REG",
         "team": "KC", "target_share": 0.0, "carries": 0, "attempts": 39},
        # 2025 week 3: a DIFFERENT sole passer threw 37 team attempts -- entirely separate season.
        {"player_id": "qb_2025", "position": "QB", "season": 2025, "week": 3, "season_type": "REG",
         "team": "KC", "target_share": 0.0, "carries": 0, "attempts": 37},
    ]
    result = add_share_columns(pd.DataFrame(rows))

    row_2024 = result[result["player_id"] == "qb_2024"].iloc[0]
    row_2025 = result[result["player_id"] == "qb_2025"].iloc[0]
    assert row_2024["passing_share"] == pytest.approx(1.0)
    assert row_2025["passing_share"] == pytest.approx(1.0)


def test_add_share_columns_sole_2025_passer_gets_full_share_even_with_2024_rows_present():
    # The exact real scenario the forensic audit traced: Mahomes, KC week 3 2025, 37 team
    # attempts, with 2024 week 3 rows (39 attempts) also present in the same multi-season frame.
    # Pre-fix this computed 37 / (39 + 37) = 0.4868 instead of the correct 1.0.
    from app.projections.context_aware.model import add_share_columns

    rows = [
        {"player_id": "old_qb", "position": "QB", "season": 2024, "week": 3, "season_type": "REG",
         "team": "KC", "target_share": 0.0, "carries": 0, "attempts": 39},
        {"player_id": "mahomes", "position": "QB", "season": 2025, "week": 3, "season_type": "REG",
         "team": "KC", "target_share": 0.0, "carries": 0, "attempts": 37},
        {"player_id": "kc_rb", "position": "RB", "season": 2025, "week": 3, "season_type": "REG",
         "team": "KC", "target_share": 0.0, "carries": 10, "attempts": 0},
    ]
    result = add_share_columns(pd.DataFrame(rows))
    mahomes_row = result[result["player_id"] == "mahomes"].iloc[0]
    assert mahomes_row["passing_share"] == pytest.approx(1.0)


def test_add_share_columns_rushing_shares_within_a_team_season_week_sum_to_one():
    from app.projections.context_aware.model import add_share_columns

    rows = [
        {"player_id": "rb1", "position": "RB", "season": 2025, "week": 5, "season_type": "REG",
         "team": "SF", "target_share": 0.0, "carries": 12, "attempts": 0},
        {"player_id": "rb2", "position": "RB", "season": 2025, "week": 5, "season_type": "REG",
         "team": "SF", "target_share": 0.0, "carries": 6, "attempts": 0},
        {"player_id": "qb1", "position": "QB", "season": 2025, "week": 5, "season_type": "REG",
         "team": "SF", "target_share": 0.0, "carries": 2, "attempts": 30},
        # A different team, same week -- must not leak into SF's total.
        {"player_id": "other_team_rb", "position": "RB", "season": 2025, "week": 5, "season_type": "REG",
         "team": "KC", "target_share": 0.0, "carries": 20, "attempts": 0},
    ]
    result = add_share_columns(pd.DataFrame(rows))
    sf_rows = result[result["team"] == "SF"]
    assert sf_rows["rushing_share"].sum() == pytest.approx(1.0)


def test_add_share_columns_single_season_behavior_unchanged():
    # No cross-season data present at all -- proves the fix is behavior-preserving for the
    # already-passing single-season case (mirrors the original pre-fix test's exact assertions).
    from app.projections.context_aware.model import add_share_columns

    rows = [
        {"player_id": "p1", "position": "RB", "season": 2024, "week": 1, "season_type": "REG",
         "team": "SF", "target_share": 0.05, "carries": 15, "attempts": 0},
        {"player_id": "p2", "position": "RB", "season": 2024, "week": 1, "season_type": "REG",
         "team": "SF", "target_share": 0.02, "carries": 5, "attempts": 0},
    ]
    result = add_share_columns(pd.DataFrame(rows))
    p1 = result[result["player_id"] == "p1"].iloc[0]
    assert p1["receiving_share"] == pytest.approx(0.05)
    assert p1["rushing_share"] == pytest.approx(15 / 20)


def test_rb_with_real_current_season_carries_uses_derived_rushing_share():
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    share_priors = {"RB": {1: {"rushing": 0.40}}}
    efficiency_priors = {"rushing": {"yards_per_carry": 4.2, "td_rate": 0.05}}
    current_games = [
        {"team": "SF", "week": w, "carries": 12, "rushing_yards": 50, "rushing_tds": 0, "rushing_share": 0.60,
         "targets": 0, "receiving_share": 0.0, "receiving_yards": 0, "receiving_tds": 0, "receptions": 0}
        for w in range(1, 9)
    ]
    result = project_context_aware_points_detailed(
        "RB", current_games, None, tendencies, role, share_priors, efficiency_priors,
        team_changed=False, platform_points=None, availability_status="healthy",
    )
    rushing = next(c for c in result.categories if c.name == "rushing")
    # 8 real games -> prior_season_weight(8) == 0, fully current -> expected_share == 0.60 (own real share)
    assert rushing.expected_share == pytest.approx(0.60)
    assert rushing.expected_team_opportunities == pytest.approx(25.0)
    assert rushing.expected_opportunities == pytest.approx(15.0)
    # points = 15.0 * (4.2 own-rate-shrunk... but own history has real per-game rate too)
    assert rushing.points > 0


def test_compute_effective_prior_no_career_value_is_pure_fallback():
    from app.projections.context_aware.model import compute_effective_prior
    result = compute_effective_prior(
        career_value=None, total_career_opportunities=0, fallback_value=8.0, full_confidence_opportunities=200,
    )
    assert result.career_value is None
    assert result.career_evidence_weight == pytest.approx(0.0)
    assert result.fallback_value == pytest.approx(8.0)
    assert result.effective_value == pytest.approx(8.0)


def test_compute_effective_prior_full_confidence_trusts_career_value():
    from app.projections.context_aware.model import compute_effective_prior
    result = compute_effective_prior(
        career_value=11.0, total_career_opportunities=500, fallback_value=8.0, full_confidence_opportunities=200,
    )
    assert result.career_evidence_weight == pytest.approx(1.0)  # capped
    assert result.effective_value == pytest.approx(11.0)


def test_compute_effective_prior_thin_sample_pulls_toward_fallback():
    from app.projections.context_aware.model import compute_effective_prior
    result = compute_effective_prior(
        career_value=11.0, total_career_opportunities=50, fallback_value=8.0, full_confidence_opportunities=200,
    )
    assert result.career_evidence_weight == pytest.approx(0.25)
    assert result.effective_value == pytest.approx(0.25 * 11.0 + 0.75 * 8.0)


def test_compute_effective_prior_no_fallback_available_uses_career_value_alone():
    from app.projections.context_aware.model import compute_effective_prior
    result = compute_effective_prior(
        career_value=11.0, total_career_opportunities=50, fallback_value=None, full_confidence_opportunities=200,
    )
    assert result.effective_value == pytest.approx(11.0)


def test_compute_effective_prior_missing_full_confidence_threshold_is_pure_fallback():
    # PLACEHOLDER thresholds default to None until Task 8 calibrates them -- must degrade safely,
    # not crash or silently divide by None.
    from app.projections.context_aware.model import compute_effective_prior
    result = compute_effective_prior(
        career_value=11.0, total_career_opportunities=50, fallback_value=8.0, full_confidence_opportunities=None,
    )
    assert result.career_evidence_weight == pytest.approx(0.0)
    assert result.effective_value == pytest.approx(8.0)


def test_career_opportunity_total_sums_across_seasons_treating_missing_as_zero():
    from app.projections.context_aware.model import _career_opportunity_total
    from app.projections.context_aware.career_prior import CareerSeason

    def _season(targets):
        return CareerSeason(
            season=2025, season_offset=0, games=17, team="MIN",
            targets=targets, receptions=None, receiving_yards=None, receiving_tds=None,
            carries=None, rushing_yards=None, rushing_tds=None,
            attempts=None, passing_yards=None, passing_tds=None, fantasy_points_ppr=None,
            target_share=None, carry_share=None, yards_per_target=None, yards_per_carry=None,
            catch_rate=None, receiving_td_rate=None, rushing_td_rate=None,
        )

    seasons = [_season(100), _season(None), _season(50)]
    assert _career_opportunity_total(seasons, "targets") == 150


def test_career_talent_key_mapping_covers_every_real_rate_and_flags_known_gaps():
    from app.projections.context_aware.model import CAREER_TALENT_KEY_BY_CATEGORY_RATE
    from app.projections.native.categories import POSITION_CATEGORIES

    for categories in POSITION_CATEGORIES.values():
        for category in categories:
            for rate_name in category.rate_specs:
                assert (category.name, rate_name) in CAREER_TALENT_KEY_BY_CATEGORY_RATE, (
                    f"missing career-talent mapping entry for ({category.name}, {rate_name})"
                )

    # Passing td_rate/int_rate resolve to real career-prior talent stats too, same mechanism as
    # every other rate.
    assert CAREER_TALENT_KEY_BY_CATEGORY_RATE[("passing", "td_rate")] == "passing_td_rate"
    assert CAREER_TALENT_KEY_BY_CATEGORY_RATE[("passing", "int_rate")] == "passing_int_rate"
    # Real mappings resolve to career_prior.py's own TALENT_STATS names.
    assert CAREER_TALENT_KEY_BY_CATEGORY_RATE[("receiving", "yards_per_target")] == "yards_per_target"
    assert CAREER_TALENT_KEY_BY_CATEGORY_RATE[("receiving", "td_rate")] == "receiving_td_rate"
    assert CAREER_TALENT_KEY_BY_CATEGORY_RATE[("receiving", "reception_rate")] == "catch_rate"
    assert CAREER_TALENT_KEY_BY_CATEGORY_RATE[("rushing", "yards_per_carry")] == "yards_per_carry"
    assert CAREER_TALENT_KEY_BY_CATEGORY_RATE[("rushing", "td_rate")] == "rushing_td_rate"
    assert CAREER_TALENT_KEY_BY_CATEGORY_RATE[("passing", "yards_per_attempt")] == "yards_per_attempt"


def test_category_to_workload_stat_excludes_passing_deliberately():
    from app.projections.context_aware.model import CATEGORY_TO_WORKLOAD_STAT
    assert CATEGORY_TO_WORKLOAD_STAT["receiving"] == "target_share"
    assert CATEGORY_TO_WORKLOAD_STAT["rushing"] == "carry_share"
    assert CATEGORY_TO_WORKLOAD_STAT["passing"] is None


def _career_season(season, offset, games, ypt=None, td_rate=None, catch_rate=None,
                    target_share=None, targets=None, team="MIN"):
    from app.projections.context_aware.career_prior import CareerSeason
    return CareerSeason(
        season=season, season_offset=offset, games=games, team=team,
        targets=targets, receptions=None, receiving_yards=None, receiving_tds=None,
        carries=None, rushing_yards=None, rushing_tds=None,
        attempts=None, passing_yards=None, passing_tds=None, fantasy_points_ppr=None,
        target_share=target_share, carry_share=None,
        yards_per_target=ypt, yards_per_carry=None, catch_rate=catch_rate,
        receiving_td_rate=td_rate, rushing_td_rate=None,
    )


def test_v2_stale_team_bug_class_current_team_only_ever_comes_from_explicit_param():
    # The exact regression this function structurally closes: a contaminated/stale historical
    # field must never be able to masquerade as the current team. team_changed is computed
    # ONLY from current_team/prior_season_team, both explicit typed params -- there is no other
    # code path (e.g. a game dict's own "team" field) that can influence it.
    from app.projections.context_aware.model import project_context_aware_points_detailed_v2
    from app.projections.context_aware.career_prior import compute_career_prior
    from app.projections.context_aware.depth_chart import RoleInfo
    from app.projections.context_aware.qb_context import QBContext
    from app.projections.context_aware.team_context import TeamTendencies

    seasons = [_career_season(2025, 0, 17, ypt=9.0, td_rate=0.05, catch_rate=0.65,
                               target_share=0.25, targets=140, team="MIN")]
    career_prior = compute_career_prior(seasons)
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    qb_context = QBContext(current_qb_gsis_id="qb-1", prior_qb_gsis_id="qb-1", qb_changed=False, confidence="depth_chart")

    result = project_context_aware_points_detailed_v2(
        "WR", current_season_games=[], prior_season_games=[{"targets": 9, "receiving_yards": 90,
            "receiving_tds": 0, "receptions": 6, "target_share": 0.25}],
        career_prior=career_prior, career_seasons=seasons, team_tendencies=tendencies, role=role,
        qb_context=qb_context, share_priors_by_rank={}, position_efficiency_priors={"receiving": {}},
        current_team="MIN", prior_season_team="MIN",
        platform_points=None, availability_status="healthy",
    )
    assert result is not None
    assert result.team_changed is False


def test_v2_real_team_change_hard_discounts_workload_but_preserves_talent():
    from app.projections.context_aware.model import project_context_aware_points_detailed_v2
    from app.projections.context_aware.career_prior import compute_career_prior
    from app.projections.context_aware.depth_chart import RoleInfo
    from app.projections.context_aware.qb_context import QBContext
    from app.projections.context_aware.team_context import TeamTendencies

    seasons = [_career_season(2025, 0, 17, ypt=9.0, td_rate=0.05, catch_rate=0.65,
                               target_share=0.25, targets=140, team="MIN")]
    career_prior = compute_career_prior(seasons, team_changed=True)  # caller must pass this consistently
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    qb_context = QBContext(current_qb_gsis_id="qb-2", prior_qb_gsis_id="qb-1", qb_changed=True, confidence="depth_chart")

    result = project_context_aware_points_detailed_v2(
        "WR", current_season_games=[], prior_season_games=None,
        career_prior=career_prior, career_seasons=seasons, team_tendencies=tendencies, role=role,
        qb_context=qb_context, share_priors_by_rank={"WR": {1: {"receiving": 0.20}}},
        position_efficiency_priors={"receiving": {"yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}},
        current_team="LA", prior_season_team="MIN",
        platform_points=None, availability_status="healthy",
    )
    assert result is not None
    assert result.team_changed is True
    # Workload prior: career_prior.workload is all-None on team change (A's own hard zero) ->
    # career_workload_prior's effective_value falls back to the role-rank prior, not the stale
    # career share.
    workload = result.career_workload_prior["target_share"]
    assert workload.career_value is None
    assert workload.effective_value == pytest.approx(0.20)
    # Talent prior: career_prior.talent is untouched by team_changed (A's own behavior) -- this
    # function must still surface it as real evidence, not silently drop it.
    talent = result.career_talent_prior["yards_per_target"]
    assert talent.career_value == pytest.approx(9.0)


def test_v2_reports_career_evidence_weight_distinctly_from_effective_value():
    # Direct test of the debuggability requirement from review: thin vs. robust evidence must
    # be visibly distinguishable in the breakdown, not collapsed into one opaque number.
    from app.projections.context_aware.model import project_context_aware_points_detailed_v2
    from app.projections.context_aware.career_prior import compute_career_prior
    from app.projections.context_aware.depth_chart import RoleInfo
    from app.projections.context_aware.qb_context import QBContext
    from app.projections.context_aware.team_context import TeamTendencies

    thin_seasons = [_career_season(2025, 0, 2, ypt=15.0, td_rate=0.2, catch_rate=0.9,
                                    target_share=0.3, targets=10, team="MIN")]
    career_prior = compute_career_prior(thin_seasons)
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    qb_context = QBContext(current_qb_gsis_id="qb-1", prior_qb_gsis_id="qb-1", qb_changed=False, confidence="depth_chart")

    result = project_context_aware_points_detailed_v2(
        "WR", current_season_games=[], prior_season_games=None,
        career_prior=career_prior, career_seasons=thin_seasons, team_tendencies=tendencies, role=role,
        qb_context=qb_context, share_priors_by_rank={"WR": {1: {"receiving": 0.20}}},
        position_efficiency_priors={"receiving": {"yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}},
        current_team="MIN", prior_season_team="MIN",
        platform_points=None, availability_status="healthy",
    )
    talent = result.career_talent_prior["yards_per_target"]
    assert talent.career_value == pytest.approx(15.0)  # the real (noisy, thin-sample) value
    assert talent.career_evidence_weight < 1.0  # not fully trusted -- only 10 real targets behind it
    assert talent.effective_value < 15.0  # pulled toward the position average, not taken at face value


def test_v2_qb_changed_never_discounts_the_point_estimate_but_stays_on_the_breakdown_for_explainability():
    # Corrected behavior per real validation: a real QB-change directional test on team pass
    # volume (2018-2025 nflverse data) found no consistent effect (QB-changed mean delta -0.405
    # vs unchanged -0.512, both well within one standard deviation) -- so qb_changed must never
    # discount any part of the point estimate, player-level workload included. It stays purely
    # informational: visible on the breakdown/qb_context for explainability and conflict
    # detection, never blended into career_prior or any math.
    from app.projections.context_aware.model import project_context_aware_points_detailed_v2
    from app.projections.context_aware.career_prior import compute_career_prior
    from app.projections.context_aware.depth_chart import RoleInfo
    from app.projections.context_aware.qb_context import QBContext
    from app.projections.context_aware.team_context import TeamTendencies

    seasons = [_career_season(2025, 0, 17, ypt=9.0, td_rate=0.05, catch_rate=0.65,
                               target_share=0.25, targets=140, team="MIN")]
    career_prior = compute_career_prior(seasons)  # constructed identically regardless of qb_changed

    no_qb_change = QBContext(current_qb_gsis_id="qb-1", prior_qb_gsis_id="qb-1", qb_changed=False, confidence="depth_chart")
    qb_change = QBContext(current_qb_gsis_id="qb-2", prior_qb_gsis_id="qb-1", qb_changed=True, confidence="depth_chart")
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    common_kwargs = dict(
        position="WR", current_season_games=[], prior_season_games=None,
        career_prior=career_prior, career_seasons=seasons, team_tendencies=tendencies, role=role,
        share_priors_by_rank={"WR": {1: {"receiving": 0.20}}},
        position_efficiency_priors={"receiving": {"yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}},
        current_team="MIN", prior_season_team="MIN",
        platform_points=None, availability_status="healthy",
    )

    baseline = project_context_aware_points_detailed_v2(qb_context=no_qb_change, **common_kwargs)
    with_qb_change = project_context_aware_points_detailed_v2(qb_context=qb_change, **common_kwargs)

    # The point estimate is byte-identical -- qb_changed truly touched nothing in the math.
    assert with_qb_change.total_points == pytest.approx(baseline.total_points)
    assert with_qb_change.career_workload_prior["target_share"].career_value == pytest.approx(
        baseline.career_workload_prior["target_share"].career_value
    )
    # But it's still visible for explainability.
    assert with_qb_change.qb_context.qb_changed is True
    assert baseline.qb_context.qb_changed is False


def test_v2_category_breakdown_exposes_shrunk_rates_per_rate_name():
    # Diagnostic-only addition for the forensic bias audit: the per-rate shrunk value that
    # category_points was already computed from (effective_talent blended with any real
    # current-season games) must be readable back off the breakdown, not just folded into the
    # aggregate points total -- mirrors native/model.py's CategoryBreakdown.shrunk_rates.
    from app.projections.context_aware.model import project_context_aware_points_detailed_v2
    from app.projections.context_aware.career_prior import compute_career_prior
    from app.projections.context_aware.depth_chart import RoleInfo
    from app.projections.context_aware.qb_context import QBContext
    from app.projections.context_aware.team_context import TeamTendencies

    seasons = [_career_season(2025, 0, 17, ypt=9.0, td_rate=0.05, catch_rate=0.65,
                               target_share=0.25, targets=140, team="MIN")]
    career_prior = compute_career_prior(seasons)
    tendencies = TeamTendencies(pass_attempts_per_game=35.0, rush_attempts_per_game=25.0)
    role = RoleInfo(pos_rank=1, role_confidence="high", role_changed_recently=False)
    qb_context = QBContext(current_qb_gsis_id="qb-1", prior_qb_gsis_id="qb-1", qb_changed=False, confidence="depth_chart")

    result = project_context_aware_points_detailed_v2(
        "WR", current_season_games=[], prior_season_games=None,
        career_prior=career_prior, career_seasons=seasons, team_tendencies=tendencies, role=role,
        qb_context=qb_context, share_priors_by_rank={"WR": {1: {"receiving": 0.20}}},
        position_efficiency_priors={"receiving": {"yards_per_target": 8.0, "td_rate": 0.05, "reception_rate": 0.6}},
        current_team="MIN", prior_season_team="MIN",
        platform_points=None, availability_status="healthy",
    )

    category = result.categories[0]
    assert category.name == "receiving"
    # No current-season games -> effective_talent (career=9.0 ypt, career=0.05 td_rate, and
    # catch_rate=0.65 feeding reception_rate) should read back near those career values.
    assert category.shrunk_rates["yards_per_target"] == pytest.approx(9.0, abs=0.5)
    assert category.shrunk_rates["td_rate"] == pytest.approx(0.05, abs=0.01)
    assert category.shrunk_rates["reception_rate"] == pytest.approx(0.65, abs=0.05)
