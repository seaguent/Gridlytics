import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Matchup, RosterSlot, Team, WeeklyScore

DEFAULT_MEAN = 100.0
DEFAULT_STD = 15.0


async def load_weekly_scores(session: AsyncSession, league_id: int) -> pd.DataFrame:
    result = await session.execute(
        select(WeeklyScore, Matchup.week)
        .join(Matchup, WeeklyScore.matchup_id == Matchup.id)
        .where(Matchup.league_id == league_id)
    )
    rows = result.all()

    scores_by_matchup: dict[int, list[tuple[WeeklyScore, int]]] = {}
    for weekly_score, week in rows:
        scores_by_matchup.setdefault(weekly_score.matchup_id, []).append((weekly_score, week))

    records = []
    for entries in scores_by_matchup.values():
        for weekly_score, week in entries:
            opponents = [
                other.team_id for other, _ in entries if other.team_id != weekly_score.team_id
            ]
            records.append(
                {
                    "team_id": weekly_score.team_id,
                    "week": week,
                    "points": weekly_score.points,
                    "opponent_team_id": opponents[0] if opponents else None,
                }
            )

    return pd.DataFrame(records, columns=["team_id", "week", "points", "opponent_team_id"])


async def load_roster_slots(session: AsyncSession, league_id: int) -> pd.DataFrame:
    result = await session.execute(
        select(RosterSlot).join(Team, RosterSlot.team_id == Team.id).where(Team.league_id == league_id)
    )
    slots = result.scalars().all()

    records = [
        {
            "team_id": slot.team_id,
            "week": slot.week,
            "platform_player_id": slot.platform_player_id,
            "points": slot.points,
            "is_starter": slot.is_starter,
        }
        for slot in slots
    ]

    return pd.DataFrame(
        records, columns=["team_id", "week", "platform_player_id", "points", "is_starter"]
    )


async def load_simulation_inputs(session: AsyncSession, league_id: int) -> tuple[dict, dict]:
    result = await session.execute(select(Team).where(Team.league_id == league_id))
    teams = result.scalars().all()

    current_records = {
        team.id: {"wins": team.wins, "losses": team.losses, "points_for": team.points_for}
        for team in teams
    }

    scores = await load_weekly_scores(session, league_id)

    league_mean = scores["points"].mean() if len(scores) >= 1 else DEFAULT_MEAN
    league_std = scores["points"].std() if len(scores) >= 2 else DEFAULT_STD
    if pd.isna(league_std):
        league_std = DEFAULT_STD

    team_score_dist = {}
    for team in teams:
        team_scores = scores.loc[scores["team_id"] == team.id, "points"]
        if len(team_scores) >= 2:
            mean = team_scores.mean()
            std = team_scores.std()
            if pd.isna(std) or std == 0:
                std = league_std
        elif len(team_scores) == 1:
            mean = team_scores.iloc[0]
            std = league_std
        else:
            mean = league_mean
            std = league_std
        team_score_dist[team.id] = {"mean": mean, "std": std}

    return current_records, team_score_dist
