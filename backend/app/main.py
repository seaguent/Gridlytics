from contextlib import asynccontextmanager
from dataclasses import replace

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.loader import (
    load_power_ranking_inputs,
    load_remaining_schedule,
    load_roster_slots,
    load_simulation_inputs,
    load_weekly_scores,
)
from app.analytics.playoffs import simulate_season
from app.analytics.power_rankings import compute_power_rankings
from app.analytics.recap import generate_weekly_recap
from app.analytics.roster import compute_bench_points, compute_roster_efficiency, summarize_roster_efficiency
from app.analytics.standings import compute_expected_wins, compute_schedule_strength
from app.db import engine
from app.deps import get_current_connection, get_current_league, get_fresh_league, get_my_team, get_session
from app.espn.adapter import sync_league as espn_sync_league
from app.espn.schemas import EspnLeagueResponse
from app.models import Base, League, LeagueConnection, Player, ProjectionRecord, RosterSlot, Team
from app.nflverse.client import NflverseClient
from app.nflverse.sync import sync_usage_stats
from app.projections.accuracy_pipeline import load_projection_accuracy
from app.projections.ensemble import EnsembleProjectionProvider
from app.projections.espn import ESPNProjectionProvider
from app.projections.final_projection import compute_final_projection, fetch_platform_only_projections
from app.projections.historical import HistoricalAverageProjectionProvider
from app.projections.nflverse_metrics import NflverseMetricsProvider
from app.projections.rows import metrics_to_dict
from app.projections.sleeper import SleeperProjectionProvider
from app.projections.start_sit import compute_start_sit
from app.projections.trade_analysis import InvalidTradeError, compute_trade_analysis
from app.projections.uncertainty_pipeline import apply_uncertainty_ranges
from app.projections.available_players import EspnAuthError
from app.projections.value import compute_value_over_replacement
from app.projections.waivers import compute_waiver_recommendations
from app.sleeper.sync import refresh_league
from app.sleeper.client import SleeperClient
from app.sleeper.scoring import detect_custom_scoring


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No Alembic yet (Phase 20) -- create_all only creates missing tables, safe to run every startup.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Gridlytics API", lifespan=lifespan)



@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


class ConnectionRequest(BaseModel):
    platform: str
    platform_league_id: str
    access_token_hash: str


class ConnectionResponse(BaseModel):
    league_id: int
    name: str
    season: str


@app.post("/connections", response_model=ConnectionResponse)
async def create_connection(
    body: ConnectionRequest, session: AsyncSession = Depends(get_session)
) -> ConnectionResponse:
    if body.platform != "sleeper":
        raise HTTPException(status_code=400, detail="Unsupported platform")

    client = SleeperClient()
    try:
        league = await refresh_league(session, client, body.platform_league_id)
    finally:
        await client.aclose()

    session.add(LeagueConnection(league_id=league.id, access_token_hash=body.access_token_hash))
    await session.commit()

    return ConnectionResponse(league_id=league.id, name=league.name, season=league.season)


class EspnConnectionRequest(BaseModel):
    raw_league_data: dict
    access_token_hash: str


@app.post("/connections/espn", response_model=ConnectionResponse)
async def create_espn_connection(
    body: EspnConnectionRequest, session: AsyncSession = Depends(get_session)
) -> ConnectionResponse:
    raw = EspnLeagueResponse.model_validate(body.raw_league_data)
    league = await espn_sync_league(session, raw)

    nflverse_client = NflverseClient()
    try:
        await sync_usage_stats(session, nflverse_client, league)
    finally:
        await nflverse_client.aclose()

    session.add(LeagueConnection(league_id=league.id, access_token_hash=body.access_token_hash))
    await session.commit()

    return ConnectionResponse(league_id=league.id, name=league.name, season=league.season)


class EspnResyncRequest(BaseModel):
    raw_league_data: dict


