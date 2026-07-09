import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { PlayerProfile, Video } from "../types";
import { VideoUpload } from "../components/VideoUpload";
import { MatchLibrary } from "../components/MatchLibrary";
import { PlayerSelectionPanel } from "../components/PlayerSelectionPanel";
import { VideoOverlayPlayer } from "../components/VideoOverlayPlayer";
import { PhaseTimeline } from "../components/PhaseTimeline";
import { InsightsPanel } from "../components/InsightsPanel";
import { Scorecards } from "../components/Scorecards";
import { HeatmapPanel } from "../components/HeatmapPanel";
import { RadarChartPanel } from "../components/RadarChartPanel";
import { TrainingPlanPanel } from "../components/TrainingPlanPanel";
import { OverviewStrip } from "../components/OverviewStrip";
import { QualityReportCard } from "../components/QualityReportCard";
import { MatchAnalyticsPanel } from "../components/MatchAnalyticsPanel";
import { CoachReviewSection } from "../components/CoachReviewSection";
import { CompareDrawer } from "../components/CompareDrawer";
import { ComparisonStudio } from "../components/ComparisonStudio";

export function Dashboard() {
  const [searchParams] = useSearchParams();
  const [videos, setVideos] = useState<Video[]>([]);
  const [selected, setSelected] = useState<Video | null>(null);
  const [seekTime, setSeekTime] = useState<number | null>(null);
  const [studio, setStudio] = useState<{ name: string; startAt: number | null } | null>(null);
  const [profile, setProfile] = useState<PlayerProfile | null>(null);
  const [showUpload, setShowUpload] = useState(searchParams.get("upload") === "1");

  const deepLinkVideo = searchParams.get("video");
  const deepLinkTime = searchParams.get("t");

  const refreshVideos = useCallback(() => {
    api.get<Video[]>("/videos").then((list) => {
      setVideos(list);
      setSelected((prev) => {
        if (deepLinkVideo) {
          const target = list.find((v) => v.id === deepLinkVideo);
          if (target) return target;
        }
        if (prev) {
          const updated = list.find((v) => v.id === prev.id);
          if (updated) return updated;
        }
        return prev ?? list[0] ?? null;
      });
    });
  }, [deepLinkVideo]);

  const refreshProfile = useCallback(() => {
    api.get<PlayerProfile>("/profile").then(setProfile).catch(() => {});
  }, []);

  useEffect(() => {
    refreshVideos();
    refreshProfile();
  }, [refreshVideos, refreshProfile]);

  // Coach-chat evidence links land here as /dashboard?video=...&t=...
  useEffect(() => {
    if (deepLinkTime && selected && selected.id === deepLinkVideo) {
      setSeekTime(parseFloat(deepLinkTime));
    }
  }, [deepLinkTime, deepLinkVideo, selected]);

  useEffect(() => {
    const hasActive = videos.some((v) => v.status === "processing" || v.status === "uploaded");
    if (!hasActive) return;
    const interval = setInterval(refreshVideos, 2500);
    return () => clearInterval(interval);
  }, [videos, refreshVideos]);

  const latestAnalyzed = videos.find((v) => v.status === "analyzed") ?? null;

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-6">
      {profile && profile.matches_analyzed_count > 0 && (
        <OverviewStrip profile={profile} latestVideo={latestAnalyzed} />
      )}

      <div className="grid lg:grid-cols-[280px_1fr] gap-6">
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Match library</h2>
            <button
              id="upload-toggle-btn"
              onClick={() => setShowUpload((v) => !v)}
              className="text-xs text-[var(--color-accent)] hover:underline"
            >
              {showUpload ? "Hide" : "+ Upload"}
            </button>
          </div>
          {showUpload && (
            <VideoUpload
              onUploaded={(v) => {
                setShowUpload(false);
                refreshVideos();
                setSelected(v);
              }}
            />
          )}
          <MatchLibrary videos={videos} selectedId={selected?.id ?? null} onSelect={setSelected} />
        </div>

        <div className="space-y-6 min-w-0">
          {!selected && (
            <p className="text-sm text-[var(--color-ink-soft)]">Upload a match to get started.</p>
          )}

          {selected && selected.status === "failed" && (
            <div className="border border-[var(--color-bad)]/40 bg-[var(--color-bad-soft)] rounded-lg p-4 text-sm text-[var(--color-bad)]">
              Processing failed: {selected.processing_error}
            </div>
          )}

          {selected && selected.status === "processing" && (
            <div className="border border-[var(--color-accent)]/40 bg-[var(--color-accent-soft)] rounded-lg p-4 text-sm text-[var(--color-accent)]">
              Analyzing your match ({selected.progress_pct}% — {selected.stage?.replace(/_/g, " ")})...
              This runs quality checks, court detection, player tracking, pose estimation, shot
              recognition, and tactical analysis in stages.
            </div>
          )}

          {selected && selected.status === "needs_player_selection" && (
            <PlayerSelectionPanel video={selected} onDone={refreshVideos} />
          )}

          {selected && (selected.status === "analyzed" || selected.status === "needs_player_selection") && (
            <>
              <QualityReportCard video={selected} />
              <VideoOverlayPlayer video={selected} seekTo={seekTime} />
              <PhaseTimeline video={selected} onSeek={setSeekTime} />
            </>
          )}

          {selected && selected.status === "analyzed" && (
            <>
              <section>
                <h2 className="font-semibold mb-3">Coaching insights</h2>
                <InsightsPanel
                  video={selected}
                  onSeek={setSeekTime}
                  onOpenTechnique={(name, timestamp) => setStudio({ name, startAt: timestamp })}
                />
              </section>

              <section>
                <h2 className="font-semibold mb-3">Coach review</h2>
                <CoachReviewSection video={selected} onSeek={setSeekTime} />
              </section>

              <section>
                <h2 className="font-semibold mb-3">Match analytics &amp; tactics</h2>
                <MatchAnalyticsPanel video={selected} />
              </section>

              <section>
                <h2 className="font-semibold mb-3">Technique scorecards</h2>
                <Scorecards video={selected} />
              </section>

              <section>
                <h2 className="font-semibold mb-3">Compare matches</h2>
                <CompareDrawer current={selected} videos={videos} />
              </section>

              <div className="grid sm:grid-cols-2 gap-6">
                <section>
                  <h2 className="font-semibold mb-3">Court heatmap</h2>
                  <HeatmapPanel video={selected} />
                </section>
                <section>
                  <h2 className="font-semibold mb-3">Play-style profile</h2>
                  {profile && <RadarChartPanel radarScores={profile.radar_scores} />}
                </section>
              </div>

              <section>
                <h2 className="font-semibold mb-3">Training plan &amp; drills</h2>
                {profile && <TrainingPlanPanel profile={profile} />}
              </section>
            </>
          )}
        </div>
      </div>

      {studio && (
        <ComparisonStudio
          name={studio.name}
          video={selected}
          startAt={studio.startAt}
          onClose={() => setStudio(null)}
        />
      )}
    </div>
  );
}
