import { useEffect, useState } from "react";
import { useAnalytics } from "../hooks/useAnalytics";
import { PlayoffOdds } from "./PlayoffOdds";
import { PowerRankings } from "./PowerRankings";
import { Standings } from "./Standings";

type Tab = "standings" | "power" | "playoffs";

export function Popup() {
  const [token, setToken] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("standings");
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const stored = await chrome.storage.local.get(["activeLeagueId"]);
      const activeLeagueId = stored.activeLeagueId as string | undefined;
      if (!activeLeagueId) {
        setLoadError("No league connected yet. Visit your Sleeper league page and click Connect League.");
        return;
      }

      const tokenResult = await chrome.storage.local.get([`token:${activeLeagueId}`]);
      const storedToken = tokenResult[`token:${activeLeagueId}`] as string | undefined;
      if (!storedToken) {
        setLoadError("Connection token missing. Try reconnecting from your Sleeper league page.");
        return;
      }
      setToken(storedToken);
    })();
  }, []);

  const { standings, powerRankings, playoffOdds, error } = useAnalytics(token);
  const displayError = loadError ?? error;

  if (displayError) {
    return <div className="popup error">{displayError}</div>;
  }

  if (!standings || !powerRankings || !playoffOdds) {
    return <div className="popup">Loading...</div>;
  }

  return (
    <div className="popup">
      <div className="tabs">
        <button className={tab === "standings" ? "active" : ""} onClick={() => setTab("standings")}>
          Standings
        </button>
        <button className={tab === "power" ? "active" : ""} onClick={() => setTab("power")}>
          Power Rankings
        </button>
        <button className={tab === "playoffs" ? "active" : ""} onClick={() => setTab("playoffs")}>
          Playoff Odds
        </button>
      </div>
      {tab === "standings" && <Standings rows={standings} />}
      {tab === "power" && <PowerRankings rows={powerRankings} />}
      {tab === "playoffs" && <PlayoffOdds rows={playoffOdds} />}
    </div>
  );
}
