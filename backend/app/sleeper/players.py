from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Player
from app.sleeper.client import SleeperClient


async def sync_players(session: AsyncSession, client: SleeperClient) -> None:
    raw_players = await client.get_all_players()

    result = await session.execute(select(Player).where(Player.platform == "sleeper"))
    existing = {player.platform_player_id: player for player in result.scalars()}

    for platform_player_id, raw in raw_players.items():
        if raw.position is None:
            continue

        name = raw.full_name or platform_player_id
        player = existing.get(platform_player_id)
        if player is None:
            session.add(
                Player(
                    platform="sleeper",
                    platform_player_id=platform_player_id,
                    position=raw.position,
                    name=name,
                    gsis_id=raw.gsis_id,
                    team=raw.team,
                    injury_status=raw.injury_status,
                )
            )
        else:
            player.position = raw.position
            player.name = name
            player.gsis_id = raw.gsis_id
            player.team = raw.team
            player.injury_status = raw.injury_status

    await session.commit()
