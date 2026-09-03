from pydantic import BaseModel, ConfigDict


class EspnPlayerStat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scoringPeriodId: int | None = None
    statSourceId: int | None = None
    appliedTotal: float | None = None


class EspnPlayer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fullName: str | None = None
    defaultPositionId: int | None = None
    proTeamId: int | None = None
    injuryStatus: str | None = None
    stats: list[EspnPlayerStat] = []


class EspnPlayerPoolEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    player: EspnPlayer = EspnPlayer()


class EspnRosterEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    playerId: int
    lineupSlotId: int
    playerPoolEntry: EspnPlayerPoolEntry = EspnPlayerPoolEntry()


class EspnRoster(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entries: list[EspnRosterEntry] = []


class EspnRecordOverall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    wins: int = 0
    losses: int = 0
    ties: int = 0
    pointsFor: float = 0
    pointsAgainst: float = 0


class EspnRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    overall: EspnRecordOverall = EspnRecordOverall()


class EspnTeam(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    location: str | None = None
    nickname: str | None = None
    owners: list[str] = []
    record: EspnRecord = EspnRecord()
    roster: EspnRoster = EspnRoster()


class EspnScheduleTeam(BaseModel):
    model_config = ConfigDict(extra="ignore")

    teamId: int | None = None
    totalPoints: float = 0


class EspnScheduleEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    matchupPeriodId: int
    home: EspnScheduleTeam = EspnScheduleTeam()
    away: EspnScheduleTeam | None = None


class EspnRosterSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lineupSlotCounts: dict[str, int] = {}


class EspnScheduleSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    matchupPeriodCount: int = 14
    playoffTeamCount: int = 6


class EspnScoringItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    statId: int | None = None
    points: float | None = None


class EspnScoringSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scoringItems: list[EspnScoringItem] = []


class EspnSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    rosterSettings: EspnRosterSettings = EspnRosterSettings()
    scheduleSettings: EspnScheduleSettings = EspnScheduleSettings()
    scoringSettings: EspnScoringSettings = EspnScoringSettings()


class EspnMember(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    displayName: str | None = None


class EspnStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    currentMatchupPeriod: int = 1
    isActive: bool = True


class EspnLeagueResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    seasonId: int | None = None
    status: EspnStatus = EspnStatus()
    settings: EspnSettings = EspnSettings()
    teams: list[EspnTeam] = []
    schedule: list[EspnScheduleEntry] = []
    members: list[EspnMember] = []


class EspnFreeAgentEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    onTeamId: int = 0
    player: EspnPlayer = EspnPlayer()


class EspnFreeAgentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    players: list[EspnFreeAgentEntry] = []
