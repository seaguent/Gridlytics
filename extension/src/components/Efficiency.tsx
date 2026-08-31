import { EfficiencyRow } from "../api";

export function Efficiency({ rows }: { rows: EfficiencyRow[] }) {
  return (
    <div className="gl-list">
      {rows.map((row, index) => (
        <div className="gl-row gl-row--power" key={row.team_id}>
          <span className="gl-row-rank">{index + 1}</span>
          <span className="gl-row-name">{row.display_name}</span>
          <span className="gl-power-score">
            {row.avg_efficiency === null ? "—" : `${(row.avg_efficiency * 100).toFixed(0)}%`}
          </span>
        </div>
      ))}
    </div>
  );
}
