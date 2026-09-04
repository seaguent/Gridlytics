from dataclasses import dataclass, field

import pandas as pd

from app.projections.context_aware.availability import gate_availability
from app.projections.context_aware.career_prior import CareerPrior, CareerSeason
from app.projections.context_aware.conflict import detect_projection_conflict
from app.projections.context_aware.depth_chart import RoleInfo, _latest_snapshot_before
from app.projections.context_aware.qb_context import QBContext
from app.projections.context_aware.share import estimate_player_share
from app.projections.context_aware.team_context import TeamTendencies
from app.projections.native.categories import (
    POSITION_CATEGORIES,
    SCORING_FIELD_BY_CATEGORY_RATE,
    extract_player_rate_series,
)
from app.projections.native.efficiency import estimate_player_efficiency
from app.projections.scoring_rules import STANDARD_PPR, ScoringRules

# Which raw stat column each derived share (beyond "receiving", which reuses target_share
# directly) is a fraction of the team's per-game total for.
SHARE_VOLUME_COLUMN = {"rushing": "carries", "passing": "attempts"}


@dataclass
class CategoryShareBreakdown:
    name: str
    expected_team_opportunities: float | None
    expected_share: float | None
    expected_opportunities: float | None
    points: float
    shrunk_rates: dict[str, float] = field(default_factory=dict)


@dataclass
class ContextAwareBreakdown:
    total_points: float | None
    categories: list[CategoryShareBreakdown]
    availability_status: str
    team_changed: bool
    role_confidence: str
    role_changed_recently: bool
    projection_conflict: bool
    conflict_reason: str | None


def add_share_columns(weekly_stats: pd.DataFrame) -> pd.DataFrame:
    """Must be called on the full multi-player DataFrame before slicing into per-player lists."""
    result = weekly_stats.copy()
    result["receiving_share"] = result["target_share"]
    for category_name, volume_col in SHARE_VOLUME_COLUMN.items():
        # season must be part of the grouping identity, not just (team, week) -- a multi-season
        # frame (every caller passes one, since prior-season history has to be present) would
        # otherwise sum a team's "week 3" total across every season present, silently corrupting
        # every player's share.
        team_totals = result.groupby(["team", "season", "week"])[volume_col].transform("sum")
        result[f"{category_name}_share"] = result[volume_col] / team_totals.replace(0, pd.NA)
    return result


def compute_share_priors_by_rank(
    weekly_stats: pd.DataFrame,
    depth_charts: pd.DataFrame,
    season: int,
    before_week: int | None,
    as_of_date: str,
) -> dict[str, dict[int, dict[str, float]]]:
    if weekly_stats.empty:
        return {}

    reg = weekly_stats[weekly_stats["season_type"] == "REG"]
    if before_week is None:
        eligible = reg[reg["season"] <= season].copy()
    else:
        eligible = reg[(reg["season"] < season) | ((reg["season"] == season) & (reg["week"] < before_week))].copy()
    if eligible.empty:
        return {}

    eligible = add_share_columns(eligible)

    snapshot = _latest_snapshot_before(depth_charts, as_of_date)
    rank_by_gsis_position = (
        {(row["gsis_id"], row["pos_abb"]): int(row["pos_rank"]) for _, row in snapshot.iterrows()}
        if not snapshot.empty else {}
    )
    eligible["pos_rank"] = eligible.apply(
        lambda r: rank_by_gsis_position.get((r["player_id"], r["position"])), axis=1
    )
    eligible = eligible.dropna(subset=["pos_rank"])
    if eligible.empty:
        return {}

    result: dict[str, dict[int, dict[str, float]]] = {}
    for category_name in ("receiving", "rushing", "passing"):
        grouped = eligible.groupby(["position", "pos_rank"])[f"{category_name}_share"].mean()
        for (position, pos_rank), value in grouped.items():
            if pd.isna(value):
                continue
            result.setdefault(position, {}).setdefault(int(pos_rank), {})[category_name] = float(value)
    return result


