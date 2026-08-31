import { WeeklyRecap } from "../api";

function HighlightCard({
  label,
  team,
  detail,
  empty,
}: {
  label: string;
  team: string | null;
  detail: string | null;
  empty: string;
}) {
  return (
    <div className="gl-recap-card">
      <div className="gl-recap-label">{label}</div>
      {team ? (
        <div className="gl-recap-value">
          <span className="gl-recap-team">{team}</span>
          <span className="gl-recap-detail">{detail}</span>
        </div>
      ) : (
        <div className="gl-recap-empty">{empty}</div>
      )}
    </div>
  );
}

export function Recap({ recap }: { recap: WeeklyRecap }) {
  return (
    <div className="gl-list">
      <HighlightCard
        label="Highest Scorer"
        team={recap.highest_scorer?.team_id_name ?? null}
        detail={recap.highest_scorer ? `${recap.highest_scorer.points!.toFixed(1)} pts` : null}
        empty="No data yet"
      />
      <HighlightCard
        label="Lowest Scorer"
        team={recap.lowest_scorer?.team_id_name ?? null}
        detail={recap.lowest_scorer ? `${recap.lowest_scorer.points!.toFixed(1)} pts` : null}
        empty="No data yet"
      />
      <HighlightCard
        label="Closest Game"
        team={
          recap.closest_game
            ? `${recap.closest_game.team_a_name} vs ${recap.closest_game.team_b_name}`
            : null
        }
        detail={recap.closest_game ? `${recap.closest_game.margin.toFixed(1)} pt margin` : null}
        empty="No data yet"
      />
      <HighlightCard
        label="Biggest Upset"
        team={
          recap.biggest_upset
            ? `${recap.biggest_upset.winner_team_id_name} over ${recap.biggest_upset.loser_team_id_name}`
            : null
        }
        detail={
          recap.biggest_upset ? `${recap.biggest_upset.power_gap.toFixed(1)} pt underdog win` : null
        }
        empty="No upsets this week"
      />
      <HighlightCard
        label="Unluckiest Team"
        team={recap.unluckiest_team?.team_id_name ?? null}
        detail={
          recap.unluckiest_team
            ? `${(recap.unluckiest_team.all_play_win_fraction! * 100).toFixed(0)}% all-play, still lost`
            : null
        }
        empty="No data yet"
      />
      <HighlightCard
        label="Worst Bench Decision"
        team={recap.worst_bench_decision?.team_id_name ?? null}
        detail={
          recap.worst_bench_decision
            ? `${recap.worst_bench_decision.bench_points!.toFixed(1)} pts left on bench`
            : null
        }
        empty="No data yet"
      />
    </div>
  );
}
