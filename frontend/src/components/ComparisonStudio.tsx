import { useCallback, useEffect, useRef, useState } from "react";
import { api, getToken } from "../api/client";
import type { TechniqueReferenceV2, Video } from "../types";

/** V2 Comparison Studio: the user's own clip side-by-side with an animated
 * correct-form reference, with slow motion, frame stepping, a phase scrubber,
 * per-phase checkpoints, and level/handedness/context configuration.
 * The reference is a lightweight animated figure — full 3D skeletal animation
 * is a Phase-3 item (docs/V2_DESIGN.md §18). */
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
  const [phaseIndex, setPhaseIndex] = useState(0);
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

  // Reference animation loop: advance one phase per second while playing.
  useEffect(() => {
    if (!playing || !ref || ref.phases.length < 2) return;
    const t = setInterval(() => setPhaseIndex((i) => (i + 1) % ref.phases.length), 1000);
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
  const phase = ref?.phases[phaseIndex];
  const checkpoint = ref?.checkpoints?.[phaseIndex] ?? null;

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
                {src ? (
                  <>
                    <video ref={videoRef} src={src} controls className="w-full max-h-56 block mt-1" />
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
                  <ReferenceFigure phaseIndex={phaseIndex} totalPhases={ref.phases.length} />
                </div>
                <div className="px-3 pb-3">
                  <input
                    type="range"
                    min={0}
                    max={ref.phases.length - 1}
                    value={phaseIndex}
                    onChange={(e) => {
                      setPlaying(false);
                      setPhaseIndex(Number(e.target.value));
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
                  onClick={() => { setPlaying(false); setPhaseIndex(i); }}
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

// Animated reference figure — poses vary by phase progress. A stand-in for
// full 3D skeletal animation (Phase 3).
function ReferenceFigure({ phaseIndex, totalPhases }: { phaseIndex: number; totalPhases: number }) {
  const progress = totalPhases > 1 ? phaseIndex / (totalPhases - 1) : 0;
  const armAngle = -20 + progress * 150;
  const kneeBend = 10 + Math.sin(progress * Math.PI) * 22;
  const lean = Math.sin(progress * Math.PI) * 6;

  return (
    <svg viewBox="0 0 160 180" width="150" height="170">
      <line x1="30" y1="172" x2="130" y2="172" stroke="var(--color-border-strong)" strokeWidth="2" />
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
