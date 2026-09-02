import asyncio

from sqlalchemy import select

from app.db import async_session, engine
from app.models import Base, League, Player, ProjectionRecord, RosterSlot, Team
from app.nflverse.client import NflverseClient
from app.nflverse.sync import sync_usage_stats

# Real, well-known players spanning the positions this sync/backtest work targeted all session --
# same named-player set used throughout the projection validation (Jefferson/Chase/Nacua/Taylor/
# Robinson/Allen/Mahomes/LaPorta), identified by their real ESPN player ids via the crosswalk.
ROSTER = [
    ("Justin Jefferson", "WR", "MIN"),
    ("Ja'Marr Chase", "WR", "CIN"),
    ("Puka Nacua", "WR", "LA"),
    ("Jonathan Taylor", "RB", "IND"),
    ("Bijan Robinson", "RB", "ATL"),
    ("Josh Allen", "QB", "BUF"),
    ("Patrick Mahomes", "QB", "KC"),
    ("Sam LaPorta", "TE", "DET"),
]


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    client = NflverseClient()
    crosswalk = await client.get_player_crosswalk()
    await client.aclose()

    async with async_session() as session:
        # Real completed 2025 season, mid-season cutoff -- exercises real current-season blending
        # (not just the career-prior/team-prior fallback a not-yet-started season would hit).
        league = League(
            platform="espn", platform_league_id="real-sanity-sync-test",
            season="2025", name="Real Sanity Sync", status="in_season", current_week=10,
        )
        session.add(league)
        await session.flush()

        team = Team(league_id=league.id, platform_roster_id="1", display_name="Sanity Team")
        session.add(team)
        await session.flush()

        added = []
        for name, position, nfl_team in ROSTER:
            # Filter by position too -- the real crosswalk has same-name collisions (e.g. two real
            # "Josh Allen"s: the Bills QB and an offensive lineman), and a bare name match silently
            # picks whichever row comes first.
            match = crosswalk[(crosswalk["display_name"] == name) & (crosswalk["position"] == position)]
            if match.empty:
                print(f"SKIP: {name} ({position}) not found in real crosswalk")
                continue
            espn_id = str(int(match.iloc[0]["espn_id"]))

            # This dev DB may already have a real Player row for this platform_player_id from the
            # user's own actual league syncs -- reuse it (don't overwrite real existing data),
            # only insert when genuinely new.
            existing = await session.execute(
                select(Player).where(Player.platform == "espn", Player.platform_player_id == espn_id)
            )
            if existing.scalar_one_or_none() is None:
                session.add(Player(platform="espn", platform_player_id=espn_id, position=position, name=name, team=nfl_team))
            session.add(RosterSlot(team_id=team.id, week=1, platform_player_id=espn_id, is_starter=True, points=0))
            added.append((espn_id, name))
        await session.commit()
        print(f"Rostered {len(added)} real players: {added}")

        client = NflverseClient()
        await sync_usage_stats(session, client, league)
        await client.aclose()

        result = await session.execute(
            select(ProjectionRecord).where(ProjectionRecord.league_id == league.id, ProjectionRecord.source == "gridlytics")
        )
        records = result.scalars().all()
        print(f"\n=== {len(records)} gridlytics ProjectionRecord rows written ===")
        for r in sorted(records, key=lambda r: r.projected_points or -1, reverse=True):
            print(f"  {r.name:24s} {r.position:3s} projected={r.projected_points!s:>8} "
                  f"expected_opp={r.expected_opportunities!s:>8} prior_weight={r.prior_season_weight!s:>6} "
                  f"dominant={r.dominant_category}")

        print(f"\nLeague id={league.id} (platform_league_id='real-sanity-sync-test') left in the "
              f"local dev DB for inspection -- not deleted (has FK-referencing rows). Safe to "
              f"remove manually if desired.")


if __name__ == "__main__":
    asyncio.run(main())
