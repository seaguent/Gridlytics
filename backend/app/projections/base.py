from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League
from app.projections.models import PlayerProjection


class ProjectionProvider(Protocol):
    async def get_projections(self, session: AsyncSession, league: League) -> list[PlayerProjection]: ...
