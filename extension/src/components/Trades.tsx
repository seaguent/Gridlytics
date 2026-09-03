import { useState } from "react";
import {
  fetchTeamRoster,
  fetchTradeAnalysis,
  StandingRow,
  TeamRosterPlayer,
  TradeAnalysisResponse,
} from "../api";
import { TeamPicker } from "./TeamPicker";

const POSITION_ORDER = ["QB", "RB", "WR", "TE", "FLEX", "K", "DEF"];

function groupByPosition(players: TeamRosterPlayer[]): [string, TeamRosterPlayer[]][] {
  const groups = new Map<string, TeamRosterPlayer[]>();
  for (const player of players) {
    const group = groups.get(player.position) ?? [];
    group.push(player);
    groups.set(player.position, group);
  }
  const ordered = [...groups.keys()].sort((a, b) => {
    const ai = POSITION_ORDER.indexOf(a);
    const bi = POSITION_ORDER.indexOf(b);
    return (ai === -1 ? POSITION_ORDER.length : ai) - (bi === -1 ? POSITION_ORDER.length : bi);
  });
  return ordered.map((position) => [position, groups.get(position)!]);
}

function PlayerChecklist({
  roster,
  selected,
  onToggle,
}: {
  roster: TeamRosterPlayer[] | null;
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  if (roster === null) return <div className="gl-loading">Loading...</div>;
  if (roster.length === 0) return <div className="gl-loading">No players on this roster.</div>;

  return (
    <>
      {groupByPosition(roster).map(([position, players]) => (
        <div key={position}>
          <div className="gl-position-group-label">{position}</div>
          {players.map((p) => (
            <label className="gl-player-checkbox" key={p.platform_player_id}>
              <input
                type="checkbox"
                checked={selected.has(p.platform_player_id)}
                onChange={() => onToggle(p.platform_player_id)}
              />
              <span className="gl-player-checkbox-name">{p.name}</span>
              <span className="gl-player-checkbox-position">{p.position}</span>
            </label>
          ))}
        </div>
      ))}
    </>
  );
}

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

  const resetToPicker = () => {
    setOtherTeamId(null);
    setMyRoster(null);
    setTheirRoster(null);
    setGiveIds(new Set());
    setReceiveIds(new Set());
    setResult(null);
    setError(null);
  };

  const handleSelectPartner = async (teamId: number) => {
    setOtherTeamId(teamId);
    setResult(null);
    setError(null);
    setGiveIds(new Set());
    setReceiveIds(new Set());
    setMyRoster(null);
    setTheirRoster(null);
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

  const partnerName = standings.find((t) => t.team_id === otherTeamId)?.display_name ?? "this team";
  const canEvaluate = giveIds.size > 0 || receiveIds.size > 0;

  return (
    <div>
      <div className="gl-trade-partner">
        <span className="gl-trade-partner-name">Trading with {partnerName}</span>
        <button className="gl-trade-change-partner" onClick={resetToPicker}>
          Change
        </button>
      </div>

      <div className="gl-trade-section">
        <div className="gl-trade-section-label">You give</div>
        <PlayerChecklist roster={myRoster} selected={giveIds} onToggle={(id) => toggle(giveIds, setGiveIds, id)} />
      </div>

      <div className="gl-trade-section">
        <div className="gl-trade-section-label">You receive</div>
        <PlayerChecklist
          roster={theirRoster}
          selected={receiveIds}
          onToggle={(id) => toggle(receiveIds, setReceiveIds, id)}
        />
      </div>

      <button className="gl-connect" onClick={handleEvaluate} disabled={evaluating || !canEvaluate}>
        {evaluating ? "Evaluating..." : "Evaluate Trade"}
      </button>

      {error && <div className="gl-error">{error}</div>}

      {result && (
        <div className="gl-list gl-trade-results">
          <DeltaCard label="Your team" result={result.your_team} />
          <DeltaCard label="Their team" result={result.other_team} />
        </div>
      )}
    </div>
  );
}
