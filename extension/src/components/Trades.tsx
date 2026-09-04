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

function DeltaCard({
  label,
  result,
  weeksRemaining,
}: {
  label: string;
  result: TradeAnalysisResponse["your_team"];
  weeksRemaining: number;
}) {
  const weekWord = weeksRemaining === 1 ? "week" : "weeks";
  return (
    <div className="gl-row">
      <div className="gl-row-main">
        <span className="gl-row-name">{label}</span>
        <span className="gl-stat">
          {result.rest_of_season_delta >= 0 ? "+" : ""}
          {result.rest_of_season_delta.toFixed(1)} pts / {weeksRemaining} {weekWord}
        </span>
      </div>
      <div className="gl-row-stats">
        <span className="gl-stat">
          {result.rest_of_season_before.toFixed(1)} → {result.rest_of_season_after.toFixed(1)}
        </span>
      </div>
      <div className="gl-row-stats gl-stat--muted">
        This week: {result.current_week_delta >= 0 ? "+" : ""}
        {result.current_week_delta.toFixed(1)} ({result.current_week_before.toFixed(1)} →{" "}
        {result.current_week_after.toFixed(1)})
      </div>
      {Math.abs(result.actual_current_starters_points - result.current_week_before) > 0.05 && (
        <div className="gl-row-stats gl-stat--muted">
          Actual current lineup: {result.actual_current_starters_points.toFixed(1)} pts (not the optimal{" "}
          {result.current_week_before.toFixed(1)} used above -- unrelated to this trade)
        </div>
      )}
      {result.reasons.length > 0 && (
        <div className="gl-row-stats gl-stat--muted">Players received: {result.reasons.join(" · ")}</div>
      )}
    </div>
  );
}

function tradeVerdict(yourDelta: number, theirDelta: number, weeksRemaining: number): string {
  const diff = yourDelta - theirDelta;
  const perWeek = weeksRemaining > 0 ? diff / weeksRemaining : diff;
  if (Math.abs(perWeek) < 0.5) return "Roughly even";
  if (perWeek > 0) return perWeek < 2 ? "Slightly favors your team" : "Favors your team";
  return perWeek > -2 ? "Slightly favors their team" : "Favors their team";
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
          <div className="gl-trade-verdict">
            {tradeVerdict(
              result.your_team.rest_of_season_delta,
              result.other_team.rest_of_season_delta,
              result.weeks_remaining
            )}
          </div>
          <DeltaCard label="Your team" result={result.your_team} weeksRemaining={result.weeks_remaining} />
          <DeltaCard label="Their team" result={result.other_team} weeksRemaining={result.weeks_remaining} />
        </div>
      )}
    </div>
  );
}
