from dataclasses import dataclass

# Real, community-verified ESPN fantasy statId -> stat name mapping (cwendt94/espn-api project,
# a widely-used open-source ESPN fantasy API wrapper). Not yet confirmed against a live raw ESPN
# response from this app's own auth -- this sandbox has no ESPN browser session to verify against.
ESPN_STAT_ID_TO_FIELD = {
    3: "pass_yard_points",
    4: "pass_td_points",
    20: "pass_int_points",
    24: "rush_yard_points",
    25: "rush_td_points",
    41: "reception_points",
    42: "rec_yard_points",
    43: "rec_td_points",
}


@dataclass(frozen=True)
class ScoringRules:
    pass_yard_points: float = 0.04
    pass_td_points: float = 4.0
    pass_int_points: float = -2.0
    rush_yard_points: float = 0.1
    rush_td_points: float = 6.0
    rec_yard_points: float = 0.1
    rec_td_points: float = 6.0
    reception_points: float = 1.0


STANDARD_PPR = ScoringRules()


def scoring_rules_from_sleeper(scoring_settings: dict) -> ScoringRules:
    return ScoringRules(
        pass_yard_points=scoring_settings.get("pass_yd", STANDARD_PPR.pass_yard_points),
        pass_td_points=scoring_settings.get("pass_td", STANDARD_PPR.pass_td_points),
        pass_int_points=scoring_settings.get("pass_int", STANDARD_PPR.pass_int_points),
        rush_yard_points=scoring_settings.get("rush_yd", STANDARD_PPR.rush_yard_points),
        rush_td_points=scoring_settings.get("rush_td", STANDARD_PPR.rush_td_points),
        rec_yard_points=scoring_settings.get("rec_yd", STANDARD_PPR.rec_yard_points),
        rec_td_points=scoring_settings.get("rec_td", STANDARD_PPR.rec_td_points),
        reception_points=scoring_settings.get("rec", STANDARD_PPR.reception_points),
    )


def scoring_rules_from_espn(scoring_settings: dict) -> ScoringRules:
    items = scoring_settings.get("scoring_items", [])
    overrides: dict[str, float] = {}
    for item in items:
        field = ESPN_STAT_ID_TO_FIELD.get(item.get("stat_id"))
        if field is None or item.get("points") is None:
            continue
        overrides[field] = item["points"]

    # Never silently claim league-specific accuracy for a field we couldn't parse -- fields not
    # present in overrides fall back explicitly to STANDARD_PPR's own value, field by field.
    return ScoringRules(
        pass_yard_points=overrides.get("pass_yard_points", STANDARD_PPR.pass_yard_points),
        pass_td_points=overrides.get("pass_td_points", STANDARD_PPR.pass_td_points),
        pass_int_points=overrides.get("pass_int_points", STANDARD_PPR.pass_int_points),
        rush_yard_points=overrides.get("rush_yard_points", STANDARD_PPR.rush_yard_points),
        rush_td_points=overrides.get("rush_td_points", STANDARD_PPR.rush_td_points),
        rec_yard_points=overrides.get("rec_yard_points", STANDARD_PPR.rec_yard_points),
        rec_td_points=overrides.get("rec_td_points", STANDARD_PPR.rec_td_points),
        reception_points=overrides.get("reception_points", STANDARD_PPR.reception_points),
    )


def scoring_rules_for_league(platform: str, scoring_settings: dict) -> ScoringRules:
    if platform == "sleeper":
        return scoring_rules_from_sleeper(scoring_settings)
    if platform == "espn":
        return scoring_rules_from_espn(scoring_settings)
    return STANDARD_PPR
