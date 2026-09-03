import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchEspnWaivers,
  fetchStandings,
  fetchStartSit,
  fetchTeamRoster,
  fetchTradeAnalysis,
  fetchWaivers,
  setMyTeam,
} from "../src/api";

describe("fetchStandings", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves with the data from a successful API_GET response", async () => {
    const rows = [
      {
        team_id: 1,
        display_name: "A",
        wins: 1,
        losses: 0,
        points_for: 100,
        expected_wins: 0.8,
        schedule_strength: 95,
      },
    ];
    vi.stubGlobal("chrome", {
      runtime: { sendMessage: vi.fn().mockResolvedValue({ ok: true, data: rows }) },
    });

    await expect(fetchStandings("some-token")).resolves.toEqual(rows);
  });

  it("throws when the background script reports failure", async () => {
    vi.stubGlobal("chrome", {
      runtime: {
        sendMessage: vi.fn().mockResolvedValue({ ok: false, error: "Request failed with status 401" }),
      },
    });

    await expect(fetchStandings("bad-token")).rejects.toThrow("401");
  });

  it("sends the path and token in the message to the background script", async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true, data: [] });
    vi.stubGlobal("chrome", { runtime: { sendMessage } });

    await fetchStandings("my-token");

    expect(sendMessage).toHaveBeenCalledWith({
      type: "API_GET",
      path: "/leagues/me/standings",
      token: "my-token",
    });
  });
});

describe("fetchStartSit", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves with the data from a successful API_GET response", async () => {
    const data = { starters: [], bench: [], unavailable: [], optimal_points: 0 };
    vi.stubGlobal("chrome", {
      runtime: { sendMessage: vi.fn().mockResolvedValue({ ok: true, data }) },
    });

    await expect(fetchStartSit("some-token")).resolves.toEqual(data);
  });

  it("throws when the backend reports no team selected", async () => {
    vi.stubGlobal("chrome", {
      runtime: {
        sendMessage: vi.fn().mockResolvedValue({ ok: false, error: "Request failed with status 400" }),
      },
    });

    await expect(fetchStartSit("no-team-token")).rejects.toThrow("400");
  });
});

describe("fetchWaivers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves with the data from a successful API_GET response", async () => {
    const data = { mode: "projection_only", recommendations: [] };
    vi.stubGlobal("chrome", {
      runtime: { sendMessage: vi.fn().mockResolvedValue({ ok: true, data }) },
    });

    await expect(fetchWaivers("some-token")).resolves.toEqual(data);
  });

  it("sends the path and token in the message to the background script", async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true, data: { mode: "projection_only", recommendations: [] } });
    vi.stubGlobal("chrome", { runtime: { sendMessage } });

    await fetchWaivers("my-token");

    expect(sendMessage).toHaveBeenCalledWith({
      type: "API_GET",
      path: "/leagues/me/waivers",
      token: "my-token",
    });
  });
});

describe("fetchEspnWaivers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves with the data from a successful FETCH_ESPN_WAIVERS response", async () => {
    const data = { mode: "projection_only", recommendations: [] };
    vi.stubGlobal("chrome", {
      runtime: { sendMessage: vi.fn().mockResolvedValue({ ok: true, data }) },
    });

    await expect(fetchEspnWaivers("some-token", "999", "2026", 3)).resolves.toEqual(data);
  });

  it("throws when the background script reports an ESPN auth failure", async () => {
    vi.stubGlobal("chrome", {
      runtime: {
        sendMessage: vi.fn().mockResolvedValue({
          ok: false,
          error: "ESPN returned 401 -- is this league private and you're not logged in?",
        }),
      },
    });

    await expect(fetchEspnWaivers("some-token", "999", "2026", 3)).rejects.toThrow("401");
  });

  it("sends the league id, season, week, and token in the message to the background script", async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true, data: { mode: "projection_only", recommendations: [] } });
    vi.stubGlobal("chrome", { runtime: { sendMessage } });

    await fetchEspnWaivers("my-token", "999", "2026", 3);

    expect(sendMessage).toHaveBeenCalledWith({
      type: "FETCH_ESPN_WAIVERS",
      leagueId: "999",
      season: "2026",
      week: 3,
      token: "my-token",
    });
  });
});

describe("fetchTradeAnalysis", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves with the data from a successful API_POST response", async () => {
    const data = {
      your_team: { current_points: 3.0, projected_points: 18.0, delta: 15.0, reasons: [] },
      other_team: { current_points: 18.0, projected_points: 3.0, delta: -15.0, reasons: [] },
    };
    vi.stubGlobal("chrome", {
      runtime: { sendMessage: vi.fn().mockResolvedValue({ ok: true, data }) },
    });

    await expect(fetchTradeAnalysis("my-token", 7, ["give1"], ["receive1", "receive2"])).resolves.toEqual(data);
  });

  it("sends the trade payload and token in the message to the background script", async () => {
    const sendMessage = vi.fn().mockResolvedValue({
      ok: true,
      data: {
        your_team: { current_points: 0, projected_points: 0, delta: 0, reasons: [] },
        other_team: { current_points: 0, projected_points: 0, delta: 0, reasons: [] },
      },
    });
    vi.stubGlobal("chrome", { runtime: { sendMessage } });

    await fetchTradeAnalysis("my-token", 7, ["give1"], ["receive1"]);

    expect(sendMessage).toHaveBeenCalledWith({
      type: "API_POST",
      path: "/leagues/me/trade-analysis",
      token: "my-token",
      body: { other_team_id: 7, give_player_ids: ["give1"], receive_player_ids: ["receive1"] },
    });
  });

  it("throws when the backend reports a validation error", async () => {
    vi.stubGlobal("chrome", {
      runtime: {
        sendMessage: vi.fn().mockResolvedValue({ ok: false, error: "Request failed with status 400" }),
      },
    });

    await expect(fetchTradeAnalysis("bad-token", 7, [], [])).rejects.toThrow("400");
  });
});

describe("fetchTeamRoster", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves with the roster from a successful API_GET response", async () => {
    const roster = [{ platform_player_id: "p1", name: "Some WR", position: "WR" }];
    vi.stubGlobal("chrome", {
      runtime: { sendMessage: vi.fn().mockResolvedValue({ ok: true, data: roster }) },
    });

    await expect(fetchTeamRoster("my-token", 7)).resolves.toEqual(roster);
  });

  it("sends the team id in the path with the token", async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true, data: [] });
    vi.stubGlobal("chrome", { runtime: { sendMessage } });

    await fetchTeamRoster("my-token", 7);

    expect(sendMessage).toHaveBeenCalledWith({
      type: "API_GET",
      path: "/leagues/me/teams/7/roster",
      token: "my-token",
    });
  });
});

describe("setMyTeam", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends an API_POST message with the team id in the body", async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true, data: { status: "ok", my_team_id: 5 } });
    vi.stubGlobal("chrome", { runtime: { sendMessage } });

    await setMyTeam("my-token", 5);

    expect(sendMessage).toHaveBeenCalledWith({
      type: "API_POST",
      path: "/leagues/me/my-team",
      token: "my-token",
      body: { team_id: 5 },
    });
  });
});
