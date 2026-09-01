UNAVAILABLE_STATUSES = {"OUT", "IR", "INJURY_RESERVE", "PUP", "NFI", "SUS", "SUSPENSION", "SUSPENDED", "NA"}
DOUBTFUL_STATUSES = {"DOUBTFUL"}
# COV/DNR are real Sleeper codes without a fully confirmed meaning -- treated as a cautious risk flag, not "out".
QUESTIONABLE_STATUSES = {"QUESTIONABLE", "DAY_TO_DAY", "COV", "DNR"}


def classify_availability(injury_status: str | None, is_bye: bool) -> str:
    if is_bye:
        return "unavailable"

    normalized = (injury_status or "").strip().upper()
    if normalized in UNAVAILABLE_STATUSES:
        return "unavailable"
    if normalized in DOUBTFUL_STATUSES:
        return "doubtful"
    if normalized in QUESTIONABLE_STATUSES:
        return "questionable"
    return "healthy"
