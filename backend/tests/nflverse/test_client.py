import gzip

import httpx
import pytest
import respx

from app.nflverse.client import DYNASTYPROCESS_IDS_URL, NFLVERSE_RELEASES_BASE_URL, NflverseClient

CROSSWALK_CSV = (
    "gsis_id,display_name,espn_id,pfr_id\n"
    "00-0039075,Puka Nacua,4426515,NacuPu00\n"
)

WEEKLY_STATS_CSV = (
    "player_id,player_display_name,position,season,week,targets,target_share,carries\n"
    "00-0039075,Puka Nacua,WR,2024,1,10,0.28,1\n"
)


@pytest.mark.asyncio
@respx.mock
async def test_get_player_crosswalk_parses_csv_into_dataframe():
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/players/players.csv").mock(
        return_value=httpx.Response(200, text=CROSSWALK_CSV)
    )

    client = NflverseClient()
    df = await client.get_player_crosswalk()
    await client.aclose()

    assert len(df) == 1
    assert df.iloc[0]["espn_id"] == 4426515


@pytest.mark.asyncio
@respx.mock
async def test_get_weekly_stats_parses_csv_into_dataframe():
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_2024.csv").mock(
        return_value=httpx.Response(200, text=WEEKLY_STATS_CSV)
    )

    client = NflverseClient()
    df = await client.get_weekly_stats("2024")
    await client.aclose()

    assert len(df) == 1
    assert df.iloc[0]["target_share"] == 0.28


@pytest.mark.asyncio
@respx.mock
async def test_get_weekly_stats_returns_empty_dataframe_for_unpublished_season():
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_week_2099.csv").mock(
        return_value=httpx.Response(404)
    )

    client = NflverseClient()
    df = await client.get_weekly_stats("2099")
    await client.aclose()

    assert df.empty


@pytest.mark.asyncio
@respx.mock
async def test_get_season_stats_parses_csv_into_dataframe():
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_reg_2025.csv").mock(
        return_value=httpx.Response(
            200, text="player_id,player_display_name,position,team,target_share\n00-1,A,WR,SF,0.25\n"
        )
    )

    client = NflverseClient()
    df = await client.get_season_stats("2025")
    await client.aclose()

    assert len(df) == 1
    assert df.iloc[0]["target_share"] == 0.25


@pytest.mark.asyncio
@respx.mock
async def test_get_season_stats_returns_empty_dataframe_for_unpublished_season():
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/stats_player/stats_player_reg_2099.csv").mock(
        return_value=httpx.Response(404)
    )

    client = NflverseClient()
    df = await client.get_season_stats("2099")
    await client.aclose()

    assert df.empty


@pytest.mark.asyncio
@respx.mock
async def test_get_sleeper_crosswalk_parses_csv_into_dataframe():
    respx.get(DYNASTYPROCESS_IDS_URL).mock(
        return_value=httpx.Response(200, text="sleeper_id,gsis_id,name\n9493,00-0039075,Puka Nacua\n")
    )

    client = NflverseClient()
    df = await client.get_sleeper_crosswalk()
    await client.aclose()

    assert len(df) == 1
    assert str(df.iloc[0]["sleeper_id"]) == "9493"


@pytest.mark.asyncio
@respx.mock
async def test_get_snap_counts_parses_csv_into_dataframe():
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/snap_counts/snap_counts_2024.csv").mock(
        return_value=httpx.Response(
            200, text="pfr_player_id,season,week,offense_pct\nNacuPu00,2024,1,0.91\n"
        )
    )

    client = NflverseClient()
    df = await client.get_snap_counts("2024")
    await client.aclose()

    assert len(df) == 1
    assert df.iloc[0]["offense_pct"] == 0.91


@pytest.mark.asyncio
@respx.mock
async def test_get_snap_counts_returns_empty_dataframe_for_unpublished_season():
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/snap_counts/snap_counts_2099.csv").mock(
        return_value=httpx.Response(404)
    )

    client = NflverseClient()
    df = await client.get_snap_counts("2099")
    await client.aclose()

    assert df.empty


@pytest.mark.asyncio
@respx.mock
async def test_get_schedule_filters_to_requested_season():
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/schedules/games.csv").mock(
        return_value=httpx.Response(
            200,
            text=(
                "season,week,home_team,away_team\n"
                "2024,1,PHI,DAL\n"
                "2023,1,KC,DET\n"
            ),
        )
    )

    client = NflverseClient()
    df = await client.get_schedule("2024")
    await client.aclose()

    assert len(df) == 1
    assert df.iloc[0]["home_team"] == "PHI"


@pytest.mark.asyncio
@respx.mock
async def test_get_play_by_play_parses_gzipped_csv():
    csv_bytes = b"week,season_type,yardline_100,pass_attempt,rush_attempt,receiver_player_id,rusher_player_id\n1,REG,15,1,0,00-0039075,\n"
    gzipped = gzip.compress(csv_bytes)
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/pbp/play_by_play_2024.csv.gz").mock(
        return_value=httpx.Response(200, content=gzipped, headers={"content-type": "application/gzip"})
    )

    client = NflverseClient()
    df = await client.get_play_by_play("2024")
    await client.aclose()

    assert len(df) == 1
    assert df.iloc[0]["receiver_player_id"] == "00-0039075"


@pytest.mark.asyncio
@respx.mock
async def test_get_play_by_play_returns_empty_dataframe_for_unpublished_season():
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/pbp/play_by_play_2099.csv.gz").mock(
        return_value=httpx.Response(404)
    )

    client = NflverseClient()
    df = await client.get_play_by_play("2099")
    await client.aclose()

    assert df.empty


@pytest.mark.asyncio
@respx.mock
async def test_get_depth_charts_parses_csv_into_dataframe():
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/depth_charts/depth_charts_2025.csv").mock(
        return_value=httpx.Response(
            200,
            text=(
                "dt,team,player_name,espn_id,gsis_id,pos_grp_id,pos_grp,pos_id,pos_name,pos_abb,pos_slot,pos_rank\n"
                "2025-09-01T00:00:00Z,SF,Test Player,1,00-1,1,Offense,1,Running Back,RB,1,1\n"
            ),
        )
    )

    client = NflverseClient()
    df = await client.get_depth_charts("2025")
    await client.aclose()

    assert len(df) == 1
    assert df.iloc[0]["pos_abb"] == "RB"


@pytest.mark.asyncio
@respx.mock
async def test_get_depth_charts_returns_empty_dataframe_on_404():
    respx.get(f"{NFLVERSE_RELEASES_BASE_URL}/depth_charts/depth_charts_2099.csv").mock(
        return_value=httpx.Response(404)
    )

    client = NflverseClient()
    df = await client.get_depth_charts("2099")
    await client.aclose()

    assert df.empty
