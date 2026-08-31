import { RankingRow } from "../api";

const POSITIONS = ["ALL", "QB", "RB", "WR", "TE", "K", "DEF"] as const;

export function Rankings({
  rows,
  position,
  onPositionChange,
}: {
  rows: RankingRow[];
  position: string;
  onPositionChange: (position: string) => void;
}) {
  return (
    <div>
      <div className="gl-position-filter">
        {POSITIONS.map((pos) => (
          <button
            key={pos}
            className={position === pos ? "gl-position gl-position--active" : "gl-position"}
            onClick={() => onPositionChange(pos)}
          >
            {pos}
          </button>
        ))}
      </div>
      <div className="gl-list">
        {rows.map((row, index) => (
          <div className="gl-row" key={row.platform_player_id}>
            <div className="gl-row-main">
              <span className="gl-row-rank">{index + 1}</span>
              <span className="gl-row-name">{row.name}</span>
              <span className="gl-row-record">{row.position}</span>
            </div>
            <div className="gl-row-stats">
              <span className="gl-stat">{row.projected_points.toFixed(1)} proj</span>
              <span className="gl-stat-sep">·</span>
              <span className="gl-stat">
                {row.floor !== null && row.ceiling !== null
                  ? `${row.floor.toFixed(1)}-${row.ceiling.toFixed(1)} range`
                  : "range n/a"}
              </span>
            </div>
          </div>
        ))}
        {rows.length === 0 && <div className="gl-loading">No ranked players yet.</div>}
      </div>
    </div>
  );
}
