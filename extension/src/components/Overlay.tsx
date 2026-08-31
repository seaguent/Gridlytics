import { useEffect, useState } from "react";
import overlayStyles from "../overlay.css";
import { fetchLeagueInfo, fetchWeeklyRecap, LeagueInfo, WeeklyRecap } from "../api";
import { useAnalytics } from "../hooks/useAnalytics";
import { Efficiency } from "./Efficiency";
import { PlayoffOdds } from "./PlayoffOdds";
import { PowerRankings } from "./PowerRankings";
import { Recap } from "./Recap";
import { Standings } from "./Standings";

function formatSubtitle(info: LeagueInfo): string {
  const period = info.status === "pre_draft" ? "Preseason" : `Week ${info.current_week}`;
  return `${info.name} · ${period}`;
}

type Tab = "standings" | "power" | "playoffs" | "efficiency" | "recap";

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

export function Overlay({ leagueId }: { leagueId: string }) {
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("standings");
  const [leagueInfo, setLeagueInfo] = useState<LeagueInfo | null>(null);

  const [recapWeek, setRecapWeek] = useState<number | null>(null);
  const [recap, setRecap] = useState<WeeklyRecap | null>(null);
  const [recapError, setRecapError] = useState<string | null>(null);

  useEffect(() => {
    chrome.storage.local.get([`token:${leagueId}`]).then((result) => {
      const stored = result[`token:${leagueId}`] as string | undefined;
      if (stored) setToken(stored);
    });
  }, [leagueId]);

  useEffect(() => {
    if (!token) return;
    fetchLeagueInfo(token).then(setLeagueInfo).catch(() => {});
  }, [token]);

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
  }, [token, recapWeek]);

  const { standings, powerRankings, playoffOdds, efficiency, error } = useAnalytics(token);

  const handleConnect = async () => {
    setConnecting(true);
    setConnectError(null);
    const response = (await chrome.runtime.sendMessage({
      type: "CONNECT_LEAGUE",
      platform: "sleeper",
      platformLeagueId: leagueId,
    })) as ConnectResponse;
    setConnecting(false);

    if (!response?.ok) {
      setConnectError(response?.error ?? "Failed to connect");
      return;
    }

    const stored = await chrome.storage.local.get([`token:${leagueId}`]);
    setToken(stored[`token:${leagueId}`] as string);
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
          <button className="gl-close" onClick={() => setOpen(false)} aria-label="Close">
            &times;
          </button>
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
              <button
                className={tab === "standings" ? "gl-tab gl-tab--active" : "gl-tab"}
                onClick={() => setTab("standings")}
              >
                Standings
              </button>
              <button
                className={tab === "power" ? "gl-tab gl-tab--active" : "gl-tab"}
                onClick={() => setTab("power")}
              >
                Power Rankings
              </button>
              <button
                className={tab === "playoffs" ? "gl-tab gl-tab--active" : "gl-tab"}
                onClick={() => setTab("playoffs")}
              >
                Playoffs
              </button>
              <button
                className={tab === "efficiency" ? "gl-tab gl-tab--active" : "gl-tab"}
                onClick={() => setTab("efficiency")}
              >
                Efficiency
              </button>
              <button
                className={tab === "recap" ? "gl-tab gl-tab--active" : "gl-tab"}
                onClick={() => setTab("recap")}
              >
                Recap
              </button>
            </div>

            <div className="gl-body">
              {tab !== "recap" && error && <div className="gl-error">{error}</div>}
              {tab !== "recap" && !error && !dataReady && (
                <div className="gl-loading">Loading...</div>
              )}
              {tab !== "recap" && dataReady && (
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
            </div>
          </>
        )}
      </div>
    </>
  );
}
