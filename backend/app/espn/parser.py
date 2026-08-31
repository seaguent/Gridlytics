from app.espn.schemas import EspnLeagueResponse

POSITION_ID_MAP = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}

LINEUP_SLOT_ID_MAP = {
    0: "QB",
    2: "RB",
    4: "WR",
    6: "TE",
    23: "FLEX",
    16: "DEF",
    17: "K",
    20: "BN",
    21: "IR",
    25: "SUPER_FLEX",
}

STARTER_SLOT_IDS = {0, 2, 4, 6, 23, 16, 17, 25}


def parse_roster_positions(lineup_slot_counts: dict[str, int]) -> list[str]:
    positions = []
    for slot_id_str, count in lineup_slot_counts.items():
        slot_name = LINEUP_SLOT_ID_MAP.get(int(slot_id_str))
        if slot_name is None:
            continue
        positions.extend([slot_name] * count)
    return positions


def parse_league(raw: EspnLeagueResponse) -> dict:
    playoff_week_start = raw.settings.scheduleSettings.matchupPeriodCount + 1
    return {
        "platform_league_id": str(raw.id),
        "season": str(raw.seasonId) if raw.seasonId else "",
        "name": raw.settings.name or "",
        "status": "in_season" if raw.status.isActive else "complete",
        "roster_positions": parse_roster_positions(raw.settings.rosterSettings.lineupSlotCounts),
        "current_week": raw.status.currentMatchupPeriod,
        "playoff_teams": raw.settings.scheduleSettings.playoffTeamCount,
        "playoff_week_start": playoff_week_start,
    }


def parse_teams(raw: EspnLeagueResponse) -> list[dict]:
    teams = []
    for team in raw.teams:
        display_name = team.name or f"{team.location or ''} {team.nickname or ''}".strip() or (
            f"Team {team.id}"
        )
        teams.append(
            {
                "platform_team_id": str(team.id),
                "platform_owner_id": team.owners[0] if team.owners else None,
                "display_name": display_name,
                "wins": team.record.overall.wins,
                "losses": team.record.overall.losses,
                "ties": team.record.overall.ties,
                "points_for": team.record.overall.pointsFor,
                "points_against": team.record.overall.pointsAgainst,
            }
        )
    return teams


def parse_matchups(raw: EspnLeagueResponse) -> list[dict]:
    matchups = []
    for entry in raw.schedule:
        if entry.home.teamId is not None:
            matchups.append(
                {
                    "week": entry.matchupPeriodId,
                    "platform_matchup_id": entry.matchupPeriodId,
                    "platform_team_id": str(entry.home.teamId),
                    "points": entry.home.totalPoints,
                }
            )
        if entry.away is not None and entry.away.teamId is not None:
            matchups.append(
                {
                    "week": entry.matchupPeriodId,
                    "platform_matchup_id": entry.matchupPeriodId,
                    "platform_team_id": str(entry.away.teamId),
                    "points": entry.away.totalPoints,
                }
            )
    return matchups


def parse_rosters(raw: EspnLeagueResponse) -> list[dict]:
    roster_slots = []
    for team in raw.teams:
        for entry in team.roster.entries:
            player = entry.playerPoolEntry.player
            roster_slots.append(
                {
                    "platform_team_id": str(team.id),
                    "platform_player_id": str(entry.playerId),
                    "player_name": player.fullName or f"Player {entry.playerId}",
                    "position": POSITION_ID_MAP.get(player.defaultPositionId, "UNKNOWN"),
                    "is_starter": entry.lineupSlotId in STARTER_SLOT_IDS,
                }
            )
    return roster_slots


PROJECTED_STAT_SOURCE_ID = 1


def parse_projections(raw: EspnLeagueResponse) -> list[dict]:
    current_period = raw.status.currentMatchupPeriod
    seen_player_ids: set[str] = set()
    projections = []

    for team in raw.teams:
        for entry in team.roster.entries:
            platform_player_id = str(entry.playerId)
            if platform_player_id in seen_player_ids:
                continue

            player = entry.playerPoolEntry.player
            projected_stat = next(
                (
                    stat
                    for stat in player.stats
                    if stat.statSourceId == PROJECTED_STAT_SOURCE_ID
                    and stat.scoringPeriodId == current_period
                    and stat.appliedTotal is not None
                ),
                None,
            )
            if projected_stat is None:
                continue

            seen_player_ids.add(platform_player_id)
            projections.append(
                {
                    "platform_player_id": platform_player_id,
                    "name": player.fullName or f"Player {entry.playerId}",
                    "position": POSITION_ID_MAP.get(player.defaultPositionId, "UNKNOWN"),
                    "projected_points": projected_stat.appliedTotal,
                }
            )
    return projections
