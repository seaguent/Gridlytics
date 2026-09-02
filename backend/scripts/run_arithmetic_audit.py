import asyncio

import pandas as pd

from app.nflverse.client import NflverseClient
from app.projections.context_aware.career_prior import compute_career_prior
from app.projections.context_aware.career_prior_sync import fetch_season_stats_range
from app.projections.context_aware.depth_chart import RoleInfo, load_current_roles_batch
from app.projections.context_aware.team_context import TeamTendencies, compute_team_tendencies
from app.projections.scoring_rules import STANDARD_PPR
from scripts.run_career_prior_validation import build_career_seasons

NAMED_PLAYERS = [
    ("Justin Jefferson", "WR"), ("Ja'Marr Chase", "WR"), ("Puka Nacua", "WR"),
    ("CeeDee Lamb", "WR"), ("Amon-Ra St. Brown", "WR"),
    ("Jonathan Taylor", "RB"), ("Bijan Robinson", "RB"),
    ("Josh Allen", "QB"), ("Patrick Mahomes", "QB"),
    ("Sam LaPorta", "TE"), ("George Kittle", "TE"),
]

CATEGORY_FOR_POSITION = {"WR": "receiving", "TE": "receiving", "RB": "rushing", "QB": "passing"}
OPPORTUNITY_COLUMN = {"receiving": "targets", "rushing": "carries", "passing": "attempts"}
SHARE_KEY = {"receiving": "target_share", "rushing": "carry_share"}


def _find_gsis_id(season_df: pd.DataFrame, name: str) -> str | None:
    matches = season_df[season_df["player_display_name"] == name]
    return matches.iloc[0]["player_id"] if not matches.empty else None


