import { createRoot } from "react-dom/client";
import { Overlay, OverlayLeague } from "./components/Overlay";
import { extractEspnLeagueInfo } from "./espn";
import { extractLeagueId } from "./sleeper";

function detectLeague(): OverlayLeague | null {
  const sleeperLeagueId = extractLeagueId(window.location.href);
  if (sleeperLeagueId) {
    return { platform: "sleeper", leagueId: sleeperLeagueId };
  }

  const espnInfo = extractEspnLeagueInfo(window.location.href);
  if (espnInfo) {
    return { platform: "espn", leagueId: espnInfo.leagueId, season: espnInfo.season };
  }

  return null;
}

const league = detectLeague();

if (league) {
  const host = document.createElement("div");
  host.id = "gridlytics-host";
  document.body.appendChild(host);

  const shadowRoot = host.attachShadow({ mode: "open" });
  const container = document.createElement("div");
  shadowRoot.appendChild(container);

  createRoot(container).render(<Overlay league={league} />);
}
