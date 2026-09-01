STANDARD_PASS_TDS = {4.0}
STANDARD_PASS_YD_RATES = {0.04, 0.05}
STANDARD_RUSH_REC_YD_RATE = 0.1


def detect_custom_scoring(scoring_settings: dict) -> tuple[bool, list[str]]:
    reasons = []

    bonus_keys = [k for k, v in scoring_settings.items() if k.startswith("bonus_") and v]
    if bonus_keys:
        reasons.append(f"bonus scoring active: {', '.join(sorted(bonus_keys))}")

    pass_td = scoring_settings.get("pass_td")
    if pass_td is not None and pass_td not in STANDARD_PASS_TDS:
        reasons.append(f"non-standard pass_td value: {pass_td}")

    pass_yd = scoring_settings.get("pass_yd")
    if pass_yd is not None and pass_yd not in STANDARD_PASS_YD_RATES:
        reasons.append(f"non-standard pass_yd rate: {pass_yd}")

    for key in ("rush_yd", "rec_yd"):
        value = scoring_settings.get(key)
        if value is not None and value != STANDARD_RUSH_REC_YD_RATE:
            reasons.append(f"non-standard {key} rate: {value}")

    return bool(reasons), reasons
