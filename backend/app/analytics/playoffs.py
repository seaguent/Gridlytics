import random


def simulate_season(
    current_records: dict,
    team_score_dist: dict,
    remaining_schedule: list,
    playoff_spots: int,
    num_trials: int,
    seed: int = 0,
) -> dict:
    rng = random.Random(seed)

    playoff_counts = {team_id: 0 for team_id in current_records}
    win_totals = {team_id: 0.0 for team_id in current_records}

    for _ in range(num_trials):
        wins = {team_id: record["wins"] for team_id, record in current_records.items()}
        points = {team_id: record["points_for"] for team_id, record in current_records.items()}

        for _week, team_a, team_b in remaining_schedule:
            mean_a, std_a = team_score_dist[team_a]["mean"], team_score_dist[team_a]["std"]
            mean_b, std_b = team_score_dist[team_b]["mean"], team_score_dist[team_b]["std"]
            score_a = rng.gauss(mean_a, std_a)
            score_b = rng.gauss(mean_b, std_b)

            points[team_a] += score_a
            points[team_b] += score_b

            if score_a > score_b:
                wins[team_a] += 1
            elif score_b > score_a:
                wins[team_b] += 1

        standings = sorted(
            current_records.keys(),
            key=lambda team_id: (wins[team_id], points[team_id]),
            reverse=True,
        )

        for team_id in standings[:playoff_spots]:
            playoff_counts[team_id] += 1
        for team_id in current_records:
            win_totals[team_id] += wins[team_id]

    return {
        team_id: {
            "playoff_odds": playoff_counts[team_id] / num_trials,
            "projected_wins": win_totals[team_id] / num_trials,
        }
        for team_id in current_records
    }
