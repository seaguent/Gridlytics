import httpx
import pytest
import respx

from app.models import League
from app.nflverse.client import NFLVERSE_RELEASES_BASE_URL
from app.projections.available_players import (
    AvailablePlayerCandidate,
    EspnAuthError,
    EspnAvailablePlayerProvider,
    SleeperAvailablePlayerProvider,
    passes_basic_prefilter,
)
from app.sleeper.client import SLEEPER_BASE_URL, SLEEPER_PROJECTIONS_BASE_URL


def _candidate(**overrides) -> AvailablePlayerCandidate:
    fields = dict(
        platform_player_id="p1", gsis_id="00-001", name="Test Player", position="WR",
        team="KC", injury_status=None, platform_projection=8.0,
    )
    fields.update(overrides)
    return AvailablePlayerCandidate(**fields)


def test_passes_basic_prefilter_accepts_fantasy_relevant_unrostered_active_player():
    candidate = _candidate()
    assert passes_basic_prefilter(candidate, fantasy_positions={"QB", "RB", "WR", "TE"}, rostered_ids=set())


def test_passes_basic_prefilter_rejects_non_fantasy_position():
    candidate = _candidate(position="LB")
    assert not passes_basic_prefilter(candidate, fantasy_positions={"QB", "RB", "WR", "TE"}, rostered_ids=set())


def test_passes_basic_prefilter_rejects_player_with_no_current_team():
    candidate = _candidate(team=None)
    assert not passes_basic_prefilter(candidate, fantasy_positions={"QB", "RB", "WR", "TE"}, rostered_ids=set())


def test_passes_basic_prefilter_rejects_already_rostered_player():
    candidate = _candidate(platform_player_id="p1")
    assert not passes_basic_prefilter(
        candidate, fantasy_positions={"QB", "RB", "WR", "TE"}, rostered_ids={"p1"}
    )


def _league() -> League:
    return League(
        platform="sleeper", platform_league_id="123", season="2026", name="L",
        status="in_season", current_week=2, roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN"],
        scoring_settings={"rec": 1.0},
    )


@pytest.mark.asyncio
@respx.mock
async def test_sleeper_available_player_provider_excludes_rostered_and_inactive(db_session):
    respx.get(f"{SLEEPER_BASE_URL}/players/nfl").mock(
        return_value=httpx.Response(
            200,
            json={
                "fa1": {"position": "WR", "full_name": "Free Agent WR", "gsis_id": "00-100", "team": "KC"},
                "rostered1": {"position": "WR", "full_name": "Rostered WR", "gsis_id": "00-200", "team": "SF"},
                "retired1": {"position": "WR", "full_name": "No Team WR", "gsis_id": "00-300", "team": None},
            },
        )
    )
    respx.get(f"{SLEEPER_BASE_URL}/league/123/rosters").mock(
        return_value=httpx.Response(
            200,
            json=[{"roster_id": 1, "league_id": "123", "players": ["rostered1"], "settings": {}}],
        )
    )
    respx.get(f"{SLEEPER_PROJECTIONS_BASE_URL}/2026/2").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"player_id": "fa1", "week": 2, "stats": {"pts_ppr": 9.5},
                 "player": {"first_name": "Free", "last_name": "Agent", "position": "WR"}},
            ],
        )
    )

    provider = SleeperAvailablePlayerProvider()
    candidates = await provider.get_available_players(db_session, _league())

    ids = {c.platform_player_id for c in candidates}
    assert ids == {"fa1"}
    fa = candidates[0]
    assert fa.platform_projection == pytest.approx(9.5)
    assert fa.gsis_id == "00-100"


def _espn_league() -> League:
    return League(
        platform="espn", platform_league_id="1", season="2026", name="L",
        status="in_season", current_week=2, roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN"],
    )


def _espn_player(
    player_id: int,
    *,
    on_team_id: int = 0,
    full_name: str = "Test Player",
    position_id: int = 3,
    team_id: int | None = 12,
    injury_status: str | None = None,
    stats: list[dict] | None = None,
) -> dict:
    return {
        "id": player_id,
        "onTeamId": on_team_id,
        "player": {
            "fullName": full_name,
            "defaultPositionId": position_id,
            "proTeamId": team_id,
            "injuryStatus": injury_status,
            "stats": stats or [],
        },
    }


def _mock_espn_crosswalk(rows: str = "gsis_id,display_name,espn_id,pfr_id,position\n") -> None:
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/players/players.csv").mock(
        return_value=httpx.Response(200, text=rows)
    )


