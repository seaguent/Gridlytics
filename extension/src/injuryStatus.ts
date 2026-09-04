const OUT_STATUSES = new Set([
  "OUT",
  "IR",
  "INJURY_RESERVE",
  "PUP",
  "NFI",
  "SUS",
  "SUSPENSION",
  "SUSPENDED",
  "NA",
]);

const QUESTIONABLE_STATUSES = new Set([
  "QUESTIONABLE",
  "DOUBTFUL",
  "DAY_TO_DAY",
  "COV",
  "DNR",
]);

export function injuryTagClass(status: string): string {
  const normalized = status.trim().toUpperCase();
  if (OUT_STATUSES.has(normalized)) return "gl-injury gl-injury--out";
  if (QUESTIONABLE_STATUSES.has(normalized)) return "gl-injury gl-injury--questionable";
  return "gl-injury";
}
