import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { CoachAvatar } from "../components/CoachAvatar";
import { AuthForms } from "../components/AuthForms";
import { CoachChat } from "../components/CoachChat";
import { api } from "../api/client";
import type { PlayerProfile, Video } from "../types";

export function Welcome() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [profile, setProfile] = useState<PlayerProfile | null>(null);
  const [videos, setVideos] = useState<Video[]>([]);

  useEffect(() => {
    if (!user) return;
    api.get<PlayerProfile>("/profile").then(setProfile).catch(() => {});
    api.get<Video[]>("/videos").then(setVideos).catch(() => {});
  }, [user]);

  if (!user) {
    return (
      <div className="max-w-6xl mx-auto px-4 py-16">
        <div className="text-center mb-10">
          <CoachAvatar />
          <h1 className="text-3xl font-semibold mt-4">Your AI badminton coach</h1>
          <p className="text-[var(--color-ink-soft)] mt-2 max-w-lg mx-auto">
            Upload match footage and get technique, footwork, and tactical coaching that builds
            into a personalized player profile over time.
          </p>
        </div>
        <AuthForms />
        <p className="text-center text-xs text-[var(--color-ink-soft)] mt-8 max-w-md mx-auto">
          Coaching insights are generated from video analysis and are approximate — accuracy
          depends on camera angle, video quality, frame rate, and calibration. Every insight shows
          a confidence level.
        </p>
      </div>
    );
  }

  const focusArea = profile?.training_plan?.priority_areas?.[0];
  const hasVideos = videos.length > 0;

  return (
    <div className="max-w-3xl mx-auto px-4 py-16 text-center">
      <CoachAvatar />
      <h1 className="text-2xl font-semibold mt-4">Welcome back, {user.display_name}.</h1>

      {!hasVideos ? (
        <div className="mt-4 text-[var(--color-ink-soft)] max-w-lg mx-auto space-y-2">
          <p>Here's how this works: upload a match, and I'll analyze your court positioning,</p>
          <p>footwork, technique, and shot patterns — then turn it into coaching insights,</p>
          <p>drills, and a training plan tailored to you.</p>
        </div>
      ) : focusArea ? (
        <p className="mt-4 text-[var(--color-ink-soft)] max-w-lg mx-auto">
          You've analyzed {profile?.matches_analyzed_count} match
          {profile?.matches_analyzed_count === 1 ? "" : "es"} so far. Your biggest opportunity
          right now is <span className="font-medium text-[var(--color-ink)]">{focusArea}</span> —
          want to work on that today?
        </p>
      ) : (
        <p className="mt-4 text-[var(--color-ink-soft)]">
          Your last match is still building your profile. Upload another to sharpen your insights.
        </p>
      )}

      <div className="mt-8 flex flex-wrap gap-3 justify-center">
        <button
          onClick={() => navigate("/dashboard?upload=1")}
          className="bg-[var(--color-accent)] text-white px-5 py-2.5 rounded-md font-medium hover:bg-[var(--color-accent-dark)]"
        >
          Upload a Match
        </button>
        {hasVideos && (
          <button
            onClick={() => navigate("/dashboard")}
            className="bg-[var(--color-card)] border border-[var(--color-border-strong)] px-5 py-2.5 rounded-md font-medium hover:bg-[var(--color-card-hover)]"
          >
            Review Your Latest Session
          </button>
        )}
        {profile && profile.matches_analyzed_count > 0 && (
          <button
            onClick={() => navigate("/profile")}
            className="bg-[var(--color-card)] border border-[var(--color-border-strong)] px-5 py-2.5 rounded-md font-medium hover:bg-[var(--color-card-hover)]"
          >
            View Profile &amp; Training Plan
          </button>
        )}
      </div>

      {hasVideos && (
        <div className="mt-10">
          <h2 className="text-sm font-semibold text-[var(--color-ink-soft)] uppercase tracking-wide mb-4">
            Ask your coach
          </h2>
          <CoachChat />
        </div>
      )}

      <p className="text-xs text-[var(--color-ink-soft)] mt-10 max-w-md mx-auto">
        Coaching insights are based on video analysis and may vary with camera angle, lighting,
        and video quality. Every insight includes a confidence level and known limitations.
        The coach answers from your own match data and complements — never replaces — in-person
        coaching or medical advice.
      </p>
    </div>
  );
}
