import { describe, expect, it } from "vitest";
import { extractEspnLeagueInfo } from "../src/espn";

describe("extractEspnLeagueInfo", () => {
  it("extracts leagueId and season from a team page URL", () => {
    const url = "https://fantasy.espn.com/football/team?leagueId=1234567&seasonId=2026&teamId=1";
    expect(extractEspnLeagueInfo(url)).toEqual({ leagueId: "1234567", season: "2026" });
  });

  it("extracts leagueId and season from a league page URL", () => {
    const url = "https://fantasy.espn.com/football/league?leagueId=1234567&seasonId=2026";
    expect(extractEspnLeagueInfo(url)).toEqual({ leagueId: "1234567", season: "2026" });
  });

  it("returns null when leagueId is missing", () => {
    const url = "https://fantasy.espn.com/football/league?seasonId=2026";
    expect(extractEspnLeagueInfo(url)).toBeNull();
  });

  it("returns null when seasonId is missing", () => {
    const url = "https://fantasy.espn.com/football/league?leagueId=1234567";
    expect(extractEspnLeagueInfo(url)).toBeNull();
  });

  it("returns null for a non-ESPN-fantasy URL", () => {
    expect(extractEspnLeagueInfo("https://espn.com/nfl/scores")).toBeNull();
  });

  it("returns null for an ESPN fantasy URL for a different sport", () => {
    const url = "https://fantasy.espn.com/basketball/team?leagueId=1234567&seasonId=2026";
    expect(extractEspnLeagueInfo(url)).toBeNull();
  });
});
