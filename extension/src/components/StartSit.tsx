import { StartSitPlayerRow, StartSitResponse, StartSitSummary } from "../api";
import { dominantCategoryLabel, priorSeasonWeightLabel } from "../nativeProjection";

function GridlyticsRow({ row }: { row: StartSitPlayerRow }) {
  if (row.gridlytics_projected_points === null || row.projected_points === null) return null;
  const delta = row.gridlytics_projected_points - row.projected_points;
  return (
    <div className="gl-row-stats">
      <span className="gl-stat">
        Gridlytics {row.gridlytics_projected_points.toFixed(1)} ({delta >= 0 ? "↑" : "↓"} {Math.abs(delta).toFixed(1)})
      </span>
      {row.gridlytics_expected_opportunities !== null && (
        <>
          <span className="gl-stat-sep">·</span>
          <span className="gl-stat gl-stat--muted">
            {row.gridlytics_expected_opportunities.toFixed(1)} {dominantCategoryLabel(row.gridlytics_dominant_category)},{" "}
            {priorSeasonWeightLabel(row.gridlytics_prior_season_weight)}
          </span>
        </>
      )}
      {row.gridlytics_lower_confidence && (
        <>
          <span className="gl-stat-sep">·</span>
          <span className="gl-stat gl-stat--muted">Limited confidence for TE with little NFL history</span>
        </>
      )}
    </div>
  );
}

function SummaryBanner({ summary }: { summary: StartSitSummary }) {
  if (summary.changes_count === 0) {
    return <div className="gl-summary-banner gl-summary-banner--optimal">Your lineup is already optimized</div>;
  }
  const sign = summary.projected_points_change >= 0 ? "+" : "";
  const plural = summary.changes_count === 1 ? "" : "s";
  return (
    <div className="gl-summary-banner">
      {summary.changes_count} suggested change{plural} · {sign}
      {summary.projected_points_change.toFixed(1)} projected points
    </div>
  );
}

function ReasonsDetails({ row }: { row: StartSitPlayerRow }) {
  if (row.reasons.length === 0) return null;
  return (
    <details className="gl-details">
      <summary>More details</summary>
      <ul className="gl-reasons">
        {row.reasons.map((reason, index) => (
          <li key={index}>{reason}</li>
        ))}
      </ul>
    </details>
  );
}

function SwapCard({ row }: { row: StartSitPlayerRow }) {
  const comparison = row.comparison;
  const gapText =
    comparison && Math.abs(comparison.projection_gap) >= 0.05
      ? ` — +${comparison.projection_gap.toFixed(1)} pts`
      : "";

  return (
    <div className="gl-row gl-row--swap">
      <div className="gl-row-main">
        <span className="gl-action-badge gl-action-badge--swap">START</span>
        <span className="gl-row-name">{row.name}</span>
        {row.injury_status && row.injury_status.toUpperCase() !== "ACTIVE" && (
          <span className="gl-injury">{row.injury_status}</span>
        )}
        <span className="gl-row-record">{row.recommended_slot}</span>
      </div>
      <div className="gl-swap-headline">
        Start {row.name}
        {row.swap_out_name && ` over ${row.swap_out_name}`}
        {gapText}
        {comparison?.is_close_call && <span className="gl-close-call">Close call</span>}
      </div>
      {comparison && comparison.this_player_labels.length > 0 && (
        <div className="gl-label-row">
          {comparison.this_player_labels.map((label) => (
            <span className="gl-label" key={label}>
              {label}
            </span>
          ))}
        </div>
      )}
      {comparison && comparison.opponent_risks.length > 0 && (
        <div className="gl-comparison-note">
          {row.swap_out_name} risk: {comparison.opponent_risks.join(", ")}
        </div>
      )}
      <GridlyticsRow row={row} />
      <ReasonsDetails row={row} />
    </div>
  );
}

function ConfirmedCard({ row, showSlot }: { row: StartSitPlayerRow; showSlot?: boolean }) {
  const badge = row.action === "start" ? "START" : row.action === "swap_out" ? "OUT" : null;
  const badgeClass = row.action === "start" ? "gl-action-badge--confirmed" : "gl-action-badge--out";

  return (
    <div className="gl-row">
      <div className="gl-row-main">
        {badge && <span className={`gl-action-badge ${badgeClass}`}>{badge}</span>}
        <span className="gl-row-name">{row.name}</span>
        {row.injury_status && row.injury_status.toUpperCase() !== "ACTIVE" && (
          <span className="gl-injury">{row.injury_status}</span>
        )}
        <span className="gl-row-record">
          {showSlot && row.recommended_slot ? row.recommended_slot : row.position}
        </span>
      </div>
      <div className="gl-row-stats">
        <span className="gl-stat">
          {row.projected_points !== null ? `${row.projected_points.toFixed(1)} proj` : "no projection"}
        </span>
      </div>
      <GridlyticsRow row={row} />
      <ReasonsDetails row={row} />
    </div>
  );
}

function PlayerCard({ row, showSlot }: { row: StartSitPlayerRow; showSlot?: boolean }) {
  if (row.action === "swap_in") return <SwapCard row={row} />;
  return <ConfirmedCard row={row} showSlot={showSlot} />;
}

export function StartSit({ data }: { data: StartSitResponse }) {
  const hasRoster = data.starters.length + data.bench.length + data.unavailable.length > 0;

  if (!hasRoster) {
    return <div className="gl-loading">No roster data yet for this team.</div>;
  }

  return (
    <div>
      <SummaryBanner summary={data.summary} />

      <div className="gl-section-label">Start · {data.optimal_points.toFixed(1)} projected pts</div>
      <div className="gl-list">
        {data.starters.map((row) => (
          <PlayerCard key={row.platform_player_id} row={row} showSlot />
        ))}
      </div>

      {data.bench.length > 0 && (
        <>
          <div className="gl-section-label">Bench</div>
          <div className="gl-list">
            {data.bench.map((row) => (
              <PlayerCard key={row.platform_player_id} row={row} />
            ))}
          </div>
        </>
      )}

      {data.unavailable.length > 0 && (
        <>
          <div className="gl-section-label">Unavailable</div>
          <div className="gl-list">
            {data.unavailable.map((row) => (
              <PlayerCard key={row.platform_player_id} row={row} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