def project_context_aware_points_detailed(
    position: str,
    current_season_games: list[dict],
    prior_season_games: list[dict] | None,
    team_tendencies: TeamTendencies,
    role: RoleInfo,
    share_priors_by_rank: dict[str, dict[int, dict[str, float]]],
    position_efficiency_priors: dict[str, dict[str, float | None]],
    team_changed: bool,
    platform_points: float | None,
    availability_status: str,
    scoring_rules: ScoringRules = STANDARD_PPR,
) -> ContextAwareBreakdown | None:
    """position_efficiency_priors and share_priors_by_rank are different prior sources -- must not be conflated."""
    categories = POSITION_CATEGORIES.get(position)
    if not categories:
        return None
    if availability_status == "unavailable":
        return None

    rank_priors = share_priors_by_rank.get(position, {}).get(role.pos_rank or -1, {})

    total_points = 0.0
    category_breakdowns: list[CategoryShareBreakdown] = []
    for category in categories:
        team_opportunities = (
            team_tendencies.pass_attempts_per_game
            if category.name in ("receiving", "passing")
            else team_tendencies.rush_attempts_per_game
        )

        # Uniform across all three categories: current_season_games/prior_season_games are
        # expected to already carry a f"{category.name}_share" key on every game dict, added by
        # add_share_columns() on the full multi-player DataFrame BEFORE per-player slicing (a
        # single player's own row can't derive their team-share on its own).
        share_key = f"{category.name}_share"
        current_shares = [g[share_key] for g in current_season_games if g.get(share_key) is not None]
        prior_shares = (
            [g[share_key] for g in prior_season_games if g.get(share_key) is not None]
            if prior_season_games else None
        )

        role_rank_prior_share = rank_priors.get(category.name)
        expected_share = estimate_player_share(
            current_shares, prior_shares, role_rank_prior_share, team_changed, role.role_changed_recently
        )

        expected_opportunities = (
            team_opportunities * expected_share
            if team_opportunities is not None and expected_share is not None
            else None
        )

        category_priors = position_efficiency_priors.get(category.name, {})
        category_points = 0.0
        if expected_opportunities is not None:
            for rate_name in category.rate_specs:
                position_rate_avg = category_priors.get(rate_name)
                if position_rate_avg is None:
                    continue

                # Real per-league scoring value, not the hardcoded standard-PPR default baked
                # into rate_specs -- that default is still what STANDARD_PPR itself resolves to.
                points_per_unit = getattr(scoring_rules, SCORING_FIELD_BY_CATEGORY_RATE[(category.name, rate_name)])

                player_rates = extract_player_rate_series(current_season_games, category, rate_name)
                shrunk_rate = estimate_player_efficiency(player_rates, position_rate_avg, team_changed=team_changed)
                category_points += expected_opportunities * shrunk_rate * points_per_unit

        total_points += category_points
        category_breakdowns.append(
            CategoryShareBreakdown(
                name=category.name,
                expected_team_opportunities=team_opportunities,
                expected_share=expected_share,
                expected_opportunities=expected_opportunities,
                points=category_points,
            )
        )

    # If NOT ONE category resolved any real expected_opportunities, there is genuinely nothing to
    # project from -- report this as an abstention (None), never a fabricated 0.0 that would be
    # indistinguishable from a real projected zero downstream (e.g. in the backtest's scoring).
    any_category_resolved = any(c.expected_opportunities is not None for c in category_breakdowns)
    final_points = total_points if any_category_resolved else None

    is_conflict, conflict_reason = (
        detect_projection_conflict(final_points, platform_points, availability_status, team_changed, role.role_confidence)
        if final_points is not None
        else (False, None)
    )

    return ContextAwareBreakdown(
        total_points=final_points,
        categories=category_breakdowns,
        availability_status=availability_status,
        team_changed=team_changed,
        role_confidence=role.role_confidence,
        role_changed_recently=role.role_changed_recently,
        projection_conflict=is_conflict,
        conflict_reason=conflict_reason,
    )


# ============================================================================
# Career-prior-aware model: adds multi-year player/team/QB context on top of the
# position-share model above.
# ============================================================================


@dataclass
class EffectivePrior:
    career_value: float | None
    career_evidence_weight: float
    fallback_value: float | None
    effective_value: float | None


def _career_opportunity_total(seasons: list[CareerSeason], opportunity_column: str) -> int:
    return sum(getattr(season, opportunity_column) or 0 for season in seasons)


