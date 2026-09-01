import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchStandings, fetchStartSit, setMyTeam } from "../src/api";

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
