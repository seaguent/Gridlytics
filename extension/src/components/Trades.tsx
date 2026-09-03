import { useState } from "react";
import {
  fetchTeamRoster,
  fetchTradeAnalysis,
  StandingRow,
  TeamRosterPlayer,
  TradeAnalysisResponse,
} from "../api";
import { TeamPicker } from "./TeamPicker";

function DeltaCard({ label, result }: { label: string; result: TradeAnalysisResponse["your_team"] }) {
  return (
    <div className="gl-row">
      <div className="gl-row-main">
        <span className="gl-row-name">{label}</span>
        <span className="gl-stat">
          {result.delta >= 0 ? "+" : ""}
          {result.delta.toFixed(1)} pts
        </span>
      </div>
      <div className="gl-row-stats">
        <span className="gl-stat">
          {result.current_points.toFixed(1)} → {result.projected_points.toFixed(1)}
        </span>
      </div>
      {result.reasons.length > 0 && (
        <div className="gl-row-stats gl-stat--muted">{result.reasons.join(" · ")}</div>
      )}
    </div>
  );
}

export function Trades({
  token,
  myTeamId,
  standings,
}: {
  token: string;
  myTeamId: number;
  standings: StandingRow[];
}) {
  const [otherTeamId, setOtherTeamId] = useState<number | null>(null);
  const [myRoster, setMyRoster] = useState<TeamRosterPlayer[] | null>(null);
  const [theirRoster, setTheirRoster] = useState<TeamRosterPlayer[] | null>(null);
  const [giveIds, setGiveIds] = useState<Set<string>>(new Set());
  const [receiveIds, setReceiveIds] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<TradeAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);

  const handleSelectPartner = async (teamId: number) => {
    setOtherTeamId(teamId);
    setResult(null);
    setError(null);
    setGiveIds(new Set());
    setReceiveIds(new Set());
    const [mine, theirs] = await Promise.all([fetchTeamRoster(token, myTeamId), fetchTeamRoster(token, teamId)]);
    setMyRoster(mine);
    setTheirRoster(theirs);
  };

  const toggle = (set: Set<string>, setSet: (s: Set<string>) => void, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSet(next);
  };

  const handleEvaluate = async () => {
    if (otherTeamId === null || (giveIds.size === 0 && receiveIds.size === 0)) return;
    setEvaluating(true);
    setError(null);
    try {
      const response = await fetchTradeAnalysis(token, otherTeamId, [...giveIds], [...receiveIds]);
      setResult(response);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setEvaluating(false);
    }
  };

  if (otherTeamId === null) {
    return (
      <TeamPicker
        teams={standings.filter((t) => t.team_id !== myTeamId)}
        onSelect={handleSelectPartner}
        saving={false}
        label="Who are you trading with?"
      />
    );
  }

  return (
    <div className="gl-list">
      <div className="gl-row">
        <div className="gl-row-main">
          <span className="gl-row-name">You give</span>
        </div>
        {(myRoster ?? []).map((p) => (
          <label key={p.platform_player_id} className="gl-row-stats">
            <input
              type="checkbox"
              checked={giveIds.has(p.platform_player_id)}
              onChange={() => toggle(giveIds, setGiveIds, p.platform_player_id)}
            />
            {p.name} ({p.position})
          </label>
        ))}
      </div>
      <div className="gl-row">
        <div className="gl-row-main">
          <span className="gl-row-name">You receive</span>
        </div>
        {(theirRoster ?? []).map((p) => (
          <label key={p.platform_player_id} className="gl-row-stats">
            <input
              type="checkbox"
              checked={receiveIds.has(p.platform_player_id)}
              onChange={() => toggle(receiveIds, setReceiveIds, p.platform_player_id)}
            />
            {p.name} ({p.position})
          </label>
        ))}
      </div>
      <button className="gl-connect" onClick={handleEvaluate} disabled={evaluating}>
        {evaluating ? "Evaluating..." : "Evaluate Trade"}
      </button>
      {error && <div className="gl-error">{error}</div>}
      {result && (
        <>
          <DeltaCard label="Your team" result={result.your_team} />
          <DeltaCard label="Their team" result={result.other_team} />
        </>
      )}
    </div>
  );
}