@app.post("/leagues/me/resync-espn")
async def resync_espn_league(
    body: EspnResyncRequest,
    league: League = Depends(get_current_league),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    if league.platform != "espn":
        raise HTTPException(status_code=400, detail="This league is not an ESPN league")

    raw = EspnLeagueResponse.model_validate(body.raw_league_data)
    await espn_sync_league(session, raw)

    nflverse_client = NflverseClient()
    try:
        await sync_usage_stats(session, nflverse_client, league)
    finally:
        await nflverse_client.aclose()

    return {"status": "ok"}


@app.get("/leagues/me")
async def get_league_info(
    league: League = Depends(get_fresh_league),
    connection: LeagueConnection = Depends(get_current_connection),
) -> dict:
    scoring_is_custom = False
    scoring_notes: list[str] = []
    if league.platform == "sleeper":
        scoring_is_custom, scoring_notes = detect_custom_scoring(league.scoring_settings)

    return {
        "name": league.name,
        "season": league.season,
        "status": league.status,
        "current_week": league.current_week,
        "scoring_is_custom": scoring_is_custom,
        "scoring_notes": scoring_notes,
        "my_team_id": connection.my_team_id,
    }


class SetMyTeamRequest(BaseModel):
    team_id: int


@app.post("/leagues/me/my-team")
async def set_my_team(
    body: SetMyTeamRequest,
    league: League = Depends(get_fresh_league),
    connection: LeagueConnection = Depends(get_current_connection),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        select(Team).where(Team.id == body.team_id, Team.league_id == league.id)
    )
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=400, detail="Team does not belong to this league")

    connection.my_team_id = team.id
    await session.commit()
    return {"status": "ok", "my_team_id": team.id}


@app.get("/leagues/me/standings")
async def get_standings(
    league: League = Depends(get_fresh_league), session: AsyncSession = Depends(get_session)
) -> list[dict]:
    scores = await load_weekly_scores(session, league.id)
    expected_wins = compute_expected_wins(scores) if len(scores) else {}
    schedule_strength = compute_schedule_strength(scores) if len(scores) else {}

    result = await session.execute(select(Team).where(Team.league_id == league.id))
    teams = result.scalars().all()

    return [
        {
            "team_id": team.id,
            "display_name": team.display_name,
            "wins": team.wins,
            "losses": team.losses,
            "points_for": team.points_for,
            "expected_wins": expected_wins.get(team.id, 0.0),
            "schedule_strength": schedule_strength.get(team.id, 0.0),
        }
        for team in teams
    ]


@app.get("/leagues/me/power-rankings")
async def get_power_rankings(
    league: League = Depends(get_fresh_league), session: AsyncSession = Depends(get_session)
) -> list[dict]:
    stats = await load_power_ranking_inputs(session, league.id)
    if not len(stats):
        return []
    rankings = compute_power_rankings(stats)

    result = await session.execute(select(Team).where(Team.league_id == league.id))
    names = {team.id: team.display_name for team in result.scalars()}

    return [
        {
            "team_id": row.team_id,
            "display_name": names.get(row.team_id, ""),
            "power_score": row.power_score,
        }
        for row in rankings.itertuples()
    ]


@app.get("/leagues/me/roster-efficiency")
async def get_roster_efficiency(
    league: League = Depends(get_fresh_league), session: AsyncSession = Depends(get_session)
) -> list[dict]:
    efficiency = await compute_roster_efficiency(session, league)
    if not len(efficiency):
        return []

    summary = summarize_roster_efficiency(efficiency)

    result = await session.execute(select(Team).where(Team.league_id == league.id))
    names = {team.id: team.display_name for team in result.scalars()}

    return [
        {
            "team_id": int(row.team_id),
            "display_name": names.get(row.team_id, ""),
            "avg_efficiency": None if pd.isna(row.avg_efficiency) else float(row.avg_efficiency),
        }
        for row in summary.itertuples()
    ]


