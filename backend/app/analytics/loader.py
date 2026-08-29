import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Matchup, WeeklyScore


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
