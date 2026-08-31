import { generateToken, sha256Hex } from "./auth";
import { API_BASE_URL } from "./config";

interface ConnectLeagueMessage {
  type: "CONNECT_LEAGUE";
  platform: "sleeper";
  platformLeagueId: string;
}

interface ApiGetMessage {
  type: "API_GET";
  path: string;
  token: string;
}

type Message = ConnectLeagueMessage | ApiGetMessage;

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
    [`token:${platformLeagueId}`]: token,
    activeLeagueId: platformLeagueId,
  });
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

  if (message.type === "API_GET") {
    apiGet(message.path, message.token).then(sendResponse);
    return true;
  }

  return false;
});
