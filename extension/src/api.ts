export interface LeagueInfo {
  name: string;
  season: string;
  status: string;
  current_week: number;
  scoring_is_custom: boolean;
  scoring_notes: string[];
  my_team_id: number | null;
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

export interface RankingRow {
  platform_player_id: string;
  name: string;
  position: string;
  projected_points: number;
  sources: string[];
  value_over_replacement: number;
  value_score: number;
  floor: number | null;
  ceiling: number | null;
  confidence: number | null;
  range_source: string | null;
  sample_size: number;
  target_share: number | null;
  targets: number | null;
  carries: number | null;
  usage_trend: string | null;
  snap_share: number | null;
  red_zone_opportunities: number | null;
  injury_status: string | null;
  opponent: string | null;
  matchup_rating: number | null;
  experience_status: string | null;
  games_played: number;
  season_target_share: number | null;
  recent_target_share: number | null;
  availability: string | null;
}

export type StartSitAction = "start" | "bench" | "swap_in" | "swap_out" | "unavailable";

export interface StartSitPlayerRow {
  platform_player_id: string;
  name: string;
  position: string;
  currently_starting: boolean;
  action: StartSitAction;
  projected_points: number | null;
  sources: string[];
  floor: number | null;
  ceiling: number | null;
  confidence: number | null;
  range_source: string | null;
  sample_size: number;
  reasons: string[];
  target_share: number | null;
  targets: number | null;
  carries: number | null;
  usage_trend: string | null;
  snap_share: number | null;
  red_zone_opportunities: number | null;
  injury_status: string | null;
  opponent: string | null;
  matchup_rating: number | null;
  experience_status: string | null;
  games_played: number;
  season_target_share: number | null;
  recent_target_share: number | null;
  availability: string | null;
  recommended_slot?: string;
  swap_out_player_id?: string;
  swap_out_name?: string;
  comparison?: PlayerComparison | null;
}

export interface StartSitSummary {
  changes_count: number;
  current_lineup_points: number;
  projected_points_change: number;
}

export interface PlayerComparison {
  opponent_player_id: string;
  opponent_name: string;
  projection_gap: number;
  is_close_call: boolean;
  favors_this_player: string[];
  favors_opponent: string[];
  this_player_risks: string[];
  opponent_risks: string[];
  this_player_labels: string[];
  opponent_labels: string[];
}

export interface StartSitResponse {
  starters: StartSitPlayerRow[];
  bench: StartSitPlayerRow[];
  unavailable: StartSitPlayerRow[];
  optimal_points: number;
  summary: StartSitSummary;
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

async function postJson<T>(path: string, token: string, body: unknown): Promise<T> {
  const response = (await chrome.runtime.sendMessage({
    type: "API_POST",
    path,
    token,
    body,
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

export function fetchRankings(token: string, position?: string): Promise<RankingRow[]> {
  const query = position ? `?position=${position}` : "";
  return fetchJson(`/leagues/me/rankings${query}`, token);
}

export function setMyTeam(token: string, teamId: number): Promise<{ status: string; my_team_id: number }> {
  return postJson("/leagues/me/my-team", token, { team_id: teamId });
}

export function fetchStartSit(token: string): Promise<StartSitResponse> {
  return fetchJson("/leagues/me/start-sit", token);
}
