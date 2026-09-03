import { WaiverResponse } from "../api";

export function Waivers({ data }: { data: WaiverResponse | null }) {
  if (!data) return <div className="gl-loading">Loading...</div>;

  if (data.mode === "unsupported_platform") {
    return <div className="gl-loading">Waivers aren't available for this platform yet.</div>;
  }

  if (data.recommendations.length === 0) {
    return <div className="gl-loading">No real upgrades available right now.</div>;
  }

  return (
    <div className="gl-list">
      {data.mode === "projection_only" && (
        <div className="gl-scoring-note">
          Pick your team on the Start/Sit tab to see real lineup-improvement comparisons — ranked
          by Gridlytics projection for now.
        </div>
      )}
      {data.recommendations.map((row) => (
        <div className="gl-row" key={row.platform_player_id}>
          <div className="gl-row-main">
            <span className="gl-row-name">{row.name}</span>
            <span className="gl-row-record">
              {row.position}
              {row.team ? ` · ${row.team}` : ""}
            </span>
          </div>
          <div className="gl-row-stats">
            {row.projected_lineup_improvement !== null && (
              <span className="gl-stat">+{row.projected_lineup_improvement.toFixed(1)} lineup pts</span>
            )}
            {row.value_over_replacement !== null && row.projected_lineup_improvement === null && (
              <span className="gl-stat">{row.value_over_replacement.toFixed(1)} VOR</span>
            )}
            {row.replaces_name && (
              <>
                <span className="gl-stat-sep">·</span>
                <span className="gl-stat">Replaces {row.replaces_name}</span>
              </>
            )}
          </div>
          {row.reasons.length > 0 && (
            <div className="gl-row-stats gl-stat--muted">{row.reasons.join(" · ")}</div>
          )}
        </div>
      ))}
    </div>
  );
}
