from dataclasses import dataclass


@dataclass
class SourceAccuracy:
    source: str
    mae: float
    sample_size: int


@dataclass
class ProjectionAccuracyReport:
    all_available: list[SourceAccuracy]
    common_sample: list[SourceAccuracy]


def _mae_by_source(rows: list[dict], sources: list[str]) -> list[SourceAccuracy]:
    result = []
    for source in sources:
        source_rows = [r for r in rows if r["source"] == source]
        if not source_rows:
            continue
        mae = sum(abs(r["projected_points"] - r["actual_points"]) for r in source_rows) / len(source_rows)
        result.append(SourceAccuracy(source=source, mae=mae, sample_size=len(source_rows)))
    return result


def compute_projection_accuracy(records: list[dict]) -> ProjectionAccuracyReport:
    if not records:
        return ProjectionAccuracyReport(all_available=[], common_sample=[])

    sources = sorted({r["source"] for r in records})
    all_available = _mae_by_source(records, sources)

    keys_by_source = {
        source: {(r["platform_player_id"], r["week"]) for r in records if r["source"] == source}
        for source in sources
    }
    common_keys = set.intersection(*keys_by_source.values())
    common_rows = [r for r in records if (r["platform_player_id"], r["week"]) in common_keys]
    common_sample = _mae_by_source(common_rows, sources)

    return ProjectionAccuracyReport(all_available=all_available, common_sample=common_sample)
