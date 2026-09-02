from app.projections.availability import classify_availability


def gate_availability(injury_status: str | None, is_bye: bool) -> tuple[bool, str]:
    status = classify_availability(injury_status, is_bye)
    return status == "unavailable", status