async def main():
    client = NflverseClient()
    season = 2026
    prior_season = 2025
    weekly_2025 = await client.get_weekly_stats(str(prior_season))
    weekly_2024 = await client.get_weekly_stats(str(prior_season - 1))
    season_stats_by_year = await fetch_season_stats_range(client, current_season=season, lookback=4)
    depth_charts = await client.get_depth_charts(str(prior_season))
    await client.aclose()

    weekly_combined = pd.concat([weekly_2024, weekly_2025], ignore_index=True)
    season_df = season_stats_by_year.get(prior_season)
    if season_df is None or season_df.empty:
        print("No real season data available.")
        return

    as_of_date = "2026-08-01"
    role_by_player = load_current_roles_batch(depth_charts, as_of_date)
    tendencies_by_team = compute_team_tendencies(weekly_combined, season=prior_season + 1, before_week=1)

    # Real, whole-league average team pass/rush attempts per game -- context for whether any one
    # team's own number looks like an outlier or like the real population.
    real_tendencies = [t for t in tendencies_by_team.values() if t.pass_attempts_per_game is not None]
    avg_pass = sum(t.pass_attempts_per_game for t in real_tendencies) / len(real_tendencies)
    avg_rush = sum(t.rush_attempts_per_game for t in real_tendencies) / len(real_tendencies)
    print(f"Real league-wide average (all 32 teams, blended prior+current season by games observed):")
    print(f"  avg pass_attempts_per_game={avg_pass:.2f}, avg rush_attempts_per_game={avg_rush:.2f}\n")

    print("=" * 100)
    for name, position in NAMED_PLAYERS:
        gsis_id = _find_gsis_id(season_df, name)
        if gsis_id is None:
            print(f"{name}: not found in real season data\n")
            continue
        row = season_df[season_df["player_id"] == gsis_id].iloc[0]
        team = row.get("recent_team")

        limited_seasons = {s: df for s, df in season_stats_by_year.items() if 2022 <= s <= 2025}
        career_seasons = build_career_seasons(limited_seasons, gsis_id, season)
        # NO QB discount, NO team-change discount -- pure career-weighted value, exactly what the
        # user asked to isolate: "trace the complete arithmetic ... with NO QB workload discount."
        career_prior = compute_career_prior(career_seasons)

        role = role_by_player.get((gsis_id, position), RoleInfo(pos_rank=None, role_confidence="unknown", role_changed_recently=False))
        tendencies = tendencies_by_team.get(team, TeamTendencies(None, None))

        category = CATEGORY_FOR_POSITION[position]
        team_volume = (
            tendencies.pass_attempts_per_game if category in ("receiving", "passing")
            else tendencies.rush_attempts_per_game
        )
        share_key = SHARE_KEY.get(category)
        share = career_prior.workload.get(share_key) if share_key else None

        print(f"--- {name} ({position}, team={team}) | seasons_used={career_prior.seasons_used} | "
              f"role: pos_rank={role.pos_rank} confidence={role.role_confidence} ---")
        print(f"  team {category} volume (this team, blended): {team_volume}")
        print(f"  team {category} volume (league average):     {avg_pass if category != 'rushing' else avg_rush:.2f}")
        print(f"  career {share_key or 'n/a'} (NO discount):    {share}")

        if team_volume is None or share is None:
            print("  Cannot compute expected opportunities -- missing team volume or share.\n")
            continue

        expected_opps = team_volume * share
        print(f"  expected_opportunities = {team_volume:.2f} x {share:.4f} = {expected_opps:.2f}")

        if category == "receiving":
            ypt = career_prior.talent.get("yards_per_target")
            td_rate = career_prior.talent.get("receiving_td_rate")
            catch_rate = career_prior.talent.get("catch_rate")
            print(f"  career yards_per_target={ypt}, receiving_td_rate={td_rate}, catch_rate={catch_rate}")
            if None in (ypt, td_rate, catch_rate):
                print("  Missing efficiency input.\n")
                continue
            receptions = expected_opps * catch_rate
            yards = expected_opps * ypt
            tds = expected_opps * td_rate
            points = (receptions * STANDARD_PPR.reception_points + yards * STANDARD_PPR.rec_yard_points
                      + tds * STANDARD_PPR.rec_td_points)
            print(f"  receptions = {expected_opps:.2f} x {catch_rate:.4f} = {receptions:.2f} -> "
                  f"{receptions:.2f} x {STANDARD_PPR.reception_points} = {receptions * STANDARD_PPR.reception_points:.2f} pts")
            print(f"  yards      = {expected_opps:.2f} x {ypt:.4f} = {yards:.2f} -> "
                  f"{yards:.2f} x {STANDARD_PPR.rec_yard_points} = {yards * STANDARD_PPR.rec_yard_points:.2f} pts")
            print(f"  exp. TDs   = {expected_opps:.2f} x {td_rate:.4f} = {tds:.3f} -> "
                  f"{tds:.3f} x {STANDARD_PPR.rec_td_points} = {tds * STANDARD_PPR.rec_td_points:.2f} pts")
            print(f"  TOTAL (standard full PPR) = {points:.2f}")

        elif category == "rushing":
            ypc = career_prior.talent.get("yards_per_carry")
            td_rate = career_prior.talent.get("rushing_td_rate")
            print(f"  career yards_per_carry={ypc}, rushing_td_rate={td_rate}")
            if None in (ypc, td_rate):
                print("  Missing efficiency input.\n")
                continue
            yards = expected_opps * ypc
            tds = expected_opps * td_rate
            rushing_points = yards * STANDARD_PPR.rush_yard_points + tds * STANDARD_PPR.rush_td_points
            print(f"  yards    = {expected_opps:.2f} x {ypc:.4f} = {yards:.2f} -> "
                  f"{yards:.2f} x {STANDARD_PPR.rush_yard_points} = {yards * STANDARD_PPR.rush_yard_points:.2f} pts")
            print(f"  exp. TDs = {expected_opps:.2f} x {td_rate:.4f} = {tds:.3f} -> "
                  f"{tds:.3f} x {STANDARD_PPR.rush_td_points} = {tds * STANDARD_PPR.rush_td_points:.2f} pts")
            print(f"  RUSHING SUBTOTAL = {rushing_points:.2f} (real players also have a receiving "
                  f"subtotal not computed in this rushing-only pass)")

        elif category == "passing":
            ypa = career_prior.talent.get("yards_per_attempt")
            print(f"  career yards_per_attempt={ypa} (passing_td_rate/int_rate not tracked by 15.7c-A -- "
                  f"deliberate gap, falls back to position prior in the live model, not audited here)")
            if ypa is None:
                print("  Missing efficiency input.\n")
                continue
            yards = expected_opps * ypa
            print(f"  yards = {expected_opps:.2f} x {ypa:.4f} = {yards:.2f} -> "
                  f"{yards:.2f} x {STANDARD_PPR.pass_yard_points} = {yards * STANDARD_PPR.pass_yard_points:.2f} pts "
                  f"(TD/INT not included in this pass -- see note above)")

        print()


asyncio.run(main())
