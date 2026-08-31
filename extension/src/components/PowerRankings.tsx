import { PowerRankingRow } from "../api";

export function PowerRankings({ rows }: { rows: PowerRankingRow[] }) {
  return (
    <div className="gl-list">
      {rows.map((row, index) => (
        <div className="gl-row gl-row--power" key={row.team_id}>
          <span className="gl-row-rank">{index + 1}</span>
          <span className="gl-row-name">{row.display_name}</span>
          <span className="gl-power-score">{row.power_score.toFixed(1)}</span>
        </div>
      ))}
    </div>
  );
}
