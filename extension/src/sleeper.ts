export function extractLeagueId(url: string): string | null {
  const match = url.match(/\/leagues\/(\d+)/);
  return match ? match[1] : null;
}
