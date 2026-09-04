import { useEffect, useState } from "react";
import overlayStyles from "../overlay.css";
import {
  fetchEspnWaivers,
  fetchLeagueInfo,
  fetchProjectionAccuracy,
  fetchRankings,
  fetchStartSit,
  fetchWaivers,
  fetchWeeklyRecap,
  LeagueInfo,
  ProjectionAccuracy,
  RankingRow,
  setMyTeam,
  StartSitResponse,
  WaiverResponse,
  WeeklyRecap,
} from "../api";
import { useAnalytics } from "../hooks/useAnalytics";
import { Efficiency } from "./Efficiency";
import { PlayoffOdds } from "./PlayoffOdds";
import { PowerRankings } from "./PowerRankings";
import { Rankings } from "./Rankings";
import { Recap } from "./Recap";
import { Standings } from "./Standings";
import { StartSit } from "./StartSit";
import { TeamPicker } from "./TeamPicker";
import { Trades } from "./Trades";
import { Waivers } from "./Waivers";

export type OverlayLeague =
  | { platform: "sleeper"; leagueId: string }
  | { platform: "espn"; leagueId: string; season: string };

function formatSubtitle(info: LeagueInfo): string {
  const period = info.status === "pre_draft" ? "Preseason" : `Week ${info.current_week}`;
  return `${info.name} · ${period}`;
}

type Tab =
  | "standings"
  | "power"
  | "playoffs"
  | "efficiency"
  | "recap"
  | "rankings"
  | "startSit"
  | "waivers"
  | "trades";

type Group = "league" | "myTeam" | "players";

const GROUP_LABELS: Record<Group, string> = {
  league: "League",
  myTeam: "My Team",
  players: "Players",
};

const GROUP_TABS: Record<Group, { id: Tab; label: string }[]> = {
  league: [
    { id: "standings", label: "Standings" },
    { id: "power", label: "Power Rankings" },
    { id: "playoffs", label: "Playoffs" },
    { id: "recap", label: "Recap" },
  ],
  myTeam: [
    { id: "efficiency", label: "Efficiency" },
    { id: "startSit", label: "Start/Sit" },
    { id: "waivers", label: "Waivers" },
    { id: "trades", label: "Trades" },
  ],
  players: [{ id: "rankings", label: "Players" }],
};

const GROUP_ORDER: Group[] = ["league", "myTeam", "players"];

interface ConnectResponse {
  ok: boolean;
  error?: string;
}

function ChartIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <rect x="3" y="12" width="4" height="9" rx="1" fill="currentColor" />
      <rect x="10" y="7" width="4" height="14" rx="1" fill="currentColor" />
      <rect x="17" y="3" width="4" height="18" rx="1" fill="currentColor" />
    </svg>
  );
}

