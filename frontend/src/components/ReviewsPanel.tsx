import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, getToken } from "../api/client";
import type { ReviewDetail, ReviewSummary } from "../types";

/** Phase 4 coaching reviews, both directions:
 * - as coach: open an assigned review → watch the student's match, read the
 *   AI insights, and add timestamped notes that confirm/adjust/override them
 * - as student: see reviews you've requested and revoke access */
export function ReviewsPanel() {
  const [asCoach, setAsCoach] = useState<ReviewSummary[]>([]);
  const [asStudent, setAsStudent] = useState<ReviewSummary[]>([]);
  const [openReview, setOpenReview] = useState<ReviewDetail | null>(null);

  function refresh() {
    api.get<{ as_coach: ReviewSummary[]; as_student: ReviewSummary[] }>("/coach-reviews")
      .then((r) => { setAsCoach(r.as_coach); setAsStudent(r.as_student); })
      .catch(() => {});
  }

  useEffect(refresh, []);

  async function open(reviewId: string) {
    try {
      setOpenReview(await api.get<ReviewDetail>(`/coach-reviews/${reviewId}`));
    } catch { /* review inactive */ }
  }

  async function revoke(reviewId: string) {
    await api.post(`/coach-reviews/${reviewId}/revoke`, {});
    refresh();
  }

  async function complete(reviewId: string) {
    await api.post(`/coach-reviews/${reviewId}/complete`, {});
    setOpenReview(null);
    refresh();
  }

  if (asCoach.length === 0 && asStudent.length === 0) {
    return (
      <p className="text-sm text-[var(--color-ink-soft)]">
        No coaching reviews yet. Invite a coach from any match on your dashboard, or ask a player to invite you.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {asCoach.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase text-[var(--color-ink-soft)] mb-2">Matches to review (you're the coach)</h3>
          <div className="space-y-2">
            {asCoach.map((r) => (
              <div key={r.review_id} className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-3 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm truncate">{r.student_name} · {r.video_filename}</p>
                  <p className="text-xs text-[var(--color-ink-soft)]">
                    {r.match_format} · {r.note_count} note{r.note_count === 1 ? "" : "s"} · {r.status}
                    {r.message ? ` · “${r.message}”` : ""}
                  </p>
                </div>
                {r.status === "active" && (
                  <button onClick={() => open(r.review_id)} className="text-xs bg-[var(--color-accent)] text-white rounded-md px-3 py-1.5 shrink-0 hover:bg-[var(--color-accent-dark)]">
                    Review
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {asStudent.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase text-[var(--color-ink-soft)] mb-2">Reviews you requested</h3>
          <div className="space-y-2">
            {asStudent.map((r) => (
              <div key={r.review_id} className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-3 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm truncate">{r.coach_name} · {r.video_filename}</p>
                  <p className="text-xs text-[var(--color-ink-soft)]">{r.note_count} note{r.note_count === 1 ? "" : "s"} · {r.status}</p>
                </div>
                {r.status === "active" && (
                  <button onClick={() => revoke(r.review_id)} className="text-xs border border-[var(--color-bad)]/50 text-[var(--color-bad)] rounded-md px-3 py-1.5 shrink-0 hover:bg-[var(--color-bad-soft)]">
                    Revoke access
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {openReview && (
        <ReviewWorkspace
          detail={openReview}
          onClose={() => setOpenReview(null)}
          onComplete={() => complete(openReview.review_id)}
          onNoteAdded={() => open(openReview.review_id)}
        />
      )}
    </div>
  );
}

function ReviewWorkspace({
  detail,
  onClose,
  onComplete,
  onNoteAdded,
}: {
  detail: ReviewDetail;
  onClose: () => void;
  onComplete: () => void;
  onNoteAdded: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [comment, setComment] = useState("");
  const [stance, setStance] = useState("");
  const [relatedInsight, setRelatedInsight] = useState("");

  const src = `/api/v1/videos/${detail.video.video_id}/stream?token=${encodeURIComponent(getToken() || "")}`;

  async function addNote(e: FormEvent) {
    e.preventDefault();
    if (!comment.trim()) return;
    await api.post(`/coach-reviews/${detail.review_id}/notes`, {
      timestamp_s: Math.round((videoRef.current?.currentTime ?? 0) * 10) / 10,
      comment,
      stance: stance || null,
      related_insight_id: relatedInsight || null,
    });
    setComment("");
    setStance("");
    setRelatedInsight("");
    onNoteAdded();
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-[var(--color-card)] border border-[var(--color-border-strong)] rounded-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto p-6 shadow-2xl shadow-black/40"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-start mb-3">
          <div>
            <h2 className="text-lg font-semibold">Reviewing {detail.student_name} — {detail.video.filename}</h2>
            <p className="text-xs text-[var(--color-ink-soft)] mt-1">
              Your notes appear on {detail.student_name}'s dashboard next to the AI insights. Access ends when you complete the review.
            </p>
          </div>
          <button onClick={onClose} className="text-[var(--color-ink-soft)] hover:text-[var(--color-ink)] text-xl leading-none">×</button>
        </div>

        <video ref={videoRef} src={src} controls className="w-full max-h-64 rounded-md bg-black/40 mb-4" />

        <div className="grid md:grid-cols-2 gap-4 mb-4">
          <div>
            <h3 className="text-xs font-semibold uppercase text-[var(--color-ink-soft)] mb-2">AI insights on this match</h3>
            <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
              {detail.ai_insights.length === 0 && <p className="text-xs text-[var(--color-ink-soft)]">No AI insights were generated.</p>}
              {detail.ai_insights.map((i) => (
                <button
                  key={i.insight_id}
                  onClick={() => {
                    if (videoRef.current) videoRef.current.currentTime = i.timestamp_s;
                    setRelatedInsight(i.insight_id);
                  }}
                  className={`w-full text-left border rounded-lg p-2.5 text-xs transition ${
                    relatedInsight === i.insight_id
                      ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
                      : "border-[var(--color-border)] bg-[var(--color-bg-raised)] hover:bg-[var(--color-card-hover)]"
                  }`}
                >
                  <span className="text-[var(--color-accent)]">{formatTime(i.timestamp_s)}</span> · {i.category} · {Math.round(i.confidence * 100)}%
                  <p className="mt-1 text-[var(--color-ink-soft)]">{i.observed_action.slice(0, 110)}…</p>
                </button>
              ))}
            </div>
          </div>

          <div>
            <h3 className="text-xs font-semibold uppercase text-[var(--color-ink-soft)] mb-2">Your notes</h3>
            <div className="space-y-2 max-h-32 overflow-y-auto pr-1 mb-3">
              {detail.notes.length === 0 && <p className="text-xs text-[var(--color-ink-soft)]">No notes yet.</p>}
              {detail.notes.map((n) => (
                <div key={n.note_id} className="border border-[var(--color-border)] rounded-lg p-2.5 text-xs bg-[var(--color-bg-raised)]">
                  <span className="text-[var(--color-accent)]">{formatTime(n.timestamp_s)}</span>
                  {n.stance && <span className="ml-2 capitalize text-[var(--color-ink-soft)]">({n.stance})</span>}
                  <p className="mt-1">{n.comment}</p>
                </div>
              ))}
            </div>

            <form onSubmit={addNote} className="space-y-2">
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Note at the current video position… (click an AI insight to link your note to it)"
                rows={3}
                className="w-full text-sm border border-[var(--color-border)] rounded-md px-3 py-2 focus:outline-none focus:border-[var(--color-accent)]"
              />
              <div className="flex gap-2 items-center">
                <select value={stance} onChange={(e) => setStance(e.target.value)} className="text-xs border border-[var(--color-border)] rounded-md px-2 py-1.5">
                  <option value="">No stance on AI</option>
                  <option value="agree">Agree with AI insight</option>
                  <option value="adjust">Adjust AI insight</option>
                  <option value="disagree">Override AI insight</option>
                </select>
                {relatedInsight && <span className="text-[10px] text-[var(--color-accent)]">linked to insight ✓</span>}
                <button type="submit" className="ml-auto text-xs bg-[var(--color-accent)] text-white rounded-md px-3 py-1.5 hover:bg-[var(--color-accent-dark)]">
                  Add note
                </button>
              </div>
            </form>
          </div>
        </div>

        <div className="flex justify-end">
          <button onClick={onComplete} className="text-xs border border-[var(--color-good)]/50 text-[var(--color-good)] rounded-md px-4 py-2 hover:bg-[var(--color-good-soft)]">
            Complete review (ends your access)
          </button>
        </div>
      </div>
    </div>
  );
}

function formatTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}
