import { useEffect, useState } from "react";
import { api } from "../api/client";
import { FriendsPanel } from "../components/FriendsPanel";
import { PracticePlanner } from "../components/PracticePlanner";
import { PrivacyControls } from "../components/PrivacyControls";
import { ClubsPanel } from "../components/ClubsPanel";
import { SharedClipsPanel } from "../components/SharedClipsPanel";
import { useAuth } from "../context/AuthContext";

export function Community() {
  const { user } = useAuth();
  const [streak, setStreak] = useState<number | null>(null);

  useEffect(() => {
    api.get<{ streak_weeks: number }>("/community/streak").then((r) => setStreak(r.streak_weeks)).catch(() => {});
  }, []);

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-8">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold mb-1">Community &amp; training</h1>
          <p className="text-sm text-[var(--color-ink-soft)]">
            Connect with training partners, plan sessions, and control what others can see.
          </p>
        </div>
        {streak !== null && streak > 0 && (
          <div className="border border-[var(--color-court)]/40 bg-[var(--color-court-soft)] rounded-lg px-4 py-2 text-sm">
            <span className="font-semibold text-[var(--color-court)]">{streak}-week</span>{" "}
            <span className="text-[var(--color-ink-soft)]">training streak — matches uploaded or practice planned every week</span>
          </div>
        )}
      </div>

      <div className="grid md:grid-cols-2 gap-8">
        <section>
          <h2 className="font-semibold mb-3">Friends &amp; training partners</h2>
          <FriendsPanel />
        </section>
        <section>
          <h2 className="font-semibold mb-3">Practice &amp; match planning</h2>
          <PracticePlanner />
        </section>
      </div>

      <div className="grid md:grid-cols-2 gap-8">
        <section>
          <h2 className="font-semibold mb-3">Clubs</h2>
          <ClubsPanel />
        </section>
        <section>
          <h2 className="font-semibold mb-3">Shared clips</h2>
          <SharedClipsPanel currentUserId={user?.id ?? ""} />
        </section>
      </div>

      <section>
        <h2 className="font-semibold mb-3">Privacy controls</h2>
        <PrivacyControls />
      </section>
    </div>
  );
}
