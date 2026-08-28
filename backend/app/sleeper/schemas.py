from pydantic import BaseModel, ConfigDict


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


class SleeperUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    display_name: str
    metadata: dict = {}
