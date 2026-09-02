import pandas as pd

from app.nflverse.client import NflverseClient
from app.projections.context_aware.career_prior import CareerSeason


def _rate(numerator, denominator) -> float | None:
    if denominator is None or denominator == 0 or pd.isna(denominator):
        return None
    return float(numerator) / float(denominator)


async def fetch_season_stats_range(
    client: NflverseClient, current_season: int, lookback: int = 4
) -> dict[int, pd.DataFrame]:
    result: dict[int, pd.DataFrame] = {}
    for offset in range(1, lookback + 1):
        season = current_season - offset
        df = await client.get_season_stats(str(season))
        if not df.empty:
            result[season] = df
    return result


def build_career_seasons(
    season_stats_by_year: dict[int, pd.DataFrame], gsis_id: str, held_out_season: int
) -> list[CareerSeason]:
    """Leak-safe career-season history for one player: only seasons strictly before
    `held_out_season`, most recent first (season_offset=0). Shared by both the live production
    sync and every validation/backtest script."""
    available = sorted(
        (season for season in season_stats_by_year if season < held_out_season), reverse=True
    )
    seasons: list[CareerSeason] = []
    for offset, season in enumerate(available):
        df = season_stats_by_year[season]
        reg = df[df["season_type"] == "REG"]
        rows = reg[reg["player_id"] == gsis_id]
        if rows.empty:
            continue
        row = rows.iloc[0]
        team = row.get("recent_team")
        team_carries_total = reg[reg["recent_team"] == team]["carries"].sum() if team else 0
        carries = row.get("carries")
        carry_share = (carries / team_carries_total) if team_carries_total else None

        seasons.append(
            CareerSeason(
                season=season, season_offset=offset, games=int(row.get("games") or 0), team=team,
                targets=_int_or_none(row.get("targets")), receptions=_int_or_none(row.get("receptions")),
                receiving_yards=_int_or_none(row.get("receiving_yards")),
                receiving_tds=_int_or_none(row.get("receiving_tds")),
                carries=_int_or_none(carries), rushing_yards=_int_or_none(row.get("rushing_yards")),
                rushing_tds=_int_or_none(row.get("rushing_tds")),
                attempts=_int_or_none(row.get("attempts")), passing_yards=_int_or_none(row.get("passing_yards")),
                passing_tds=_int_or_none(row.get("passing_tds")),
                fantasy_points_ppr=_float_or_none(row.get("fantasy_points_ppr")),
                target_share=_float_or_none(row.get("target_share")), carry_share=carry_share,
                yards_per_target=_rate(row.get("receiving_yards"), row.get("targets")),
                yards_per_carry=_rate(row.get("rushing_yards"), carries),
                catch_rate=_rate(row.get("receptions"), row.get("targets")),
                receiving_td_rate=_rate(row.get("receiving_tds"), row.get("targets")),
                rushing_td_rate=_rate(row.get("rushing_tds"), carries),
                passing_interceptions=_int_or_none(row.get("passing_interceptions")),
            )
        )
    return seasons


def _int_or_none(value) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _float_or_none(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
