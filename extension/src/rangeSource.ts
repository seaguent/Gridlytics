const SHORT_LABEL: Record<string, string> = {
  current_season: "season",
  blended_history: "blend",
  prior_season: "prior yr",
  position_prior: "pos. baseline",
};

export function rangeSourceShortLabel(rangeSource: string | null): string | null {
  return rangeSource ? (SHORT_LABEL[rangeSource] ?? null) : null;
}

export function rangeProvenanceText(rangeSource: string | null, sampleSize: number, position: string): string {
  switch (rangeSource) {
    case "current_season":
      return `Based on ${sampleSize} games this season`;
    case "blended_history":
      return `Based on ${sampleSize} games, blending prior and current season`;
    case "prior_season":
      return `Based on ${sampleSize} games last season`;
    case "position_prior":
      return `Limited history · ${position} baseline from ${sampleSize} games`;
    default:
      return "Range not available yet";
  }
}
