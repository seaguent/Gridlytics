import asyncio
import sys

from app.db import async_session
from app.sleeper.adapter import sync_league
from app.sleeper.client import SleeperClient


async def main(league_id: str) -> None:
    client = SleeperClient()
    async with async_session() as session:
        league = await sync_league(session, client, league_id)
        print(f"Synced: {league.name} ({league.season}, {league.status})")
    await client.aclose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/sync_sleeper_league.py <league_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
