export function priorSeasonWeightLabel(weight: number | null): string {
  if (weight === null) return "";
  if (weight < 0.3) return "mostly this season's usage";
  if (weight <= 0.7) return "blending last season and this season";
  return "mostly last season's usage, limited 2026 games so far";
}

export function dominantCategoryLabel(category: string | null): string {
  if (category === "passing") return "expected attempts";
  if (category === "rushing") return "expected carries";
  if (category === "receiving") return "expected targets";
  return "";
}
