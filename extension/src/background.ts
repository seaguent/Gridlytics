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

interface ApiGetMessage {
  type: "API_GET";
  path: string;
  token: string;
}

type Message =
  | ConnectLeagueMessage
  | ConnectEspnLeagueMessage
  | ResyncEspnLeagueMessage
  | ApiGetMessage;

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

  if (message.type === "API_GET") {
    apiGet(message.path, message.token).then(sendResponse);
    return true;
  }

  return false;
});
