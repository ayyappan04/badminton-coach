import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Drill, PlayerProfile } from "../types";
import { EmptyState, SkeletonRows, formatScore, titleCase } from "../ui";

/** Bridges analytics to action: each priority carries the measured score that
 *  produced it, then the drills that target it. Targets are NOT shown because
 *  the backend does not define any — inventing them would be fiction. */
export function TrainingPlanPanel({ profile }: { profile: PlayerProfile }) {
  const [drills, setDrills] = useState<Drill[] | null>(null);
  const tags = profile.training_plan?.recommended_drill_tags ?? [];
  const tagKey = tags.join(",");

  useEffect(() => {
    if (!tags.length) {
      setDrills([]);
      return;
    }
    let cancelled = false;
    setDrills(null);
    Promise.all(tags.map((t) => api.get<Drill[]>(`/drills?tag=${encodeURIComponent(t)}`)))
      .then((results) => {
        if (cancelled) return;
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
      })
      .catch(() => !cancelled && setDrills([]));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tagKey]);

  if (profile.matches_analyzed_count === 0) {
    return <p className="text-[13px]" style={{ color: "var(--text-tertiary)" }}>{profile.message}</p>;
  }

  const priorities = profile.training_plan?.priority_areas ?? [];

  return (
    <div className="space-y-5">
      {profile.training_plan?.weekly_theme && (
        <p className="text-[15px] font-medium" style={{ color: "var(--text-primary)" }}>
          {profile.training_plan.weekly_theme}
        </p>
      )}

      {priorities.length > 0 && (
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider mb-2.5" style={{ color: "var(--text-tertiary)" }}>
            Priorities
          </p>
          <ol className="divide-y" style={{ borderColor: "var(--separator)" }}>
            {priorities.map((area, i) => {
              const score = profile.radar_scores[area.replace(/ /g, "_")]?.score ?? null;
              return (
                <li key={area} className="py-2.5 flex items-baseline justify-between gap-3 first:pt-0">
                  <span className="text-[14px]" style={{ color: "var(--text-secondary)" }}>
                    <span className="tnum mr-2" style={{ color: "var(--text-tertiary)" }}>
                      {i + 1}
                    </span>
                    {titleCase(area)}
                  </span>
                  <span className="tnum text-[15px] font-medium" style={{ color: "var(--text-primary)" }}>
                    {formatScore(score)}
                    {score !== null && (
                      <span className="text-[12px] font-normal" style={{ color: "var(--text-tertiary)" }}>
                        {" "}
                        / 100
                      </span>
                    )}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      )}

      <div>
        <p className="text-[11px] font-medium uppercase tracking-wider mb-2.5" style={{ color: "var(--text-tertiary)" }}>
          Recommended drills
        </p>
        {drills === null ? (
          <SkeletonRows rows={3} />
        ) : drills.length === 0 ? (
          <EmptyState
            compact
            title="No drills matched yet"
            description="Analyze more matches and the plan will target specific weaknesses."
          />
        ) : (
          <ul className="divide-y" style={{ borderColor: "var(--separator)" }}>
            {drills.map((d) => (
              <li key={d.id} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[14px] font-medium" style={{ color: "var(--text-primary)" }}>
                    {d.name}
                  </span>
                  <span className="text-[11px] uppercase tracking-wider shrink-0" style={{ color: "var(--text-tertiary)" }}>
                    {d.category}
                  </span>
                </div>
                <p className="text-[13px] mt-1 leading-snug" style={{ color: "var(--text-secondary)" }}>
                  {d.description}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
