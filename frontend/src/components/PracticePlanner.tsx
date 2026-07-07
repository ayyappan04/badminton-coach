import { useEffect, useState } from "react";
import { api } from "../api/client";

interface PracticePlan {
  plan_id: string;
  kind: string;
  scheduled_at: string;
  location: string | null;
  notes: string | null;
}

export function PracticePlanner() {
  const [plans, setPlans] = useState<PracticePlan[]>([]);
  const [kind, setKind] = useState("practice");
  const [scheduledAt, setScheduledAt] = useState("");
  const [location, setLocation] = useState("");
  const [notes, setNotes] = useState("");

  function refresh() {
    api.get<PracticePlan[]>("/practice-plans").then(setPlans).catch(() => {});
  }

  useEffect(refresh, []);

  async function createPlan() {
    if (!scheduledAt) return;
    await api.post("/practice-plans", {
      kind,
      participants: [],
      scheduled_at: new Date(scheduledAt).toISOString(),
      location: location || null,
      notes: notes || null,
      linked_drill_ids: [],
    });
    setScheduledAt("");
    setLocation("");
    setNotes("");
    refresh();
  }

  return (
    <div>
      <div className="grid sm:grid-cols-2 gap-2 mb-3">
        <select value={kind} onChange={(e) => setKind(e.target.value)} className="border border-[var(--color-border)] rounded-md px-2 py-1.5 text-sm">
          <option value="practice">Practice session</option>
          <option value="match">Match</option>
        </select>
        <input
          type="datetime-local"
          value={scheduledAt}
          onChange={(e) => setScheduledAt(e.target.value)}
          className="border border-[var(--color-border)] rounded-md px-2 py-1.5 text-sm"
        />
        <input
          placeholder="Location"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          className="border border-[var(--color-border)] rounded-md px-2 py-1.5 text-sm"
        />
        <input
          placeholder="Notes (e.g. focus drills)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="border border-[var(--color-border)] rounded-md px-2 py-1.5 text-sm"
        />
      </div>
      <button onClick={createPlan} className="bg-[var(--color-accent)] text-white text-sm px-3 py-1.5 rounded-md mb-4">
        + Plan session
      </button>
      <div className="flex flex-col gap-2">
        {plans.map((p) => (
          <div key={p.plan_id} className="border border-[var(--color-border)] rounded-lg px-3 py-2 bg-[var(--color-card)]">
            <p className="text-sm font-medium">
              {p.kind === "match" ? "Match" : "Practice"} · {new Date(p.scheduled_at).toLocaleString()}
            </p>
            <p className="text-xs text-[var(--color-ink-soft)]">
              {p.location || "No location set"}
              {p.notes ? ` · ${p.notes}` : ""}
            </p>
          </div>
        ))}
        {plans.length === 0 && <p className="text-sm text-[var(--color-ink-soft)]">Nothing planned yet.</p>}
      </div>
    </div>
  );
}
