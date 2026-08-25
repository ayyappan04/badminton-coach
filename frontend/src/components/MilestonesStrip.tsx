import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { MilestoneItem } from "../types";

const KIND_ICON: Record<string, string> = {
  matches: "🏸",
  doubles: "👥",
  score: "📈",
};

/** Shared progress milestones: derived facts about you and friends whose
 * profile scope allows sharing — never raw analysis data. */
export function MilestonesStrip() {
  const [milestones, setMilestones] = useState<MilestoneItem[]>([]);

  useEffect(() => {
    api.get<{ milestones: MilestoneItem[] }>("/community/milestones")
      .then((r) => setMilestones(r.milestones))
      .catch(() => {});
  }, []);

  if (milestones.length === 0) return null;

  return (
    <div className="flex gap-2 flex-wrap">
      {milestones.map((m, i) => (
        <span
          key={i}
          className="text-xs border border-[var(--separator)] bg-[var(--surface)] rounded-full px-3 py-1.5"
        >
          {KIND_ICON[m.kind] ?? "•"} <span className="font-medium">{m.who}</span>
          <span className="text-[var(--text-secondary)]"> — {m.milestone}</span>
        </span>
      ))}
    </div>
  );
}