@pytest.mark.asyncio
@respx.mock
async def test_espn_provider_returns_available_free_agent_with_resolved_gsis_id(db_session):
    _mock_espn_crosswalk(
        "gsis_id,display_name,espn_id,pfr_id,position\n00-0100,Free Agent WR,555,FreeAg00,WR\n"
    )
    raw = {
        "players": [
            _espn_player(555, full_name="Free Agent WR", stats=[
                {"scoringPeriodId": 2, "statSourceId": 1, "appliedTotal": 8.5}
            ]),
        ]
    }

    provider = EspnAvailablePlayerProvider()
    candidates = await provider.get_available_players(db_session, _espn_league(), raw)

    assert len(candidates) == 1
    fa = candidates[0]
    assert fa.platform_player_id == "555"
    assert fa.name == "Free Agent WR"
    assert fa.position == "WR"
    assert fa.team == "KC"
    assert fa.gsis_id == "00-0100"


@pytest.mark.asyncio
@respx.mock
async def test_espn_provider_excludes_rostered_player(db_session):
    _mock_espn_crosswalk()
    raw = {
        "players": [
            _espn_player(555, on_team_id=0, full_name="Free Agent WR"),
            _espn_player(600, on_team_id=3, full_name="Rostered WR"),
        ]
    }

    provider = EspnAvailablePlayerProvider()
    candidates = await provider.get_available_players(db_session, _espn_league(), raw)

    ids = {c.platform_player_id for c in candidates}
    assert ids == {"555"}


@pytest.mark.asyncio
@respx.mock
async def test_espn_provider_captures_current_week_projection(db_session):
    _mock_espn_crosswalk()
    raw = {
        "players": [
            _espn_player(555, stats=[
                {"scoringPeriodId": 1, "statSourceId": 1, "appliedTotal": 99.0},  # wrong week
                {"scoringPeriodId": 2, "statSourceId": 0, "appliedTotal": 5.0},  # actual, not projected
                {"scoringPeriodId": 2, "statSourceId": 1, "appliedTotal": 11.5},  # the real projection
            ]),
        ]
    }

    provider = EspnAvailablePlayerProvider()
    candidates = await provider.get_available_players(db_session, _espn_league(), raw)

    assert candidates[0].platform_projection == pytest.approx(11.5)


@pytest.mark.asyncio
@respx.mock
async def test_espn_provider_keeps_rookie_free_agent_with_no_projection_or_history(db_session):
    _mock_espn_crosswalk()
    raw = {"players": [_espn_player(555, full_name="Undrafted Rookie WR", stats=[])]}

    provider = EspnAvailablePlayerProvider()
    candidates = await provider.get_available_players(db_session, _espn_league(), raw)

    assert len(candidates) == 1
    fa = candidates[0]
    assert fa.name == "Undrafted Rookie WR"
    assert fa.platform_projection is None
    assert fa.gsis_id is None


@pytest.mark.asyncio
@respx.mock
async def test_espn_provider_passes_through_injury_status(db_session):
    _mock_espn_crosswalk()
    raw = {"players": [_espn_player(555, injury_status="QUESTIONABLE")]}

    provider = EspnAvailablePlayerProvider()
    candidates = await provider.get_available_players(db_session, _espn_league(), raw)

    assert candidates[0].injury_status == "QUESTIONABLE"


@pytest.mark.asyncio
@respx.mock
async def test_espn_provider_deduplicates_repeated_player_id(db_session):
    _mock_espn_crosswalk()
    raw = {
        "players": [
            _espn_player(555, full_name="Free Agent WR"),
            _espn_player(555, full_name="Free Agent WR"),
        ]
    }

    provider = EspnAvailablePlayerProvider()
    candidates = await provider.get_available_players(db_session, _espn_league(), raw)

    assert len(candidates) == 1
    assert candidates[0].platform_player_id == "555"


@pytest.mark.asyncio
async def test_espn_provider_raises_auth_error_when_raw_data_is_missing(db_session):
    provider = EspnAvailablePlayerProvider()

    with pytest.raises(EspnAuthError):
        await provider.get_available_players(db_session, _espn_league(), None)


@pytest.mark.asyncio
@respx.mock
async def test_espn_provider_returns_empty_list_for_empty_free_agent_pool(db_session):
    _mock_espn_crosswalk()
    raw = {"players": []}

    provider = EspnAvailablePlayerProvider()
    candidates = await provider.get_available_players(db_session, _espn_league(), raw)

    assert candidates == []
