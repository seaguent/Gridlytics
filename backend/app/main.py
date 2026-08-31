from contextlib import asynccontextmanager

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
from app.deps import get_fresh_league, get_session
from app.models import Base, League, LeagueConnection, Team
from app.sleeper.sync import refresh_league
from app.sleeper.client import SleeperClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No real migration tool yet (that's Phase 20) -- create_all is safe to
    # run on every startup since it only creates tables that don't exist.
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


@app.get("/leagues/me")
async def get_league_info(league: League = Depends(get_fresh_league)) -> dict:
    return {
        "name": league.name,
        "season": league.season,
        "status": league.status,
        "current_week": league.current_week,
    }


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
