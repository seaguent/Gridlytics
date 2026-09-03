from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.espn.parser import parse_free_agents
from app.espn.schemas import EspnFreeAgentResponse
from app.models import League
from app.nflverse.client import NflverseClient
from app.nflverse.crosswalk import build_espn_lookup
from app.projections.value import FIXED_POSITIONS
from app.sleeper.adapter import _scoring_field
from app.sleeper.client import SleeperClient

_SLOT_POSITIONS = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"}, "K": {"K"}, "DEF": {"DEF"},
    "FLEX": {"RB", "WR", "TE"}, "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}


@dataclass
class AvailablePlayerCandidate:
    platform_player_id: str
    gsis_id: str | None
    name: str
    position: str
    team: str | None
    injury_status: str | None
    platform_projection: float | None


def passes_basic_prefilter(
    candidate: AvailablePlayerCandidate, fantasy_positions: set[str], rostered_ids: set[str]
) -> bool:
    if candidate.position not in fantasy_positions:
        return False
    if candidate.team is None:
        return False
    if candidate.platform_player_id in rostered_ids:
        return False
    return True


class SleeperAvailablePlayerProvider:
    async def get_available_players(self, session: AsyncSession, league: League) -> list[AvailablePlayerCandidate]:
        if league.platform != "sleeper":
            return []

        client = SleeperClient()
        try:
            all_players = await client.get_all_players()
            rosters = await client.get_rosters(league.platform_league_id)
            rostered_ids = {pid for roster in rosters for pid in roster.players}

            projections = await client.get_projections(league.season, league.current_week)
            field = _scoring_field(league.scoring_settings)
            projection_by_id = {
                p.player_id: getattr(p.stats, field) for p in projections if getattr(p.stats, field) is not None
            }
        finally:
            await client.aclose()

        fantasy_positions = FIXED_POSITIONS & {
            position for slot in league.roster_positions for position in _SLOT_POSITIONS.get(slot, set())
        }

        candidates = []
        for player_id, player in all_players.items():
            if player.position is None:
                continue
            candidate = AvailablePlayerCandidate(
                platform_player_id=player_id,
                gsis_id=player.gsis_id,
                name=player.full_name or player_id,
                position=player.position,
                team=player.team,
                injury_status=player.injury_status,
                platform_projection=projection_by_id.get(player_id),
            )
            if passes_basic_prefilter(candidate, fantasy_positions, rostered_ids):
                candidates.append(candidate)
        return candidates


class EspnAuthError(Exception):
    """Raised when an ESPN league has no free-agent data because the browser's ESPN session
    couldn't fetch it (expired login, private league, or the extension never pushed a payload)."""


class EspnAvailablePlayerProvider:
    def __init__(self, espn_lookup: dict[str, str] | None = None) -> None:
        # espn_lookup is the same shape build_espn_lookup(crosswalk) produces (ESPN's own numeric
        # player id -> gsis_id). When the caller already loaded the crosswalk for this request
        # (e.g. compute_waiver_recommendations, which also needs it for teammate availability),
        # it's passed in here instead of this provider fetching /players.csv a second time. Left
        # as None, this provider fetches it itself -- exactly the old, still-correct behavior,
        # kept for any caller that doesn't need to share the lookup with anything else.
        self._espn_lookup = espn_lookup

    async def get_available_players(
        self, session: AsyncSession, league: League, raw_free_agents_data: dict | None = None
    ) -> list[AvailablePlayerCandidate]:
        if league.platform != "espn":
            return []
        if raw_free_agents_data is None:
            raise EspnAuthError(
                "ESPN free-agent data unavailable -- reconnect ESPN in the extension and try again"
            )

        raw = EspnFreeAgentResponse.model_validate(raw_free_agents_data)
        free_agents = parse_free_agents(raw, league.current_week)

        if self._espn_lookup is not None:
            espn_to_gsis = self._espn_lookup
        else:
            nflverse_client = NflverseClient()
            try:
                crosswalk = await nflverse_client.get_player_crosswalk()
            finally:
                await nflverse_client.aclose()
            espn_to_gsis = build_espn_lookup(crosswalk)

        fantasy_positions = FIXED_POSITIONS & {
            position for slot in league.roster_positions for position in _SLOT_POSITIONS.get(slot, set())
        }

        candidates = []
        for fa in free_agents:
            candidate = AvailablePlayerCandidate(
                platform_player_id=fa["platform_player_id"],
                gsis_id=espn_to_gsis.get(fa["platform_player_id"]),
                name=fa["name"],
                position=fa["position"],
                team=fa["team"],
                injury_status=fa["injury_status"],
                platform_projection=fa["projected_points"],
            )
            if passes_basic_prefilter(candidate, fantasy_positions, rostered_ids=set()):
                candidates.append(candidate)
        return candidates
