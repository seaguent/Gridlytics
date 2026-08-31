import { createRoot } from "react-dom/client";
import { Overlay } from "./components/Overlay";
import { extractLeagueId } from "./sleeper";

const leagueId = extractLeagueId(window.location.href);

if (leagueId) {
  const host = document.createElement("div");
  host.id = "gridlytics-host";
  document.body.appendChild(host);

  const shadowRoot = host.attachShadow({ mode: "open" });
  const container = document.createElement("div");
  shadowRoot.appendChild(container);

  createRoot(container).render(<Overlay leagueId={leagueId} />);
}
