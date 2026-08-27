import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Video } from "../types";
import { VideoUpload } from "../components/VideoUpload";
import { MatchLibrary } from "../components/MatchLibrary";
import { PlayerSelectionPanel } from "../components/PlayerSelectionPanel";
import { VideoOverlayPlayer } from "../components/VideoOverlayPlayer";
import { ComparisonStudio } from "../components/ComparisonStudio";
import { CompareDrawer } from "../components/CompareDrawer";
import { MatchSummary } from "../components/match/MatchSummary";
import { useMatchData } from "../components/match/matchData";
import { useVideoProgress } from "../hooks/useVideoProgress";
import {
  MovementTab, OverviewTab, ShotsTab, TacticsTab, TechniqueTab,
} from "../components/match/MatchTabs";
import {
  Button, EmptyState, Page, PageHeader, SegmentedControl, StatusLabel,
  Surface, formatDate,
} from "../ui";

type TabKey = "overview" | "movement" | "technique" | "tactics" | "shots";

const TABS: { value: TabKey; label: string }[] = [
  { value: "overview", label: "Overview" },
  { value: "movement", label: "Movement" },
  { value: "technique", label: "Technique" },
  { value: "tactics", label: "Tactics" },
  { value: "shots", label: "Shots" },
];

/** Processing stages, in the order the backend runs them. Internal stage
 *  names are mapped to language a player understands. */
const STAGE_LABELS: Record<string, string> = {
  // Media ingestion, before any CV work.
  queued: "Waiting for a worker",
  fetching_video: "Fetching your recording",
  checking_video: "Checking the recording",
  validating: "Checking the recording",
  optimizing_video: "Optimizing video",
  storing_prepared_video: "Optimizing video",
  fetching_prepared_video: "Loading prepared video",
  normalizing: "Optimizing video",
  analyzing: "Analyzing",
  // CV pipeline.
  reading_video_metadata: "Reading video",
  assessing_video_quality: "Checking recording quality",
  extracting_frames: "Extracting frames",
  detecting_court: "Detecting the court",
  tracking_players: "Tracking players",
  estimating_pose: "Analysing body movement",
  detecting_shuttle: "Following the shuttle",
  segmenting_rallies: "Finding rallies",
  recognizing_shots: "Recognising shots",
  analyzing_rally_phases: "Mapping rally phases",
  estimating_biomechanics: "Measuring technique",
  analyzing_tactics: "Analysing tactics",
  done: "Finalising",
};