@app.get("/leagues/me/teams/{team_id}/roster")
async def get_team_roster(
    team_id: int,
    league: League = Depends(get_fresh_league),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    result = await session.execute(select(Team).where(Team.id == team_id, Team.league_id == league.id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Team not found in this league")

    result = await session.execute(
        select(RosterSlot.platform_player_id).where(
            RosterSlot.team_id == team_id, RosterSlot.week == league.current_week
        )
    )
    player_ids = [pid for (pid,) in result.all()]

    result = await session.execute(
        select(Player).where(Player.platform == league.platform, Player.platform_player_id.in_(player_ids))
    )
    return [
        {"platform_player_id": p.platform_player_id, "name": p.name, "position": p.position}
        for p in result.scalars()
    ]


@app.get("/leagues/me/playoff-odds")
async def get_playoff_odds(
    league: League = Depends(get_fresh_league), session: AsyncSession = Depends(get_session)
) -> list[dict]:
    current_records, team_score_dist = await load_simulation_inputs(session, league.id)
    remaining_schedule = await load_remaining_schedule(session, league)

    odds = simulate_season(
        current_records=current_records,
        team_score_dist=team_score_dist,
        remaining_schedule=remaining_schedule,
        playoff_spots=league.playoff_teams,
        num_trials=5000,
    )

    result = await session.execute(select(Team).where(Team.league_id == league.id))
    names = {team.id: team.display_name for team in result.scalars()}

    rows = [
        {
            "team_id": team_id,
            "display_name": names.get(team_id, ""),
            "playoff_odds": stats["playoff_odds"],
            "projected_wins": stats["projected_wins"],
        }
        for team_id, stats in odds.items()
    ]
    return sorted(rows, key=lambda row: row["playoff_odds"], reverse=True)


@app.get("/leagues/me/recap/{week}")
async def get_weekly_recap(
    week: int,
    league: League = Depends(get_fresh_league),
    session: AsyncSession = Depends(get_session),
) -> dict:
    scores = await load_weekly_scores(session, league.id)
    week_scores = scores[scores["week"] == week].reset_index(drop=True)
    if not len(week_scores):
        raise HTTPException(status_code=404, detail=f"No data for week {week}")

    power_inputs = await load_power_ranking_inputs(session, league.id)
    power_scores = {}
    if len(power_inputs):
        rankings = compute_power_rankings(power_inputs)
        power_scores = dict(zip(rankings["team_id"], rankings["power_score"]))

    roster = await load_roster_slots(session, league.id)
    week_roster = roster[roster["week"] == week]
    bench_points = (
        compute_bench_points(week_roster)
        if len(week_roster)
        else pd.DataFrame(columns=["team_id", "week", "bench_points"])
    )

    recap = generate_weekly_recap(week_scores, power_scores, bench_points)

    result = await session.execute(select(Team).where(Team.league_id == league.id))
    names = {team.id: team.display_name for team in result.scalars()}

    def named(entry: dict | None, *id_fields: str) -> dict | None:
        if entry is None:
            return None
        extra = {f"{field}_name": names.get(entry[field], "") for field in id_fields}
        return {**entry, **extra}

    return {
        "week": week,
        "highest_scorer": named(recap["highest_scorer"], "team_id"),
        "lowest_scorer": named(recap["lowest_scorer"], "team_id"),
        "closest_game": named(recap["closest_game"], "team_a", "team_b"),
        "biggest_upset": named(recap["biggest_upset"], "winner_team_id", "loser_team_id"),
        "unluckiest_team": named(recap["unluckiest_team"], "team_id"),
        "worst_bench_decision": named(recap["worst_bench_decision"], "team_id"),
    }


@app.get("/leagues/me/projections")
async def get_projections(
    league: League = Depends(get_fresh_league), session: AsyncSession = Depends(get_session)
) -> list[dict]:
    provider = EnsembleProjectionProvider(
        [ESPNProjectionProvider(), SleeperProjectionProvider(), HistoricalAverageProjectionProvider()]
    )
    projections = await provider.get_projections(session, league)
    projections = await apply_uncertainty_ranges(session, league, projections)

    rows = [
        {
            "platform_player_id": p.platform_player_id,
            "name": p.name,
            "position": p.position,
            "projected_points": p.projected_points,
            "sources": p.sources,
            "floor": p.floor,
            "ceiling": p.ceiling,
            "confidence": p.confidence,
            "range_source": p.range_source,
            "sample_size": p.sample_size,
        }
        for p in projections
    ]
    return sorted(rows, key=lambda row: row["projected_points"], reverse=True)


@app.get("/leagues/me/rankings")
async def get_rankings(
    position: str | None = None,
    league: League = Depends(get_fresh_league),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    provider = EnsembleProjectionProvider(
        [ESPNProjectionProvider(), SleeperProjectionProvider(), HistoricalAverageProjectionProvider()]
    )
    projections = await provider.get_projections(session, league)
    if not projections:
        return []
    projections = await apply_uncertainty_ranges(session, league, projections)

    metrics_by_player = {
        m.platform_player_id: m for m in await NflverseMetricsProvider().get_metrics(session, league)
    }

    result = await session.execute(
        select(ProjectionRecord).where(
            ProjectionRecord.league_id == league.id,
            ProjectionRecord.week == league.current_week,
            ProjectionRecord.source == "gridlytics",
            ProjectionRecord.platform_player_id.in_([p.platform_player_id for p in projections]),
        )
    )
    native_by_player = {r.platform_player_id: r for r in result.scalars()}
    platform_projection_by_player = await fetch_platform_only_projections(session, league)

    # The final blended Gridlytics projection (context-aware base x platform, per
    # compute_final_projection's zero-handling rules) is what drives ranking/VOR going forward
    # -- not the raw multi-source ensemble average, and not the unblended Gridlytics base alone.
    final_projections = [
        replace(
            p,
            projected_points=compute_final_projection(
                gridlytics_base=native_by_player[p.platform_player_id].projected_points
                if p.platform_player_id in native_by_player else None,
                platform_projection=platform_projection_by_player.get(p.platform_player_id),
                availability_status=metrics_by_player[p.platform_player_id].availability
                if p.platform_player_id in metrics_by_player else None,
            ),
        )
        for p in projections
    ]
    final_by_player = {p.platform_player_id: p.projected_points for p in final_projections}

    result = await session.execute(select(Team).where(Team.league_id == league.id))
    num_teams = len(result.scalars().all())

    vor = compute_value_over_replacement(final_projections, league.roster_positions, num_teams)
    vor_values = list(vor.values())
    vor_min, vor_max = min(vor_values), max(vor_values)
    vor_range = vor_max - vor_min

    rows = []
    for p in projections:
        player_vor = vor.get(p.platform_player_id, 0.0)
        value_score = 50.0 if vor_range == 0 else (player_vor - vor_min) / vor_range * 100
        metrics = metrics_by_player.get(p.platform_player_id)
        native = native_by_player.get(p.platform_player_id)
        rows.append(
            {
                "platform_player_id": p.platform_player_id,
                "name": p.name,
                "position": p.position,
                # The primary "X proj" field is the untouched ESPN/Sleeper platform number --
                # NEVER the blend. Gridlytics' own (blended) opinion is a separate field below.
                "projected_points": platform_projection_by_player.get(p.platform_player_id),
                "sources": p.sources,
                "value_over_replacement": player_vor,
                "value_score": value_score,
                "floor": p.floor,
                "ceiling": p.ceiling,
                "confidence": p.confidence,
                "range_source": p.range_source,
                "sample_size": p.sample_size,
                "gridlytics_base_projection": native.projected_points if native else None,
                "platform_projection": platform_projection_by_player.get(p.platform_player_id),
                "final_gridlytics_projection": final_by_player.get(p.platform_player_id),
                # "Gridlytics" in the UI is the blended final number, not the raw base --
                # comparing this against "projected_points" (pure platform) is the real,
                # user-facing ESPN-vs-Gridlytics comparison.
                "gridlytics_projected_points": final_by_player.get(p.platform_player_id),
                "gridlytics_expected_opportunities": native.expected_opportunities if native else None,
                "gridlytics_prior_season_weight": native.prior_season_weight if native else None,
                "gridlytics_dominant_category": native.dominant_category if native else None,
                "gridlytics_lower_confidence": bool(
                    metrics is not None
                    and p.position == "TE"
                    and metrics.experience_status == "rookie_or_limited_history"
                ),
                **metrics_to_dict(p.position, metrics),
            }
        )

    if position:
        rows = [row for row in rows if row["position"] == position.upper()]

    return sorted(rows, key=lambda row: row["value_score"], reverse=True)


@app.get("/leagues/me/start-sit")
async def get_start_sit(
    league: League = Depends(get_fresh_league),
    team: Team = Depends(get_my_team),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await compute_start_sit(session, league, team)


class TradeAnalysisRequest(BaseModel):
    other_team_id: int
    give_player_ids: list[str] = []
    receive_player_ids: list[str] = []


@app.post("/leagues/me/trade-analysis")
async def post_trade_analysis(
    body: TradeAnalysisRequest,
    league: League = Depends(get_fresh_league),
    team: Team = Depends(get_my_team),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        return await compute_trade_analysis(
            session, league, team.id, body.other_team_id, body.give_player_ids, body.receive_player_ids
        )
    except InvalidTradeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/leagues/me/waivers")
async def get_waivers(
    league: League = Depends(get_fresh_league),
    connection: LeagueConnection = Depends(get_current_connection),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if league.platform == "espn":
        # ESPN has no server-side auth -- free-agent data can only arrive via POST with a
        # browser-fetched payload (see post_waivers below), never through a bare GET.
        return {"mode": "unsupported_platform", "recommendations": []}
    return await compute_waiver_recommendations(session, league, connection)


class WaiversRequest(BaseModel):
    raw_free_agents_data: dict | None = None


@app.post("/leagues/me/waivers")
async def post_waivers(
    body: WaiversRequest,
    league: League = Depends(get_fresh_league),
    connection: LeagueConnection = Depends(get_current_connection),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        return await compute_waiver_recommendations(session, league, connection, body.raw_free_agents_data)
    except EspnAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/leagues/me/projection-accuracy")
async def get_projection_accuracy(
    league: League = Depends(get_fresh_league), session: AsyncSession = Depends(get_session)
) -> dict:
    report = await load_projection_accuracy(session, league)
    return {
        "all_available": [
            {"source": s.source, "mae": s.mae, "sample_size": s.sample_size} for s in report.all_available
        ],
        "common_sample": [
            {"source": s.source, "mae": s.mae, "sample_size": s.sample_size} for s in report.common_sample
        ],
    }
