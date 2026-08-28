import httpx

from app.sleeper.schemas import SleeperLeague, SleeperMatchup, SleeperRoster, SleeperUser

SLEEPER_BASE_URL = "https://api.sleeper.app/v1"


class SleeperClient:
    def __init__(self, base_url: str = SLEEPER_BASE_URL) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=10.0)

    async def get_league(self, league_id: str) -> SleeperLeague:
        response = await self._client.get(f"/league/{league_id}")
        response.raise_for_status()
        return SleeperLeague.model_validate(response.json())

    async def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        response = await self._client.get(f"/league/{league_id}/rosters")
        response.raise_for_status()
        return [SleeperRoster.model_validate(item) for item in response.json()]

    async def get_matchups(self, league_id: str, week: int) -> list[SleeperMatchup]:
        response = await self._client.get(f"/league/{league_id}/matchups/{week}")
        response.raise_for_status()
        return [SleeperMatchup.model_validate(item) for item in response.json()]

    async def get_users(self, league_id: str) -> list[SleeperUser]:
        response = await self._client.get(f"/league/{league_id}/users")
        response.raise_for_status()
        return [SleeperUser.model_validate(item) for item in response.json()]

    async def aclose(self) -> None:
        await self._client.aclose()
