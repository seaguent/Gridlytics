import { PlayoffOddsRow } from "../api";

export function PlayoffOdds({ rows }: { rows: PlayoffOddsRow[] }) {
  return (
    <div className="gl-list">
      {rows.map((row) => (
        <div className="gl-bar-row" key={row.team_id}>
          <div className="gl-bar-row-top">
            <span className="gl-row-name">{row.display_name}</span>
            <span className="gl-bar-pct">{(row.playoff_odds * 100).toFixed(0)}%</span>
          </div>
          <div className="gl-bar-track">
            <div
              className="gl-bar-fill"
              style={{ width: `${Math.round(row.playoff_odds * 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
