import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Drill, PlayerProfile } from "../types";

export function TrainingPlanPanel({ profile }: { profile: PlayerProfile }) {
  const [drills, setDrills] = useState<Drill[]>([]);
  const tags = profile.training_plan?.recommended_drill_tags || [];

  useEffect(() => {
    if (tags.length === 0) return;
    Promise.all(tags.map((t) => api.get<Drill[]>(`/drills?tag=${encodeURIComponent(t)}`))).then((results) => {
      const seen = new Set<string>();
      const merged: Drill[] = [];
      for (const list of results) {
        for (const d of list) {
          if (!seen.has(d.id)) {
            seen.add(d.id);
            merged.push(d);
          }
        }
      }
      setDrills(merged);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tags.join(",")]);

  if (profile.matches_analyzed_count === 0) {
    return <p className="text-sm text-[var(--color-ink-soft)]">{profile.message}</p>;
  }

  return (
    <div>
      {profile.training_plan?.weekly_theme && (
        <p className="text-sm font-medium mb-3">{profile.training_plan.weekly_theme}</p>
      )}
      {profile.training_plan?.priority_areas && profile.training_plan.priority_areas.length > 0 && (
        <div className="flex gap-2 mb-4 flex-wrap">
          {profile.training_plan.priority_areas.map((a) => (
            <span key={a} className="text-xs bg-[var(--color-accent-soft)] text-[var(--color-accent)] px-2.5 py-1 rounded-full">
              Priority: {a}
            </span>
          ))}
        </div>
      )}
      <div className="grid sm:grid-cols-2 gap-3">
        {drills.map((d) => (
          <div key={d.id} className="border border-[var(--color-border)] rounded-lg p-3 bg-[var(--color-card)]">
            <div className="flex justify-between items-start mb-1">
              <span className="text-sm font-medium">{d.name}</span>
              <span className="text-[10px] text-[var(--color-ink-soft)] uppercase">{d.category}</span>
            </div>
            <p className="text-xs text-[var(--color-ink-soft)]">{d.description}</p>
          </div>
        ))}
        {drills.length === 0 && (
          <p className="text-sm text-[var(--color-ink-soft)]">No specific drills matched yet — analyze more matches to refine this.</p>
        )}
      </div>
    </div>
  );
}
