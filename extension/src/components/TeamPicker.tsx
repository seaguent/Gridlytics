import { useState } from "react";
import { StandingRow } from "../api";

export function TeamPicker({
  teams,
  onSelect,
  saving,
  label = "Which team is yours?",
}: {
  teams: StandingRow[];
  onSelect: (teamId: number) => void;
  saving: boolean;
  label?: string;
}) {
  const [selected, setSelected] = useState<number | "">("");

  return (
    <div className="gl-team-picker">
      <div className="gl-team-picker-label">{label}</div>
      <select
        className="gl-team-picker-select"
        value={selected}
        onChange={(event) => setSelected(event.target.value ? Number(event.target.value) : "")}
      >
        <option value="">Select a team...</option>
        {teams.map((team) => (
          <option key={team.team_id} value={team.team_id}>
            {team.display_name}
          </option>
        ))}
      </select>
      <button
        className="gl-connect"
        disabled={selected === "" || saving}
        onClick={() => selected !== "" && onSelect(selected)}
      >
        {saving ? "Saving..." : "Confirm"}
      </button>
    </div>
  );
}
