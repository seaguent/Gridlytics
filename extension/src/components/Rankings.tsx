import { RankingRow } from "../api";
import { rangeProvenanceText, rangeSourceShortLabel } from "../rangeSource";

const POSITIONS = ["ALL", "QB", "RB", "WR", "TE", "K", "DEF"] as const;

const TREND_ICON: Record<string, string> = {
  rising: "↑",
  falling: "↓",
  stable: "→",
};

function matchupLabel(rating: number): string {
  if (rating >= 65) return "easy";
  if (rating <= 35) return "tough";
  return "avg";
}

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
              {row.injury_status && row.injury_status.toUpperCase() !== "ACTIVE" && (
                <span className="gl-injury">{row.injury_status}</span>
              )}
              <span className="gl-row-record">{row.position}</span>
            </div>
            <div className="gl-row-stats">
              <span className="gl-stat">{row.projected_points.toFixed(1)} proj</span>
              <span className="gl-stat-sep">·</span>
              <span
                className="gl-stat"
                title={rangeProvenanceText(row.range_source, row.sample_size, row.position)}
              >
                {row.floor !== null && row.ceiling !== null
                  ? `${row.floor.toFixed(1)}-${row.ceiling.toFixed(1)} range${
                      rangeSourceShortLabel(row.range_source) ? ` (${rangeSourceShortLabel(row.range_source)})` : ""
                    }`
                  : "range n/a"}
              </span>
              {row.target_share !== null && (
                <>
                  <span className="gl-stat-sep">·</span>
                  <span className="gl-stat">
                    {(row.target_share * 100).toFixed(0)}% share
                    {row.usage_trend && ` ${TREND_ICON[row.usage_trend] ?? ""}`}
                  </span>
                </>
              )}
            </div>
            {row.target_share === null && row.experience_status === "rookie_or_limited_history" ? (
              <div className="gl-row-stats">
                <span className="gl-stat gl-stat--muted">
                  No NFL usage history · Rookie / limited history · Projection based on{" "}
                  {row.sources.join("/") || "platform"} data
                </span>
              </div>
            ) : (
              (row.snap_share !== null || row.red_zone_opportunities !== null || row.opponent !== null) && (
                <div className="gl-row-stats">
                  {row.snap_share !== null && (
                    <span className="gl-stat">{(row.snap_share * 100).toFixed(0)}% snaps</span>
                  )}
                  {row.red_zone_opportunities !== null && (
                    <>
                      {row.snap_share !== null && <span className="gl-stat-sep">·</span>}
                      <span className="gl-stat">{row.red_zone_opportunities} RZ looks</span>
                    </>
                  )}
                  {row.opponent !== null && (
                    <>
                      {(row.snap_share !== null || row.red_zone_opportunities !== null) && (
                        <span className="gl-stat-sep">·</span>
                      )}
                      <span className="gl-stat">
                        vs {row.opponent}
                        {row.matchup_rating !== null && ` (${matchupLabel(row.matchup_rating)})`}
                      </span>
                    </>
                  )}
                  {row.games_played > 0 && row.games_played < 3 && (
                    <>
                      <span className="gl-stat-sep">·</span>
                      <span className="gl-stat gl-stat--muted">
                        Limited sample: {row.games_played} game{row.games_played === 1 ? "" : "s"}
                      </span>
                    </>
                  )}
                </div>
              )
            )}
          </div>
        ))}
        {rows.length === 0 && <div className="gl-loading">No ranked players yet.</div>}
      </div>
    </div>
  );
}
