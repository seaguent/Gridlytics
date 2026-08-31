import { describe, expect, it } from "vitest";
import { extractLeagueId } from "../src/sleeper";

describe("extractLeagueId", () => {
  it("extracts the league id from a Sleeper league URL", () => {
    const url = "https://sleeper.com/leagues/1389738640346722304/team";
    expect(extractLeagueId(url)).toBe("1389738640346722304");
  });

  it("extracts the league id when the path has no trailing segment", () => {
    const url = "https://sleeper.com/leagues/1389738640346722304";
    expect(extractLeagueId(url)).toBe("1389738640346722304");
  });

  it("returns null for a non-league page", () => {
    const url = "https://sleeper.com/leagues";
    expect(extractLeagueId(url)).toBeNull();
  });

  it("returns null for a completely unrelated URL", () => {
    expect(extractLeagueId("https://example.com/")).toBeNull();
  });
});
