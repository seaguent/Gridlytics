from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League
from app.projections.base import ProjectionProvider
from app.projections.models import PlayerProjection


def _average_non_none(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


class EnsembleProjectionProvider:
    def __init__(self, providers: list[ProjectionProvider]) -> None:
        self.providers = providers

    async def get_projections(self, session: AsyncSession, league: League) -> list[PlayerProjection]:
        by_player: dict[str, list[PlayerProjection]] = {}
        for provider in self.providers:
            for projection in await provider.get_projections(session, league):
                by_player.setdefault(projection.platform_player_id, []).append(projection)

        ensemble = []
        for platform_player_id, projections in by_player.items():
            representative = projections[0]
            sources: list[str] = []
            for projection in projections:
                for source in projection.sources:
                    if source not in sources:
                        sources.append(source)

            ensemble.append(
                PlayerProjection(
                    platform_player_id=platform_player_id,
                    name=representative.name,
                    position=representative.position,
                    projected_points=sum(p.projected_points for p in projections) / len(projections),
                    sources=sources,
                    floor=_average_non_none([p.floor for p in projections]),
                    ceiling=_average_non_none([p.ceiling for p in projections]),
                    confidence=_average_non_none([p.confidence for p in projections]),
                )
            )
        return ensemble
