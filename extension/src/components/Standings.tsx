import { StandingRow } from "../api";

export function Standings({ rows }: { rows: StandingRow[] }) {
  const sorted = [...rows].sort(
    (a, b) => b.wins - a.wins || b.points_for - a.points_for
  );

  return (
    <div className="gl-list">
      {sorted.map((row, index) => (
        <div className="gl-row" key={row.team_id}>
          <div className="gl-row-main">
            <span className="gl-row-rank">{index + 1}</span>
            <span className="gl-row-name">{row.display_name}</span>
            <span className="gl-row-record">
              {row.wins}-{row.losses}
            </span>
          </div>
          <div className="gl-row-stats">
            <span className="gl-stat">{row.points_for.toFixed(1)} pts</span>
            <span className="gl-stat-sep">·</span>
            <span className="gl-stat">{row.expected_wins.toFixed(1)} xWins</span>
          </div>
        </div>
      ))}
    </div>
  );
}
