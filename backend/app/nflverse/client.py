import io

import httpx
import pandas as pd

NFLVERSE_RELEASES_BASE_URL = "https://github.com/nflverse/nflverse-data/releases/download"
# dynastyprocess/data fills the sleeper_id gap nflverse's own crosswalk doesn't have.
DYNASTYPROCESS_IDS_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"


class NflverseClient:
    def __init__(self, base_url: str = NFLVERSE_RELEASES_BASE_URL) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0, follow_redirects=True)

    async def get_player_crosswalk(self) -> pd.DataFrame:
        response = await self._client.get("/players/players.csv")
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content), low_memory=False)

    async def get_weekly_stats(self, season: str) -> pd.DataFrame:
        response = await self._client.get(f"/stats_player/stats_player_week_{season}.csv")
        if response.status_code == 404:
            # A not-yet-started season has no file published yet -- expected, not an error.
            return pd.DataFrame()
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content), low_memory=False)

    async def get_season_stats(self, season: str) -> pd.DataFrame:
        response = await self._client.get(f"/stats_player/stats_player_reg_{season}.csv")
        if response.status_code == 404:
            return pd.DataFrame()
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content), low_memory=False)

    async def get_sleeper_crosswalk(self) -> pd.DataFrame:
        response = await self._client.get(DYNASTYPROCESS_IDS_URL)
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content), low_memory=False)

    async def get_snap_counts(self, season: str) -> pd.DataFrame:
        response = await self._client.get(f"/snap_counts/snap_counts_{season}.csv")
        if response.status_code == 404:
            return pd.DataFrame()
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content), low_memory=False)

    async def get_schedule(self, season: str) -> pd.DataFrame:
        response = await self._client.get("/schedules/games.csv")
        response.raise_for_status()
        schedule = pd.read_csv(io.BytesIO(response.content), low_memory=False)
        return schedule[schedule["season"] == int(season)]

    async def get_play_by_play(self, season: str) -> pd.DataFrame:
        response = await self._client.get(f"/pbp/play_by_play_{season}.csv.gz", timeout=60.0)
        if response.status_code == 404:
            return pd.DataFrame()
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content), compression="gzip", low_memory=False)

    async def aclose(self) -> None:
        await self._client.aclose()
