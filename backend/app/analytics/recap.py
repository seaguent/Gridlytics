import pandas as pd


def _dedupe_matchups(week_scores: pd.DataFrame) -> list[dict]:
    seen: set[frozenset] = set()
    matchups = []
    scores_by_team = dict(zip(week_scores["team_id"], week_scores["points"]))

    for row in week_scores.itertuples():
        if row.opponent_team_id is None:
            continue
        pair = frozenset({row.team_id, row.opponent_team_id})
        if pair in seen:
            continue
        seen.add(pair)

        opponent_points = scores_by_team[row.opponent_team_id]
        if row.points > opponent_points:
            winner, loser = row.team_id, row.opponent_team_id
        else:
            winner, loser = row.opponent_team_id, row.team_id

        matchups.append(
            {
                "team_a": row.team_id,
                "team_b": row.opponent_team_id,
                "winner": winner,
                "loser": loser,
                "margin": abs(row.points - opponent_points),
            }
        )
    return matchups


def find_closest_game(matchups: list[dict]) -> dict | None:
    if not matchups:
        return None
    return min(matchups, key=lambda m: m["margin"])


def find_biggest_upset(matchups: list[dict], power_scores: dict) -> dict | None:
    best = None
    best_gap = 0.0
    for m in matchups:
        winner_power = power_scores.get(m["winner"], 0.0)
        loser_power = power_scores.get(m["loser"], 0.0)
        gap = loser_power - winner_power
        if gap > best_gap:
            best_gap = gap
            best = {"winner_team_id": m["winner"], "loser_team_id": m["loser"], "power_gap": gap}
    return best


def find_unluckiest_team(week_scores: pd.DataFrame, matchups: list[dict]) -> dict | None:
    n = len(week_scores)
    if n < 2:
        return None

    ranks = week_scores["points"].rank(method="average")
    all_play_fraction = (ranks - 1) / (n - 1)
    scored = week_scores.assign(all_play_fraction=all_play_fraction)

    losers = {m["loser"] for m in matchups}
    candidates = scored[scored["team_id"].isin(losers)]
    if not len(candidates):
        return None

    row = candidates.loc[candidates["all_play_fraction"].idxmax()]
    return {"team_id": row["team_id"], "all_play_win_fraction": row["all_play_fraction"]}


def find_worst_bench_decision(bench_points: pd.DataFrame) -> dict | None:
    if not len(bench_points):
        return None
    row = bench_points.loc[bench_points["bench_points"].idxmax()]
    return {"team_id": row["team_id"], "bench_points": row["bench_points"]}


def generate_weekly_recap(
    week_scores: pd.DataFrame, power_scores: dict, bench_points: pd.DataFrame
) -> dict:
    matchups = _dedupe_matchups(week_scores)

    highest = week_scores.loc[week_scores["points"].idxmax()]
    lowest = week_scores.loc[week_scores["points"].idxmin()]

    return {
        "highest_scorer": {"team_id": highest["team_id"], "points": highest["points"]},
        "lowest_scorer": {"team_id": lowest["team_id"], "points": lowest["points"]},
        "closest_game": find_closest_game(matchups),
        "biggest_upset": find_biggest_upset(matchups, power_scores),
        "unluckiest_team": find_unluckiest_team(week_scores, matchups),
        "worst_bench_decision": find_worst_bench_decision(bench_points),
    }