def compute_effective_prior(
    career_value: float | None,
    total_career_opportunities: int,
    fallback_value: float | None,
    full_confidence_opportunities: float | None,
) -> EffectivePrior:
    if career_value is None or full_confidence_opportunities is None or full_confidence_opportunities <= 0:
        return EffectivePrior(
            career_value=career_value, career_evidence_weight=0.0,
            fallback_value=fallback_value, effective_value=fallback_value,
        )

    weight = max(0.0, min(1.0, total_career_opportunities / full_confidence_opportunities))
    if fallback_value is None:
        effective = career_value  # nothing to blend toward -- trust the career value alone
    else:
        effective = weight * career_value + (1 - weight) * fallback_value

    return EffectivePrior(
        career_value=career_value, career_evidence_weight=weight,
        fallback_value=fallback_value, effective_value=effective,
    )


CAREER_TALENT_KEY_BY_CATEGORY_RATE: dict[tuple[str, str], str | None] = {
    ("receiving", "yards_per_target"): "yards_per_target",
    ("receiving", "td_rate"): "receiving_td_rate",
    ("receiving", "reception_rate"): "catch_rate",
    ("rushing", "yards_per_carry"): "yards_per_carry",
    ("rushing", "td_rate"): "rushing_td_rate",
    ("passing", "yards_per_attempt"): "yards_per_attempt",
    ("passing", "td_rate"): "passing_td_rate",
    ("passing", "int_rate"): "passing_int_rate",
}

CATEGORY_TO_WORKLOAD_STAT: dict[str, str | None] = {
    "receiving": "target_share",
    "rushing": "carry_share",
    # A starting QB's "share" of team pass attempts isn't a career-workload concept the way
    # WR/RB share is -- QB identity/role is handled entirely by qb_context.py instead.
    "passing": None,
}

CATEGORY_TO_OPPORTUNITY_COLUMN = {"receiving": "targets", "rushing": "carries", "passing": "attempts"}

# qb_changed intentionally never discounts workload confidence here: a backtest found no
# consistent directional effect of a QB change on team pass volume. It stays purely
# informational, surfaced via QBContext/CareerAwareBreakdown.qb_context for explainability and
# conflict detection only.


@dataclass
class CareerAwareBreakdown:
    total_points: float | None
    categories: list[CategoryShareBreakdown]
    availability_status: str
    team_changed: bool
    role_confidence: str
    role_changed_recently: bool
    projection_conflict: bool
    conflict_reason: str | None
    career_talent_prior: dict[str, EffectivePrior]
    career_workload_prior: dict[str, EffectivePrior]
    qb_context: QBContext
    current_team: str | None
    prior_season_team: str | None
    team_offense: TeamTendencies


# Empirically chosen via backtest grid search. Talent has a real interior optimum (both smaller
# and larger values perform worse). Workload is kept at a low, near-unconditional-trust value
# (1, not 0) so a player with zero real career opportunities still falls back to the role-rank
# prior instead of dividing by zero.
TALENT_FULL_CONFIDENCE_OPPORTUNITIES: dict[str, float | None] = {
    "receiving": 250, "rushing": 250, "passing": 750,
}
WORKLOAD_FULL_CONFIDENCE_OPPORTUNITIES: dict[str, float | None] = {
    "receiving": 1, "rushing": 1,
}


