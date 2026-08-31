from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.loader import (
    load_power_ranking_inputs,
    load_remaining_schedule,
    load_simulation_inputs,
    load_weekly_scores,
)
from app.analytics.playoffs import simulate_season
from app.analytics.power_rankings import compute_power_rankings
from app.analytics.roster import compute_roster_efficiency
from app.analytics.standings import compute_expected_wins, compute_schedule_strength
from app.deps import get_fresh_league, get_session
from app.models import League, LeagueConnection, Team
from app.sleeper.sync import refresh_league
from app.sleeper.client import SleeperClient

app = FastAPI(title="Gridlytics API")


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
    result = await compute_roster_efficiency(session, league)
    return result.to_dict(orient="records")


@app.get("/leagues/me/playoff-odds")
async def get_playoff_odds(
    league: League = Depends(get_fresh_league), session: AsyncSession = Depends(get_session)
) -> dict:
    current_records, team_score_dist = await load_simulation_inputs(session, league.id)
    remaining_schedule = await load_remaining_schedule(session, league)

    return simulate_season(
        current_records=current_records,
        team_score_dist=team_score_dist,
        remaining_schedule=remaining_schedule,
        playoff_spots=league.playoff_teams,
        num_trials=5000,
    )
