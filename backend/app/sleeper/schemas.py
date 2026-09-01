from pydantic import BaseModel, ConfigDict


class SleeperLeagueSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    leg: int = 1
    playoff_teams: int = 6
    playoff_week_start: int = 15


class SleeperLeague(BaseModel):
    model_config = ConfigDict(extra="ignore")

    league_id: str
    name: str
    season: str
    season_type: str
    sport: str
    status: str
    total_rosters: int
    previous_league_id: str | None = None
    roster_positions: list[str] = []
    settings: SleeperLeagueSettings = SleeperLeagueSettings()
    scoring_settings: dict = {}


class SleeperRosterSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    wins: int = 0
    losses: int = 0
    ties: int = 0
    fpts: float = 0
    fpts_decimal: int = 0
    fpts_against: float = 0
    fpts_against_decimal: int = 0


class SleeperRoster(BaseModel):
    model_config = ConfigDict(extra="ignore")

    roster_id: int
    owner_id: str | None = None
    league_id: str
    players: list[str] = []
    starters: list[str] = []
    settings: SleeperRosterSettings


class SleeperMatchup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    roster_id: int
    matchup_id: int | None = None
    points: float = 0
    starters: list[str] = []
    players: list[str] = []
    players_points: dict[str, float] = {}


class SleeperUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    display_name: str
    metadata: dict = {}


class SleeperPlayer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    position: str | None = None
    full_name: str | None = None
    gsis_id: str | None = None
    team: str | None = None
    injury_status: str | None = None


class SleeperProjectionStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pts_std: float | None = None
    pts_half_ppr: float | None = None
    pts_ppr: float | None = None


class SleeperProjectionPlayer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    first_name: str | None = None
    last_name: str | None = None
    position: str | None = None


class SleeperProjection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    player_id: str
    week: int
    stats: SleeperProjectionStats = SleeperProjectionStats()
    player: SleeperProjectionPlayer | None = None
