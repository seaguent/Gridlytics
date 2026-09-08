export interface EspnLeagueInfo {
  leagueId: string;
  season: string;
}

// The NFL season is named for the year it starts -- treat August onward as the new season having started.
function currentNflSeason(): string {
  const now = new Date();
  const year = now.getUTCFullYear();
  return String(now.getUTCMonth() >= 7 ? year : year - 1);
}

export function extractEspnLeagueInfo(url: string): EspnLeagueInfo | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }

  if (parsed.hostname !== "fantasy.espn.com" || !parsed.pathname.startsWith("/football/")) {
    return null;
  }

  const leagueId = parsed.searchParams.get("leagueId");
  if (!leagueId) {
    return null;
  }

  // ESPN's own site doesn't always include seasonId -- fall back instead of failing to detect the page.
  const season = parsed.searchParams.get("seasonId") ?? currentNflSeason();

  return { leagueId, season };
}