export function Overlay({ league }: { league: OverlayLeague }) {
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<Tab>("standings");
  const [activeGroup, setActiveGroup] = useState<Group>("league");
  const [lastTabByGroup, setLastTabByGroup] = useState<Record<Group, Tab>>({
    league: "standings",
    myTeam: "efficiency",
    players: "rankings",
  });
  const [leagueInfo, setLeagueInfo] = useState<LeagueInfo | null>(null);
  const [leagueInfoError, setLeagueInfoError] = useState<string | null>(null);

  const [recapWeek, setRecapWeek] = useState<number | null>(null);
  const [recap, setRecap] = useState<WeeklyRecap | null>(null);
  const [recapError, setRecapError] = useState<string | null>(null);

  const [rankingsPosition, setRankingsPosition] = useState("ALL");
  const [rankings, setRankings] = useState<RankingRow[] | null>(null);
  const [rankingsError, setRankingsError] = useState<string | null>(null);
  const [projectionAccuracy, setProjectionAccuracy] = useState<ProjectionAccuracy | null>(null);

  const [startSit, setStartSit] = useState<StartSitResponse | null>(null);
  const [startSitError, setStartSitError] = useState<string | null>(null);
  const [settingTeam, setSettingTeam] = useState(false);

  const [waivers, setWaivers] = useState<WaiverResponse | null>(null);
  const [waiversError, setWaiversError] = useState<string | null>(null);

  const [refreshKey, setRefreshKey] = useState(0);

  const storageKey = `token:${league.platform}:${league.leagueId}`;

  useEffect(() => {
    chrome.storage.local.get([storageKey]).then((result) => {
      const stored = result[storageKey] as string | undefined;
      if (stored) setToken(stored);
    });
  }, [storageKey]);

  useEffect(() => {
    if (!token) return;
    setLeagueInfoError(null);
    fetchLeagueInfo(token)
      .then(setLeagueInfo)
      .catch((err: Error) => setLeagueInfoError(err.message));
  }, [token, refreshKey]);

  useEffect(() => {
    if (recapWeek === null && leagueInfo) {
      setRecapWeek(leagueInfo.current_week);
    }
  }, [leagueInfo, recapWeek]);

  useEffect(() => {
    if (!token || recapWeek === null) return;
    setRecap(null);
    setRecapError(null);
    fetchWeeklyRecap(token, recapWeek)
      .then(setRecap)
      .catch(() => setRecapError(`No recap data for week ${recapWeek} yet.`));
  }, [token, recapWeek, refreshKey]);

  useEffect(() => {
    if (!token || tab !== "rankings") return;
    setRankingsError(null);
    const position = rankingsPosition === "ALL" ? undefined : rankingsPosition;
    fetchRankings(token, position)
      .then(setRankings)
      .catch((err: Error) => setRankingsError(err.message));
  }, [token, tab, rankingsPosition, refreshKey]);

  useEffect(() => {
    if (!token || tab !== "rankings") return;
    // Best-effort -- a failed accuracy fetch shouldn't block the rest of the Players tab.
    fetchProjectionAccuracy(token)
      .then(setProjectionAccuracy)
      .catch(() => setProjectionAccuracy(null));
  }, [token, tab, refreshKey]);

  useEffect(() => {
    if (!token || tab !== "startSit" || !leagueInfo?.my_team_id) return;
    setStartSit(null);
    setStartSitError(null);
    fetchStartSit(token)
      .then(setStartSit)
      .catch((err: Error) => setStartSitError(err.message));
  }, [token, tab, leagueInfo?.my_team_id, refreshKey]);

  useEffect(() => {
    if (!token || tab !== "waivers") return;
    if (league.platform === "espn") {
      if (!leagueInfo) return;
      setWaiversError(null);
      fetchEspnWaivers(token, league.leagueId, league.season, leagueInfo.current_week)
        .then(setWaivers)
        .catch((err: Error) => setWaiversError(err.message));
      return;
    }
    setWaiversError(null);
    fetchWaivers(token)
      .then(setWaivers)
      .catch((err: Error) => setWaiversError(err.message));
  }, [token, tab, refreshKey, league, leagueInfo?.current_week]);

  const { standings, powerRankings, playoffOdds, efficiency, error } = useAnalytics(token, refreshKey);

  const handleSelectGroup = (group: Group) => {
    setActiveGroup(group);
    setTab(lastTabByGroup[group]);
  };

  const handleSelectTab = (group: Group, tabId: Tab) => {
    setTab(tabId);
    setLastTabByGroup((prev) => ({ ...prev, [group]: tabId }));
  };

  const handleSelectTeam = async (teamId: number) => {
    if (!token) return;
    setSettingTeam(true);
    try {
      await setMyTeam(token, teamId);
      setLeagueInfo((info) => (info ? { ...info, my_team_id: teamId } : info));
    } catch (err) {
      setStartSitError((err as Error).message);
    } finally {
      setSettingTeam(false);
    }
  };

  const handleConnect = async () => {
    setConnecting(true);
    setConnectError(null);

    const message =
      league.platform === "sleeper"
        ? { type: "CONNECT_LEAGUE" as const, platform: "sleeper" as const, platformLeagueId: league.leagueId }
        : { type: "CONNECT_ESPN_LEAGUE" as const, leagueId: league.leagueId, season: league.season };

    const response = (await chrome.runtime.sendMessage(message)) as ConnectResponse;
    setConnecting(false);

    if (!response?.ok) {
      setConnectError(response?.error ?? "Failed to connect");
      return;
    }

    const stored = await chrome.storage.local.get([storageKey]);
    setToken(stored[storageKey] as string);
  };

  const handleRefresh = async () => {
    if (league.platform !== "espn" || !token) return;
    setRefreshing(true);
    const response = (await chrome.runtime.sendMessage({
      type: "RESYNC_ESPN_LEAGUE",
      leagueId: league.leagueId,
      season: league.season,
      token,
    })) as ConnectResponse;
    setRefreshing(false);
    if (!response?.ok) {
      setConnectError(response?.error ?? "Refresh failed");
      return;
    }
    setRefreshKey((key) => key + 1);
  };

  const dataReady = standings && powerRankings && playoffOdds && efficiency;

  return (
    <>
      <style>{overlayStyles}</style>

      {!open && (
        <button className="gl-handle" onClick={() => setOpen(true)} aria-label="Open Gridlytics">
          <ChartIcon />
        </button>
      )}

      <div className={`gl-drawer ${open ? "gl-drawer--open" : ""}`}>
        <div className="gl-header">
          <div className="gl-header-text">
            <span className="gl-brand">Gridlytics</span>
            {leagueInfo && <span className="gl-subtitle">{formatSubtitle(leagueInfo)}</span>}
          </div>
          <div className="gl-header-actions">
            {token && league.platform === "espn" && (
              <button
                className="gl-refresh"
                onClick={handleRefresh}
                disabled={refreshing}
                aria-label="Refresh ESPN data"
              >
                {refreshing ? "..." : "Refresh"}
              </button>
            )}
            <button className="gl-close" onClick={() => setOpen(false)} aria-label="Close">
              &times;
            </button>
          </div>
        </div>

        {!token && (
          <div className="gl-body">
            <button className="gl-connect" onClick={handleConnect} disabled={connecting}>
              {connecting ? "Connecting..." : "Connect League"}
            </button>
            {connectError && <div className="gl-error">{connectError}</div>}
          </div>
        )}

        {token && (
          <>
            <div className="gl-tabs">
              {GROUP_ORDER.map((group) => (
                <button
                  key={group}
                  className={activeGroup === group ? "gl-tab gl-tab--active" : "gl-tab"}
                  onClick={() => handleSelectGroup(group)}
                >
                  {GROUP_LABELS[group]}
                </button>
              ))}
            </div>

            {activeGroup !== "players" && (
              <div className="gl-tabs gl-tabs--sub">
                {GROUP_TABS[activeGroup].map(({ id, label }) => (
                  <button
                    key={id}
                    className={tab === id ? "gl-tab gl-tab--active" : "gl-tab"}
                    onClick={() => handleSelectTab(activeGroup, id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}

            {connectError && <div className="gl-error">{connectError}</div>}
            {leagueInfoError && (
              <div className="gl-error">Couldn't load your league: {leagueInfoError}</div>
            )}

            <div className="gl-body">
              {tab !== "recap" && tab !== "rankings" && tab !== "startSit" && tab !== "waivers" && tab !== "trades" && error && (
                <div className="gl-error">{error}</div>
              )}
              {tab !== "recap" && tab !== "rankings" && tab !== "startSit" && tab !== "waivers" && tab !== "trades" && !error && !dataReady && (
                <div className="gl-loading">Loading...</div>
              )}
              {tab !== "recap" && tab !== "rankings" && tab !== "startSit" && tab !== "waivers" && tab !== "trades" && dataReady && (
                <>
                  {tab === "standings" && <Standings rows={standings} />}
                  {tab === "power" && <PowerRankings rows={powerRankings} />}
                  {tab === "playoffs" && <PlayoffOdds rows={playoffOdds} />}
                  {tab === "efficiency" && <Efficiency rows={efficiency} />}
                </>
              )}

              {tab === "recap" && (
                <>
                  <div className="gl-week-stepper">
                    <button
                      onClick={() => setRecapWeek((week) => Math.max(1, (week ?? 1) - 1))}
                      disabled={recapWeek === null || recapWeek <= 1}
                      aria-label="Previous week"
                    >
                      &lt;
                    </button>
                    <span className="gl-week-label">Week {recapWeek ?? "-"}</span>
                    <button
                      onClick={() => setRecapWeek((week) => (week ?? 1) + 1)}
                      aria-label="Next week"
                    >
                      &gt;
                    </button>
                  </div>
                  {recapError && <div className="gl-error">{recapError}</div>}
                  {!recapError && !recap && <div className="gl-loading">Loading...</div>}
                  {recap && <Recap recap={recap} />}
                </>
              )}

              {tab === "rankings" && (
                <>
                  {leagueInfo?.scoring_is_custom && (
                    <div className="gl-scoring-note">
                      Custom scoring detected — Sleeper's standard/PPR projections may not exactly match this
                      league's settings.
                    </div>
                  )}
                  {projectionAccuracy && projectionAccuracy.common_sample.length > 0 ? (
                    <div className="gl-accuracy-summary">
                      {projectionAccuracy.common_sample.map((s) => (
                        <span key={s.source}>
                          {s.source}: {s.mae.toFixed(1)} MAE (n={s.sample_size})
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="gl-accuracy-summary gl-stat--muted">
                      Gridlytics vs. platform accuracy: no completed weeks yet this season
                    </div>
                  )}
                  {rankingsError && <div className="gl-error">{rankingsError}</div>}
                  {!rankingsError && !rankings && <div className="gl-loading">Loading...</div>}
                  {rankings && (
                    <Rankings
                      rows={rankings}
                      position={rankingsPosition}
                      onPositionChange={setRankingsPosition}
                    />
                  )}
                </>
              )}

              {tab === "startSit" && (
                <>
                  {!leagueInfo && <div className="gl-loading">Loading...</div>}
                  {leagueInfo && !leagueInfo.my_team_id && standings && (
                    <TeamPicker teams={standings} onSelect={handleSelectTeam} saving={settingTeam} />
                  )}
                  {leagueInfo && leagueInfo.my_team_id && (
                    <>
                      {startSitError && <div className="gl-error">{startSitError}</div>}
                      {!startSitError && !startSit && <div className="gl-loading">Loading...</div>}
                      {startSit && <StartSit data={startSit} />}
                    </>
                  )}
                </>
              )}

              {tab === "waivers" && (
                <>
                  {waiversError && <div className="gl-error">{waiversError}</div>}
                  {!waiversError && <Waivers data={waivers} />}
                </>
              )}

              {tab === "trades" && (
                <>
                  {!leagueInfo && <div className="gl-loading">Loading...</div>}
                  {leagueInfo && !leagueInfo.my_team_id && standings && (
                    <TeamPicker teams={standings} onSelect={handleSelectTeam} saving={settingTeam} />
                  )}
                  {leagueInfo && leagueInfo.my_team_id && standings && token && (
                    <Trades token={token} myTeamId={leagueInfo.my_team_id} standings={standings} />
                  )}
                </>
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}
