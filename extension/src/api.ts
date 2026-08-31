export interface LeagueInfo {
  name: string;
  season: string;
  status: string;
  current_week: number;
}

export interface StandingRow {
  team_id: number;
  display_name: string;
  wins: number;
  losses: number;
  points_for: number;
  expected_wins: number;
  schedule_strength: number;
}

export interface PowerRankingRow {
  team_id: number;
  display_name: string;
  power_score: number;
}

export interface PlayoffOddsRow {
  team_id: number;
  display_name: string;
  playoff_odds: number;
  projected_wins: number;
}

export interface EfficiencyRow {
  team_id: number;
  display_name: string;
  avg_efficiency: number | null;
}

export interface RecapHighlight {
  team_id: number;
  team_id_name: string;
  points?: number;
  all_play_win_fraction?: number;
  bench_points?: number;
}

export interface RecapMatchup {
  team_a: number;
  team_b: number;
  team_a_name: string;
  team_b_name: string;
  winner: number;
  loser: number;
  margin: number;
}

export interface RecapUpset {
  winner_team_id: number;
  loser_team_id: number;
  winner_team_id_name: string;
  loser_team_id_name: string;
  power_gap: number;
}

export interface WeeklyRecap {
  week: number;
  highest_scorer: RecapHighlight | null;
  lowest_scorer: RecapHighlight | null;
  closest_game: RecapMatchup | null;
  biggest_upset: RecapUpset | null;
  unluckiest_team: RecapHighlight | null;
  worst_bench_decision: RecapHighlight | null;
}

interface ApiGetResponse<T> {
  ok: boolean;
  data?: T;
  error?: string;
}

async function fetchJson<T>(path: string, token: string): Promise<T> {
  const response = (await chrome.runtime.sendMessage({
    type: "API_GET",
    path,
    token,
  })) as ApiGetResponse<T>;

  if (!response.ok) {
    throw new Error(response.error ?? `Request to ${path} failed`);
  }
  return response.data as T;
}

export function fetchLeagueInfo(token: string): Promise<LeagueInfo> {
  return fetchJson("/leagues/me", token);
}

export function fetchStandings(token: string): Promise<StandingRow[]> {
  return fetchJson("/leagues/me/standings", token);
}

export function fetchPowerRankings(token: string): Promise<PowerRankingRow[]> {
  return fetchJson("/leagues/me/power-rankings", token);
}

export function fetchPlayoffOdds(token: string): Promise<PlayoffOddsRow[]> {
  return fetchJson("/leagues/me/playoff-odds", token);
}

export function fetchRosterEfficiency(token: string): Promise<EfficiencyRow[]> {
  return fetchJson("/leagues/me/roster-efficiency", token);
}

export function fetchWeeklyRecap(token: string, week: number): Promise<WeeklyRecap> {
  return fetchJson(`/leagues/me/recap/${week}`, token);
}