def project_context_aware_points_detailed_v2(
    position: str,
    current_season_games: list[dict],
    prior_season_games: list[dict] | None,
    career_prior: CareerPrior,
    career_seasons: list[CareerSeason],
    team_tendencies: TeamTendencies,
    role: RoleInfo,
    qb_context: QBContext,
    share_priors_by_rank: dict[str, dict[int, dict[str, float]]],
    position_efficiency_priors: dict[str, dict[str, float | None]],
    current_team: str,
    prior_season_team: str | None,
    platform_points: float | None,
    availability_status: str,
    scoring_rules: ScoringRules = STANDARD_PPR,
) -> CareerAwareBreakdown | None:
    categories = POSITION_CATEGORIES.get(position)
    if not categories:
        return None
    if availability_status == "unavailable":
        return None

    # The structural fix for the stale-team bug class: team_changed can ONLY ever be derived
    # from these two explicitly-typed, explicitly-sourced parameters. No other value (a game
    # dict's own team field, a cached historical value) can influence it.
    team_changed = bool(current_team and prior_season_team and current_team != prior_season_team)

    rank_priors = share_priors_by_rank.get(position, {}).get(role.pos_rank or -1, {})

    career_talent_prior: dict[str, EffectivePrior] = {}
    career_workload_prior: dict[str, EffectivePrior] = {}

    total_points = 0.0
    category_breakdowns: list[CategoryShareBreakdown] = []
    for category in categories:
        team_opportunities = (
            team_tendencies.pass_attempts_per_game
            if category.name in ("receiving", "passing")
            else team_tendencies.rush_attempts_per_game
        )

        share_key = f"{category.name}_share"
        current_shares = [g[share_key] for g in current_season_games if g.get(share_key) is not None]
        prior_shares = (
            [g[share_key] for g in prior_season_games if g.get(share_key) is not None]
            if prior_season_games else None
        )

        role_rank_prior_share = rank_priors.get(category.name)
        workload_stat = CATEGORY_TO_WORKLOAD_STAT.get(category.name)
        opportunity_column = CATEGORY_TO_OPPORTUNITY_COLUMN[category.name]
        total_career_opportunities = _career_opportunity_total(career_seasons, opportunity_column)

        if workload_stat is not None:
            effective_workload = compute_effective_prior(
                career_value=career_prior.workload.get(workload_stat),
                total_career_opportunities=total_career_opportunities,
                fallback_value=role_rank_prior_share,
                full_confidence_opportunities=WORKLOAD_FULL_CONFIDENCE_OPPORTUNITIES.get(category.name),
            )
            career_workload_prior[workload_stat] = effective_workload
            role_rank_prior_share = effective_workload.effective_value

        expected_share = estimate_player_share(
            current_shares, prior_shares, role_rank_prior_share, team_changed, role.role_changed_recently
        )

        expected_opportunities = (
            team_opportunities * expected_share
            if team_opportunities is not None and expected_share is not None
            else None
        )

        category_priors = position_efficiency_priors.get(category.name, {})
        category_points = 0.0
        shrunk_rates: dict[str, float] = {}
        if expected_opportunities is not None:
            for rate_name in category.rate_specs:
                position_rate_avg = category_priors.get(rate_name)
                career_talent_key = CAREER_TALENT_KEY_BY_CATEGORY_RATE[(category.name, rate_name)]

                career_talent_value = (
                    career_prior.talent.get(career_talent_key) if career_talent_key is not None else None
                )
                effective_talent = compute_effective_prior(
                    career_value=career_talent_value,
                    total_career_opportunities=total_career_opportunities,
                    fallback_value=position_rate_avg,
                    full_confidence_opportunities=TALENT_FULL_CONFIDENCE_OPPORTUNITIES.get(category.name),
                )
                if career_talent_key is not None:
                    career_talent_prior[career_talent_key] = effective_talent

                if effective_talent.effective_value is None:
                    continue

                points_per_unit = getattr(scoring_rules, SCORING_FIELD_BY_CATEGORY_RATE[(category.name, rate_name)])
                player_rates = extract_player_rate_series(current_season_games, category, rate_name)
                shrunk_rate = estimate_player_efficiency(
                    player_rates, effective_talent.effective_value, team_changed=team_changed,
                )
                shrunk_rates[rate_name] = shrunk_rate
                category_points += expected_opportunities * shrunk_rate * points_per_unit

        total_points += category_points
        category_breakdowns.append(
            CategoryShareBreakdown(
                name=category.name, expected_team_opportunities=team_opportunities,
                expected_share=expected_share, expected_opportunities=expected_opportunities,
                points=category_points, shrunk_rates=shrunk_rates,
            )
        )

    any_category_resolved = any(c.expected_opportunities is not None for c in category_breakdowns)
    final_points = total_points if any_category_resolved else None

    is_conflict, conflict_reason = (
        detect_projection_conflict(
            final_points, platform_points, availability_status, team_changed, role.role_confidence,
            qb_changed=qb_context.qb_changed,
        )
        if final_points is not None
        else (False, None)
    )

    return CareerAwareBreakdown(
        total_points=final_points, categories=category_breakdowns,
        availability_status=availability_status, team_changed=team_changed,
        role_confidence=role.role_confidence, role_changed_recently=role.role_changed_recently,
        projection_conflict=is_conflict, conflict_reason=conflict_reason,
        career_talent_prior=career_talent_prior, career_workload_prior=career_workload_prior,
        qb_context=qb_context, current_team=current_team, prior_season_team=prior_season_team,
        team_offense=team_tendencies,
    )
