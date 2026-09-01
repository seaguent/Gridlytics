import { useEffect, useState } from "react";
import {
  EfficiencyRow,
  fetchPlayoffOdds,
  fetchPowerRankings,
  fetchRosterEfficiency,
  fetchStandings,
  PlayoffOddsRow,
  PowerRankingRow,
  StandingRow,
} from "../api";

export function useAnalytics(token: string | null, refreshKey: number = 0) {
  const [standings, setStandings] = useState<StandingRow[] | null>(null);
  const [powerRankings, setPowerRankings] = useState<PowerRankingRow[] | null>(null);
  const [playoffOdds, setPlayoffOdds] = useState<PlayoffOddsRow[] | null>(null);
  const [efficiency, setEfficiency] = useState<EfficiencyRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      fetchStandings(token),
      fetchPowerRankings(token),
      fetchPlayoffOdds(token),
      fetchRosterEfficiency(token),
    ])
      .then(([s, p, o, e]) => {
        setStandings(s);
        setPowerRankings(p);
        setPlayoffOdds(o);
        setEfficiency(e);
      })
      .catch((err: Error) => setError(err.message));
  }, [token, refreshKey]);

  return { standings, powerRankings, playoffOdds, efficiency, error };
}