export function Dashboard() {
  const [searchParams] = useSearchParams();
  const [videos, setVideos] = useState<Video[]>([]);
  const [selected, setSelected] = useState<Video | null>(null);
  const [seekTime, setSeekTime] = useState<number | null>(null);
  const [studio, setStudio] = useState<{ name: string; startAt: number | null } | null>(null);
  const [showUpload, setShowUpload] = useState(searchParams.get("upload") === "1");
  const [tab, setTab] = useState<TabKey>("overview");

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

  useEffect(() => {
    refreshVideos();
  }, [refreshVideos]);

  // Coach-chat evidence links land here as /dashboard?video=…&t=…
  useEffect(() => {
    if (deepLinkTime && selected && selected.id === deepLinkVideo) {
      setSeekTime(parseFloat(deepLinkTime));
    }
  }, [deepLinkTime, deepLinkVideo, selected]);

  // Realtime when Supabase is configured, with polling underneath it always:
  // a dropped websocket must cost staleness, never a video stuck on screen.
  useVideoProgress(videos, refreshVideos);

  return (
    <Page>
      <PageHeader
        title="Matches"
        description="Your analyzed sessions and performance history."
        action={
          <Button variant="primary" id="upload-toggle-btn" onClick={() => setShowUpload((v) => !v)}>
            {showUpload ? "Close" : "Upload match"}
          </Button>
        }
      />

      {showUpload && (
        <Surface className="mb-5">
          <VideoUpload
            onUploaded={(v) => {
              setShowUpload(false);
              refreshVideos();
              setSelected(v);
              setTab("overview");
            }}
          />
        </Surface>
      )}

      <div className="grid lg:grid-cols-[300px_minmax(0,1fr)] gap-6 items-start">
        <Surface as="aside" className="lg:sticky lg:top-[72px]">
          <MatchLibrary
            videos={videos}
            selectedId={selected?.id ?? null}
            onSelect={(v) => {
              setSelected(v);
              setTab("overview");
            }}
            onUpload={() => setShowUpload(true)}
          />
        </Surface>

        <div className="min-w-0">
          {!selected ? (
            <Surface>
              <EmptyState
                title="Select a match"
                description="Choose a session from your library to see its analysis."
              />
            </Surface>
          ) : (
            <MatchAnalysis
              video={selected}
              videos={videos}
              tab={tab}
              onTabChange={setTab}
              seekTime={seekTime}
              onSeek={setSeekTime}
              onOpenStudio={(name, startAt) => setStudio({ name, startAt })}
              onPlayerSelected={refreshVideos}
            />
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
    </Page>
  );
}

function MatchAnalysis({
  video,
  videos,
  tab,
  onTabChange,
  seekTime,
  onSeek,
  onOpenStudio,
  onPlayerSelected,
}: {
  video: Video;
  videos: Video[];
  tab: TabKey;
  onTabChange: (t: TabKey) => void;
  seekTime: number | null;
  onSeek: (t: number) => void;
  onOpenStudio: (name: string, t: number) => void;
  onPlayerSelected: () => void;
}) {
  const { cards, analytics, loading } = useMatchData(video);
  const title = video.opponent_name ? `vs ${video.opponent_name}` : video.original_filename;
  const group = video.status_group ?? (video.status === "analyzed" ? "ready" : "process");
  const analyzed = video.status === "analyzed";
  const dateLabel = formatDate(video.recorded_at ?? null);

  return (
    <div className="space-y-5">
      <header>
        <h2 className="text-[22px] font-semibold truncate" style={{ color: "var(--text-primary)" }}>
          {title}
        </h2>
        <div className="mt-1.5 flex items-center gap-3 flex-wrap text-[13px]" style={{ color: "var(--text-tertiary)" }}>
          <StatusLabel status={video.status} />
          {dateLabel !== "—" && <span>{dateLabel}</span>}
          {video.match_format !== "unknown" && <span className="capitalize">{video.match_format}</span>}
          {video.result_summary && <span style={{ color: "var(--text-secondary)" }}>{video.result_summary}</span>}
        </div>
      </header>

      {group === "error" && (
        <FailurePanel video={video} onRetried={onPlayerSelected} />
      )}

      {(group === "upload" || group === "process") && (
        <ProcessingPanel video={video} />
      )}

      {video.status === "needs_player_selection" && (
        <Surface>
          <PlayerSelectionPanel video={video} onDone={onPlayerSelected} />
        </Surface>
      )}

      {(analyzed || video.status === "needs_player_selection") && (
        <>
          <div className="grid xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-5 items-start">
            <VideoOverlayPlayer video={video} seekTo={seekTime} />
            <MatchSummary video={video} cards={cards} analytics={analytics} loading={loading} />
          </div>

          {analyzed && (
            <>
              <div className="overflow-x-auto -mx-1 px-1">
                <SegmentedControl
                  ariaLabel="Match analysis sections"
                  value={tab}
                  onChange={onTabChange}
                  options={TABS}
                />
              </div>

              <div role="tabpanel" aria-label={TABS.find((t) => t.value === tab)?.label}>
                {tab === "overview" && (
                  <OverviewTab video={video} analytics={analytics} onSeek={onSeek} onOpenStudio={onOpenStudio} />
                )}
                {tab === "movement" && <MovementTab video={video} cards={cards} analytics={analytics} />}
                {tab === "technique" && <TechniqueTab cards={cards} onOpenStudio={onOpenStudio} />}
                {tab === "tactics" && <TacticsTab analytics={analytics} />}
                {tab === "shots" && <ShotsTab video={video} analytics={analytics} onSeek={onSeek} />}
              </div>

              <Surface>
                <CompareDrawer current={video} videos={videos} />
              </Surface>
            </>
          )}
        </>
      )}
    </div>
  );
}

/** Premium processing state: plain-language stage, percentage, and the
 *  technical detail tucked behind a disclosure.
 *
 *  Uploading and processing are separated deliberately. Leaving "Uploading"
 *  on screen while the server transcodes tells the user something false, and
 *  it also implies they must stay on the page when they need not. */
function ProcessingPanel({ video }: { video: Video }) {
  const uploading = video.status_group === "upload";
  const stageLabel = uploading
    ? (video.status_label ?? "Uploading")
    : video.stage
      ? STAGE_LABELS[video.stage] ?? "Analyzing"
      : "Starting analysis";

  return (
    <Surface>
      <div className="flex items-baseline justify-between gap-4 mb-3">
        <div>
          <p className="text-[15px] font-medium" style={{ color: "var(--text-primary)" }}>
            {uploading ? "Uploading match" : "Analyzing match"}
          </p>
          <p className="text-[13px] mt-0.5" style={{ color: "var(--text-secondary)" }}>
            {stageLabel}
          </p>
        </div>
        <span className="tnum text-[24px] font-semibold" style={{ color: "var(--accent)" }}>
          {video.progress_pct}%
        </span>
      </div>

      <div
        className="h-1.5 rounded-[var(--radius-full)] overflow-hidden"
        style={{ background: "var(--surface-sunken)" }}
        role="progressbar"
        aria-valuenow={video.progress_pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Analysis progress"
      >
        <div
          className="h-full transition-[width] duration-700"
          style={{ width: `${video.progress_pct}%`, background: "var(--accent)" }}
        />
      </div>

      <details className="mt-3">
        <summary className="text-[12px] cursor-pointer" style={{ color: "var(--text-tertiary)" }}>
          Analysis details
        </summary>
        <p className="mt-1.5 text-[12px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
          Each upload is validated, normalized into an analysis proxy, then run through
          quality checks, court detection, player tracking, pose estimation, shuttle
          detection, rally segmentation, shot recognition and tactical analysis in
          sequence. Current stage: <code>{video.stage ?? video.status}</code>.
        </p>
        <p className="mt-1.5 text-[12px]" style={{ color: "var(--text-tertiary)" }}>
          You can close this page. Processing runs on our servers and continues without you.
        </p>
      </details>
    </Surface>
  );
}


/** Failure state that says what broke, and only offers Retry when retrying
 *  could actually help. A retry button on a corrupt file wastes the user's
 *  time and our compute proving the same thing three times. */
function FailurePanel({ video, onRetried }: { video: Video; onRetried: () => void }) {
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const retryable = video.processing_error_retryable !== false;

  async function retry() {
    setRetrying(true);
    setRetryError(null);
    try {
      await api.post(`/videos/${video.id}/reprocess`);
      onRetried();
    } catch (err) {
      setRetryError(err instanceof Error ? err.message : "Could not start a new analysis.");
    } finally {
      setRetrying(false);
    }
  }

  return (
    <Surface>
      <p className="text-[15px] font-medium" style={{ color: "var(--negative)" }}>
        {video.status === "cancelled" ? "Upload cancelled" : "We couldn't analyze this match"}
      </p>
      {video.processing_error && (
        <p className="text-[13px] mt-1" style={{ color: "var(--text-secondary)" }}>
          {video.processing_error}
        </p>
      )}
      {video.failed_stage && (
        <p className="text-[12px] mt-1" style={{ color: "var(--text-tertiary)" }}>
          Failed during: {STAGE_LABELS[video.failed_stage] ?? video.failed_stage}
        </p>
      )}
      {retryError && (
        <p className="text-[13px] mt-2" style={{ color: "var(--negative)" }}>{retryError}</p>
      )}
      {retryable && (
        <div className="mt-3">
          <Button variant="primary" onClick={retry} disabled={retrying}>
            {retrying ? "Starting..." : "Try again"}
          </Button>
        </div>
      )}
    </Surface>
  );
}
