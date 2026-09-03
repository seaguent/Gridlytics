import { generateToken, sha256Hex } from "./auth";
import { API_BASE_URL } from "./config";

const ESPN_API_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl";

interface ConnectLeagueMessage {
  type: "CONNECT_LEAGUE";
  platform: "sleeper";
  platformLeagueId: string;
}

interface ConnectEspnLeagueMessage {
  type: "CONNECT_ESPN_LEAGUE";
  leagueId: string;
  season: string;
}

interface ResyncEspnLeagueMessage {
  type: "RESYNC_ESPN_LEAGUE";
  leagueId: string;
  season: string;
  token: string;
}

interface FetchEspnWaiversMessage {
  type: "FETCH_ESPN_WAIVERS";
  leagueId: string;
  season: string;
  week: number;
  token: string;
}

interface ApiGetMessage {
  type: "API_GET";
  path: string;
  token: string;
}

interface ApiPostMessage {
  type: "API_POST";
  path: string;
  token: string;
  body: unknown;
}

type Message =
  | ConnectLeagueMessage
  | ConnectEspnLeagueMessage
  | ResyncEspnLeagueMessage
  | FetchEspnWaiversMessage
  | ApiGetMessage
  | ApiPostMessage;

async function connectLeague(platformLeagueId: string): Promise<{ ok: boolean; error?: string }> {
  const token = generateToken();
  const accessTokenHash = await sha256Hex(token);

  const response = await fetch(`${API_BASE_URL}/connections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      platform: "sleeper",
      platform_league_id: platformLeagueId,
      access_token_hash: accessTokenHash,
    }),
  });

  if (!response.ok) {
    return { ok: false, error: `Backend returned ${response.status}` };
  }

  await chrome.storage.local.set({
    [`token:sleeper:${platformLeagueId}`]: token,
    activeConnection: { platform: "sleeper", leagueId: platformLeagueId },
  });
  return { ok: true };
}

async function fetchEspnLeague(leagueId: string, season: string): Promise<unknown> {
  const url = `${ESPN_API_BASE}/seasons/${season}/segments/0/leagues/${leagueId}?view=mTeam&view=mRoster&view=mMatchup&view=mSettings`;
  const response = await fetch(url, { credentials: "include" });
  if (!response.ok) {
    throw new Error(`ESPN returned ${response.status} -- is this league private and you're not logged in?`);
  }
  return response.json();
}

async function connectEspnLeague(
  leagueId: string,
  season: string
): Promise<{ ok: boolean; error?: string }> {
  let rawLeagueData: unknown;
  try {
    rawLeagueData = await fetchEspnLeague(leagueId, season);
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }

  const token = generateToken();
  const accessTokenHash = await sha256Hex(token);

  const response = await fetch(`${API_BASE_URL}/connections/espn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ raw_league_data: rawLeagueData, access_token_hash: accessTokenHash }),
  });

  if (!response.ok) {
    return { ok: false, error: `Backend returned ${response.status}` };
  }

  await chrome.storage.local.set({
    [`token:espn:${leagueId}`]: token,
    activeConnection: { platform: "espn", leagueId },
  });
  return { ok: true };
}

async function resyncEspnLeague(
  leagueId: string,
  season: string,
  token: string
): Promise<{ ok: boolean; error?: string }> {
  let rawLeagueData: unknown;
  try {
    rawLeagueData = await fetchEspnLeague(leagueId, season);
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }

  const response = await fetch(`${API_BASE_URL}/leagues/me/resync-espn`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ raw_league_data: rawLeagueData }),
  });

  if (!response.ok) {
    return { ok: false, error: `Backend returned ${response.status}` };
  }
  return { ok: true };
}

async function fetchEspnFreeAgents(leagueId: string, season: string, week: number): Promise<unknown> {
  const filter = {
    players: {
      filterStatus: { value: ["FREEAGENT", "WAIVERS"] },
      limit: 300,
      sortPercOwned: { sortPriority: 1, sortAsc: false },
    },
  };
  const url = `${ESPN_API_BASE}/seasons/${season}/segments/0/leagues/${leagueId}?view=kona_player_info&scoringPeriodId=${week}`;
  const response = await fetch(url, {
    credentials: "include",
    headers: { "X-Fantasy-Filter": JSON.stringify(filter) },
  });
  if (!response.ok) {
    throw new Error(`ESPN returned ${response.status} -- is this league private and you're not logged in?`);
  }
  return response.json();
}

async function fetchEspnWaivers(
  leagueId: string,
  season: string,
  week: number,
  token: string
): Promise<{ ok: boolean; data?: unknown; error?: string }> {
  let rawFreeAgentsData: unknown;
  try {
    rawFreeAgentsData = await fetchEspnFreeAgents(leagueId, season, week);
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }
  return apiPost("/leagues/me/waivers", token, { raw_free_agents_data: rawFreeAgentsData });
}

async function apiGet(
  path: string,
  token: string
): Promise<{ ok: boolean; data?: unknown; error?: string }> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    return { ok: false, error: `Request to ${path} failed with status ${response.status}` };
  }
  return { ok: true, data: await response.json() };
}

async function apiPost(
  path: string,
  token: string,
  body: unknown
): Promise<{ ok: boolean; data?: unknown; error?: string }> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    return { ok: false, error: `Request to ${path} failed with status ${response.status}` };
  }
  return { ok: true, data: await response.json() };
}

chrome.runtime.onMessage.addListener((message: Message, _sender, sendResponse) => {
  if (message.type === "CONNECT_LEAGUE") {
    connectLeague(message.platformLeagueId).then(sendResponse);
    return true;
  }

  if (message.type === "CONNECT_ESPN_LEAGUE") {
    connectEspnLeague(message.leagueId, message.season).then(sendResponse);
    return true;
  }

  if (message.type === "RESYNC_ESPN_LEAGUE") {
    resyncEspnLeague(message.leagueId, message.season, message.token).then(sendResponse);
    return true;
  }

  if (message.type === "FETCH_ESPN_WAIVERS") {
    fetchEspnWaivers(message.leagueId, message.season, message.week, message.token).then(sendResponse);
    return true;
  }

  if (message.type === "API_GET") {
    apiGet(message.path, message.token).then(sendResponse);
    return true;
  }

  if (message.type === "API_POST") {
    apiPost(message.path, message.token, message.body).then(sendResponse);
    return true;
  }

  return false;
});
