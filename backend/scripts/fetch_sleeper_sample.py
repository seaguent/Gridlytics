import asyncio
import sys

from app.sleeper.client import SleeperClient


async def main(league_id: str) -> None:
    client = SleeperClient()
    try:
        league = await client.get_league(league_id)
        print(f"League: {league.name} ({league.season}, {league.status})")

        rosters = await client.get_rosters(league_id)
        print(f"Rosters: {len(rosters)}")
        for roster in rosters[:3]:
            print(f"  roster_id={roster.roster_id} wins={roster.settings.wins}")

        users = await client.get_users(league_id)
        print(f"Users: {len(users)}")
        for user in users[:3]:
            print(f"  {user.display_name}")

        matchups = await client.get_matchups(league_id, week=1)
        print(f"Week 1 matchups: {len(matchups)}")
    finally:
        await client.aclose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/fetch_sleeper_sample.py <league_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
