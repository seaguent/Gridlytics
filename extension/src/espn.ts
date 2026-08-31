export interface EspnLeagueInfo {
  leagueId: string;
  season: string;
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
  const season = parsed.searchParams.get("seasonId");
  if (!leagueId || !season) {
    return null;
  }

  return { leagueId, season };
}
