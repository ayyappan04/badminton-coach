import { useEffect, useState } from "react";
import { api } from "../api/client";
import { FriendsPanel } from "../components/FriendsPanel";
import { PracticePlanner } from "../components/PracticePlanner";
import { PrivacyControls } from "../components/PrivacyControls";
import { ClubsPanel } from "../components/ClubsPanel";
import { SharedClipsPanel } from "../components/SharedClipsPanel";
import { ReviewsPanel } from "../components/ReviewsPanel";
import { ChallengesPanel } from "../components/ChallengesPanel";
import { MilestonesStrip } from "../components/MilestonesStrip";
import { ApiKeysPanel } from "../components/ApiKeysPanel";
import { useAuth } from "../context/AuthContext";
import { Page, PageHeader, SectionHeader, SegmentedControl, Surface } from "../ui";

type Section = "people" | "coaching" | "sharing" | "privacy";

const SECTIONS: { value: Section; label: string }[] = [
  { value: "people", label: "People" },
  { value: "coaching", label: "Coaching" },
  { value: "sharing", label: "Clips & clubs" },
  { value: "privacy", label: "Privacy" },
];

export function Community() {
  const { user } = useAuth();
  const [streak, setStreak] = useState<number | null>(null);
  const [section, setSection] = useState<Section>("people");

  useEffect(() => {
    api
      .get<{ streak_weeks: number }>("/community/streak")
      .then((r) => setStreak(r.streak_weeks))
      .catch(() => {});
  }, []);

  return (
    <Page>
      <PageHeader
        title="Community"
        description="Train with others, invite a coach, and control exactly what you share."
        meta={
          streak !== null && streak > 0 ? (
            <span className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
              <span className="tnum font-semibold" style={{ color: "var(--viz-series-2)" }}>
                {streak}-week
              </span>{" "}
              training streak
            </span>
          ) : undefined
        }
      />

      <div className="mb-5">
        <MilestonesStrip />
      </div>

      <div className="mb-5 overflow-x-auto -mx-1 px-1">
        <SegmentedControl
          ariaLabel="Community sections"
          value={section}
          onChange={setSection}
          options={SECTIONS}
        />
      </div>

      <div role="tabpanel" aria-label={SECTIONS.find((s) => s.value === section)?.label}>
        {section === "people" && (
          <div className="grid md:grid-cols-2 gap-5 items-start">
            <Surface>
              <SectionHeader title="Friends & training partners" />
              <FriendsPanel />
            </Surface>
            <Surface>
              <SectionHeader title="Practice & match planning" />
              <PracticePlanner />
            </Surface>
            <Surface className="md:col-span-2">
              <SectionHeader title="Friendly challenges" />
              <ChallengesPanel />
            </Surface>
          </div>
        )}

        {section === "coaching" && (
          <Surface>
            <SectionHeader
              title="Coaching reviews"
              description="Matches you've shared with a coach, and matches shared with you."
            />
            <ReviewsPanel />
          </Surface>
        )}

        {section === "sharing" && (
          <div className="grid md:grid-cols-2 gap-5 items-start">
            <Surface>
              <SectionHeader title="Clubs" />
              <ClubsPanel />
            </Surface>
            <Surface>
              <SectionHeader title="Shared clips" />
              <SharedClipsPanel currentUserId={user?.id ?? ""} />
            </Surface>
          </div>
        )}

        {section === "privacy" && (
          <div className="grid md:grid-cols-2 gap-5 items-start">
            <Surface>
              <SectionHeader
                title="Privacy controls"
                description="Nothing is shared unless you turn it on here."
              />
              <PrivacyControls />
            </Surface>
            <Surface>
              <SectionHeader
                title="Integration API keys"
                description="Read-only access for club or league tools."
              />
              <ApiKeysPanel />
            </Surface>
          </div>
        )}
      </div>
    </Page>
  );
}
