import { afterEach, describe, expect, it, vi } from "vitest";
import { apiGet, apiPost } from "../src/background";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("apiGet", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves with data on a successful response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, { hello: "world" })));

    await expect(apiGet("/leagues/me", "token")).resolves.toEqual({
      ok: true,
      data: { hello: "world" },
    });
  });

  it("returns a friendly message on 401", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(401, { detail: "Invalid access token" })));

    const result = await apiGet("/leagues/me", "bad-token");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("Your connection to this league has expired. Try reconnecting.");
  });

  it("returns a friendly message on 429", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(429, { error: "Rate limit exceeded" })));

    const result = await apiGet("/leagues/me", "token");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("Too many requests -- please wait a moment and try again.");
  });

  it("returns a friendly message on 500", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(500, { detail: "Internal server error" })));

    const result = await apiGet("/leagues/me", "token");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("Something went wrong on our end. Please try again in a bit.");
  });

  it("surfaces the backend's detail message for other error statuses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(400, { detail: "No team selected for this league yet" }))
    );

    const result = await apiGet("/leagues/me/start-sit", "token");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("No team selected for this league yet");
  });

  it("falls back to a generic message when the error body isn't JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("not json", { status: 400 }))
    );

    const result = await apiGet("/leagues/me", "token");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("Request failed with status 400");
  });

  it("returns a friendly message when fetch itself throws (offline/network failure)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const result = await apiGet("/leagues/me", "token");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("Can't reach Gridlytics right now. Check your connection and try again.");
  });
});

describe("apiPost", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves with data on a successful response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, { status: "ok" })));

    await expect(apiPost("/leagues/me/my-team", "token", { team_id: 5 })).resolves.toEqual({
      ok: true,
      data: { status: "ok" },
    });
  });

  it("returns a friendly message on 429", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(429, { error: "Rate limit exceeded" })));

    const result = await apiPost("/connections", "token", {});
    expect(result.ok).toBe(false);
    expect(result.error).toBe("Too many requests -- please wait a moment and try again.");
  });

  it("returns a friendly message when fetch itself throws (offline/network failure)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const result = await apiPost("/leagues/me/my-team", "token", { team_id: 5 });
    expect(result.ok).toBe(false);
    expect(result.error).toBe("Can't reach Gridlytics right now. Check your connection and try again.");
  });
});
