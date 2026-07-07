import { useCallback, useEffect, useRef, useState } from "react";
import { api, getToken } from "../api/client";
import type { OverlayManifest, TechniqueReferenceV2, Video } from "../types";

/** Comparison Studio (Phase 3): the user's own clip side-by-side with a
 * smoothly animated correct-form reference — racket-path arc, contact-point
 * marker, and a footwork-path inset — plus slow motion, frame stepping, a
 * phase scrubber, per-phase checkpoints, and level/handedness/context
 * configuration. The user's clip gets a racket-hand (wrist-estimate) path
 * overlay drawn from their own pose data; true racket tracking remains a
 * needs-model-training item (docs/V2_DESIGN.md §18). */
export function ComparisonStudio({
  name,
  video,
  startAt,
  onClose,
}: {
  name: string;
  video: Video | null;
  startAt: number | null;
  onClose: () => void;
}) {
  const [ref, setRef] = useState<TechniqueReferenceV2 | null>(null);
  const [level, setLevel] = useState("intermediate");
  const [handedness, setHandedness] = useState("right");
  const [context, setContext] = useState("");
  const [progress, setProgress] = useState(0); // continuous 0..1 across all phases
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(0.5);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    setRef(null);
    const params = new URLSearchParams({ level, handedness });
    if (context) params.set("context", context);
    api
      .get<TechniqueReferenceV2>(`/technique-references/${name}?${params.toString()}`)
      .then(setRef)
      .catch(() => setRef(null));
  }, [name, level, handedness, context]);

  // Smoothly tween through the movement (~4s per full cycle) instead of
  // stepping one static pose per phase.
  useEffect(() => {
    if (!playing || !ref || ref.phases.length < 2) return;
    const t = setInterval(() => setProgress((p) => (p + 0.01) % 1), 40);
    return () => clearInterval(t);
  }, [playing, ref]);

  useEffect(() => {
    const v = videoRef.current;
    if (v && startAt !== null) {
      const onReady = () => {
        v.currentTime = Math.max(0, startAt - 1.5);
        v.playbackRate = speed;
      };
      if (v.readyState >= 1) onReady();
      else v.addEventListener("loadedmetadata", onReady, { once: true });
    }
  }, [startAt, video?.id]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = speed;
  }, [speed]);

  const stepFrame = useCallback((dir: number) => {
    const v = videoRef.current;
    if (v) {
      v.pause();
      v.currentTime = Math.max(0, v.currentTime + dir / 30);
    }
  }, []);

  const src = video ? `/api/v1/videos/${video.id}/stream?token=${encodeURIComponent(getToken() || "")}` : null;
  const totalPhases = ref?.phases.length ?? 0;
  const phaseIndex = totalPhases > 1 ? Math.min(totalPhases - 1, Math.floor(progress * totalPhases)) : 0;
  const phase = ref?.phases[phaseIndex];
  const checkpoint = ref?.checkpoints?.[phaseIndex] ?? null;
  const contactIndex = ref ? ref.phases.findIndex((p) => /contact/i.test(p.phase)) : -1;

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-[var(--color-card)] border border-[var(--color-border-strong)] rounded-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto p-6 shadow-2xl shadow-black/40"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-start mb-3">
          <div>
            <h2 className="text-lg font-semibold capitalize">{name.replace(/_/g, " ")} — Comparison Studio</h2>
            {ref && <p className="text-sm text-[var(--color-ink-soft)] mt-1">{ref.summary}</p>}
          </div>
          <button onClick={onClose} className="text-[var(--color-ink-soft)] hover:text-[var(--color-ink)] text-xl leading-none">×</button>
        </div>

        {/* Configuration */}
        <div className="flex gap-2 flex-wrap mb-4 text-xs">
          <select value={level} onChange={(e) => setLevel(e.target.value)} className="border border-[var(--color-border)] rounded-md px-2 py-1.5">
            <option value="beginner">Beginner</option>
            <option value="intermediate">Intermediate</option>
            <option value="advanced">Advanced</option>
          </select>
          <select value={handedness} onChange={(e) => setHandedness(e.target.value)} className="border border-[var(--color-border)] rounded-md px-2 py-1.5">
            <option value="right">Right-handed</option>
            <option value="left">Left-handed</option>
          </select>
          <select value={context} onChange={(e) => setContext(e.target.value)} className="border border-[var(--color-border)] rounded-md px-2 py-1.5">
            <option value="">Context: general</option>
            <option value="attacking">Attacking</option>
            <option value="defensive">Defensive</option>
            <option value="front_court">Front court</option>
            <option value="rear_court">Rear court</option>
          </select>
        </div>

        {!ref ? (
          <p className="text-sm text-[var(--color-ink-soft)]">No technique reference is available for this movement yet.</p>
        ) : (
          <>
            {/* Side-by-side: user clip | reference */}
            <div className="grid md:grid-cols-2 gap-4 mb-4">
              <div className="border border-[var(--color-border)] rounded-lg overflow-hidden bg-black/40">
                <p className="text-[10px] uppercase tracking-wide text-[var(--color-ink-soft)] px-3 pt-2">Your clip</p>
                {src && video ? (
                  <>
                    <div className="relative mt-1">
                      <video ref={videoRef} src={src} controls className="w-full max-h-56 block" />
                      <WristPathOverlay videoId={video.id} startAt={startAt} />
                    </div>
                    <div className="flex items-center gap-2 p-2 text-xs">
                      <button onClick={() => stepFrame(-1)} className="border border-[var(--color-border)] rounded px-2 py-1 hover:bg-white/5">⟨ frame</button>
                      <button onClick={() => stepFrame(1)} className="border border-[var(--color-border)] rounded px-2 py-1 hover:bg-white/5">frame ⟩</button>
                      {[0.25, 0.5, 1].map((s) => (
                        <button
                          key={s}
                          onClick={() => setSpeed(s)}
                          className={`rounded px-2 py-1 border ${speed === s ? "bg-[var(--color-accent)] text-white border-[var(--color-accent)]" : "border-[var(--color-border)] hover:bg-white/5"}`}
                        >
                          {s}×
                        </button>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="text-xs text-[var(--color-ink-soft)] p-3">Open from a coaching insight to load your clip alongside the reference.</p>
                )}
              </div>

              <div className="border border-[var(--color-border)] rounded-lg bg-[var(--color-bg-raised)] flex flex-col">
                <div className="flex items-center justify-between px-3 pt-2">
                  <p className="text-[10px] uppercase tracking-wide text-[var(--color-ink-soft)]">Reference movement</p>
                  <button onClick={() => setPlaying((p) => !p)} className="text-xs text-[var(--color-accent)]">
                    {playing ? "Pause" : "Play"}
                  </button>
                </div>
                <div className="flex-1 flex items-center justify-center" style={{ transform: handedness === "left" ? "scaleX(-1)" : undefined }}>
                  <ReferenceFigure progress={progress} contactAt={contactIndex >= 0 && totalPhases > 1 ? (contactIndex + 0.5) / totalPhases : null} />
                </div>
                <FootworkPath progress={progress} mirrored={handedness === "left"} />
                <div className="px-3 pb-3">
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={Math.round(progress * 100)}
                    onChange={(e) => {
                      setPlaying(false);
                      setProgress(Number(e.target.value) / 100);
                    }}
                    className="w-full accent-[var(--color-accent)]"
                  />
                </div>
              </div>
            </div>

            {/* Phase chips */}
            <div className="flex gap-1 mb-3 flex-wrap">
              {ref.phases.map((p, i) => (
                <button
                  key={p.phase}
                  onClick={() => { setPlaying(false); setProgress(totalPhases > 1 ? (i + 0.5) / totalPhases : 0); }}
                  className={`text-xs px-2.5 py-1 rounded-full border ${i === phaseIndex ? "bg-[var(--color-accent)] text-white border-[var(--color-accent)]" : "border-[var(--color-border)]"}`}
                >
                  {i + 1}. {p.phase}
                </button>
              ))}
            </div>

            {phase && (
              <div className="bg-white/5 border border-[var(--color-border)] rounded-lg p-4 mb-4">
                <h3 className="font-medium text-sm mb-1">{phase.phase}</h3>
                <p className="text-sm text-[var(--color-ink-soft)]">{phase.description}</p>
                {checkpoint && (
                  <p className="text-xs mt-2 text-[var(--color-court)]">✓ Checkpoint: {checkpoint}</p>
                )}
              </div>
            )}

            {(ref.level_note || ref.context_note) && (
              <div className="border border-[var(--color-accent)]/40 bg-[var(--color-accent-soft)] rounded-lg p-3 mb-4 space-y-1">
                {ref.level_note && <p className="text-xs"><span className="font-medium capitalize">{level}:</span> {ref.level_note}</p>}
                {ref.context_note && <p className="text-xs"><span className="font-medium capitalize">{context.replace(/_/g, " ")}:</span> {ref.context_note}</p>}
              </div>
            )}

            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <h4 className="text-xs font-semibold uppercase text-[var(--color-ink-soft)] mb-2">Common mistakes</h4>
                <ul className="text-sm space-y-1 list-disc list-inside text-[var(--color-ink-soft)]">
                  {ref.common_beginner_mistakes.map((m, i) => <li key={i}>{m}</li>)}
                </ul>
              </div>
              <div>
                <h4 className="text-xs font-semibold uppercase text-[var(--color-ink-soft)] mb-2">Advanced variations</h4>
                <ul className="text-sm space-y-1 list-disc list-inside text-[var(--color-ink-soft)]">
                  {ref.advanced_variations.map((m, i) => <li key={i}>{m}</li>)}
                </ul>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** The user's racket-hand path around the insight moment, drawn from their own
 * pose data (dominant-wrist estimate — the racket itself is not tracked). */
function WristPathOverlay({ videoId, startAt }: { videoId: string; startAt: number | null }) {
  const [points, setPoints] = useState<{ x: number; y: number }[]>([]);

  useEffect(() => {
    if (startAt === null) return;
    let cancelled = false;
    api
      .get<OverlayManifest>(`/videos/${videoId}/overlay-manifest`)
      .then((manifest) => {
        if (cancelled) return;
        // find the "self" track from box roles
        let selfTrackId: number | null = null;
        for (const boxes of Object.values(manifest.boxes_by_frame)) {
          const self = boxes.find((b) => b.role === "self");
          if (self) { selfTrackId = self.track_id; break; }
        }
        if (selfTrackId === null) return;
        const sampleFps = 10; // analysis frame rate (FRAME_SAMPLE_FPS)
        const centerFrame = Math.round(startAt * sampleFps);
        const trail: { x: number; y: number }[] = [];
        for (let f = centerFrame - 8; f <= centerFrame + 8; f++) {
          const poses = manifest.poses_by_frame[f];
          const pose = poses?.find((p) => p.track_id === selfTrackId);
          const wrist = pose?.landmarks.find((l) => l.name === "right_wrist") || pose?.landmarks.find((l) => l.name === "left_wrist");
          if (wrist && (wrist.visibility ?? 0) > 0.4) trail.push({ x: wrist.x, y: wrist.y });
        }
        if (trail.length >= 4) setPoints(trail);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [videoId, startAt]);

  if (points.length < 4) return null;
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${(p.x * 100).toFixed(1)},${(p.y * 100).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  return (
    <>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 w-full h-full pointer-events-none">
        <path d={path} fill="none" stroke="var(--color-warn)" strokeWidth="0.7" strokeDasharray="2 1.2" opacity="0.9" />
        <circle cx={last.x * 100} cy={last.y * 100} r="1.4" fill="var(--color-warn)" />
      </svg>
      <span className="absolute bottom-1 right-2 text-[9px] text-[var(--color-warn)] bg-black/50 rounded px-1.5 py-0.5 pointer-events-none">
        racket-hand path (wrist estimate)
      </span>
    </>
  );
}

// Smoothly animated reference figure with a racket-path arc and a
// contact-point marker. A stand-in for full 3D skeletal animation, which
// stays a needs-model/asset item.
function ReferenceFigure({ progress, contactAt }: { progress: number; contactAt: number | null }) {
  const armAngle = -20 + progress * 150;
  const kneeBend = 10 + Math.sin(progress * Math.PI) * 22;
  const lean = Math.sin(progress * Math.PI) * 6;
  const nearContact = contactAt !== null && Math.abs(progress - contactAt) < 0.09;

  // racket-head position for the current arm angle (matches the rotate() below)
  const rad = (armAngle * Math.PI) / 180;
  const rhx = 80 + 38 * Math.cos(rad) - (-39) * Math.sin(rad);
  const rhy = 65 + 38 * Math.sin(rad) + (-39) * Math.cos(rad);

  // faint arc showing the racket head's full path through the swing
  const arc = Array.from({ length: 25 }, (_, i) => {
    const a = ((-20 + (i / 24) * 150) * Math.PI) / 180;
    const x = 80 + 38 * Math.cos(a) - (-39) * Math.sin(a);
    const y = 65 + 38 * Math.sin(a) + (-39) * Math.cos(a);
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  return (
    <svg viewBox="0 0 190 180" width="180" height="170">
      <line x1="30" y1="172" x2="160" y2="172" stroke="var(--color-border-strong)" strokeWidth="2" />
      <path d={arc} fill="none" stroke="var(--color-accent)" strokeWidth="1" strokeDasharray="3 3" opacity="0.35" />
      {nearContact && (
        <g>
          <circle cx={rhx} cy={rhy} r="9" fill="none" stroke="var(--color-warn)" strokeWidth="1.5" opacity="0.9" />
          <circle cx={rhx} cy={rhy} r="2.5" fill="var(--color-warn)" />
          <text x={rhx + 12} y={rhy - 6} fontSize="8" fill="var(--color-warn)">contact</text>
        </g>
      )}
      <g transform={`rotate(${lean} 80 115)`}>
        <line x1="80" y1="60" x2="80" y2="115" stroke="#c7d4e8" strokeWidth="6" strokeLinecap="round" />
        <circle cx="80" cy="45" r="14" fill="#e7b790" />
        <g transform={`rotate(${armAngle} 80 65)`}>
          <line x1="80" y1="65" x2="118" y2="65" stroke="#e7b790" strokeWidth="7" strokeLinecap="round" />
          <line x1="118" y1="65" x2="118" y2="35" stroke="var(--color-accent)" strokeWidth="3" />
          <ellipse cx="118" cy="26" rx="9" ry="13" fill="none" stroke="var(--color-accent)" strokeWidth="3" />
        </g>
        <line x1="80" y1="65" x2="52" y2="80" stroke="#e7b790" strokeWidth="7" strokeLinecap="round" />
      </g>
      <line x1="80" y1="115" x2={80 - kneeBend} y2="145" stroke="#c7d4e8" strokeWidth="7" strokeLinecap="round" />
      <line x1={80 - kneeBend} y1="145" x2="65" y2="172" stroke="#c7d4e8" strokeWidth="7" strokeLinecap="round" />
      <line x1="80" y1="115" x2={80 + kneeBend} y2="145" stroke="#c7d4e8" strokeWidth="7" strokeLinecap="round" />
      <line x1={80 + kneeBend} y1="145" x2="95" y2="172" stroke="#c7d4e8" strokeWidth="7" strokeLinecap="round" />
    </svg>
  );
}

// Footwork-path inset: a small top-down court patch showing the movement
// in → plant → push-back path with a dot tracking the animation progress.
function FootworkPath({ progress, mirrored }: { progress: number; mirrored: boolean }) {
  // out-and-back path: base (center) -> target corner -> base
  const t = progress < 0.5 ? progress * 2 : (1 - progress) * 2;
  const px = 30 + t * 55;
  const py = 46 - t * 22;

  return (
    <div className="px-3 pb-1" style={{ transform: mirrored ? "scaleX(-1)" : undefined }}>
      <svg viewBox="0 0 120 56" className="w-full h-14">
        <rect x="4" y="4" width="112" height="48" rx="3" fill="none" stroke="var(--color-border)" strokeWidth="1.5" />
        <line x1="4" y1="28" x2="116" y2="28" stroke="var(--color-border)" strokeWidth="1" opacity="0.6" />
        <path d="M30,46 Q55,44 85,24" fill="none" stroke="var(--color-court)" strokeWidth="1.5" strokeDasharray="3 2" opacity="0.7" />
        <path d="M85,24 Q58,36 30,46" fill="none" stroke="var(--color-ink-soft)" strokeWidth="1" strokeDasharray="2 2" opacity="0.45" />
        <circle cx="30" cy="46" r="2.5" fill="var(--color-ink-soft)" />
        <circle cx="85" cy="24" r="2.5" fill="var(--color-court)" />
        <circle cx={px} cy={py} r="3.2" fill="var(--color-accent)" />
        <text x="8" y="14" fontSize="6" fill="var(--color-ink-soft)">footwork path: move in → plant → push back</text>
      </svg>
    </div>
  );
}
