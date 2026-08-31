import pytest

from app.projections.ensemble import EnsembleProjectionProvider
from app.projections.models import PlayerProjection


class _FakeProvider:
    def __init__(self, projections: list[PlayerProjection]) -> None:
        self._projections = projections

    async def get_projections(self, session, league) -> list[PlayerProjection]:
        return self._projections


@pytest.mark.asyncio
async def test_ensemble_averages_across_providers_that_agree_on_a_player():
    provider_a = _FakeProvider(
        [PlayerProjection("100", "Player A", "RB", 18.2, ["espn"])]
    )
    provider_b = _FakeProvider(
        [PlayerProjection("100", "Player A", "RB", 18.5, ["historical_weighted_average"])]
    )

    ensemble = EnsembleProjectionProvider([provider_a, provider_b])
    projections = await ensemble.get_projections(session=None, league=None)

    assert len(projections) == 1
    assert projections[0].projected_points == (18.2 + 18.5) / 2
    assert "espn" in projections[0].sources
    assert "historical_weighted_average" in projections[0].sources


@pytest.mark.asyncio
async def test_ensemble_falls_back_to_whichever_provider_has_a_player():
    provider_a = _FakeProvider([PlayerProjection("100", "Player A", "RB", 18.2, ["espn"])])
    provider_b = _FakeProvider(
        [PlayerProjection("200", "Player B", "WR", 12.0, ["historical_weighted_average"])]
    )

    ensemble = EnsembleProjectionProvider([provider_a, provider_b])
    projections = await ensemble.get_projections(session=None, league=None)

    by_id = {p.platform_player_id: p for p in projections}
    assert len(by_id) == 2
    assert by_id["100"].projected_points == 18.2
    assert by_id["200"].projected_points == 12.0


@pytest.mark.asyncio
async def test_ensemble_averages_floor_ceiling_confidence_from_providers_that_have_them():
    # provider_a has no distribution data (e.g. ESPN); provider_b does.
    provider_a = _FakeProvider([PlayerProjection("100", "Player A", "RB", 18.2, ["espn"])])
    provider_b = _FakeProvider(
        [
            PlayerProjection(
                "100",
                "Player A",
                "RB",
                18.5,
                ["historical_weighted_average"],
                floor=12.0,
                ceiling=24.0,
                confidence=0.8,
            )
        ]
    )

    ensemble = EnsembleProjectionProvider([provider_a, provider_b])
    projections = await ensemble.get_projections(session=None, league=None)

    assert projections[0].floor == 12.0
    assert projections[0].ceiling == 24.0
    assert projections[0].confidence == 0.8
