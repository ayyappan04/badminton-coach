import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { MatchAnalytics, TechniqueScoreEntry, Video } from "../../types";

export type Scorecards = Record<string, TechniqueScoreEntry>;

/** Scorecard dimensions grouped into the coaching areas the tabs use. These
 *  are the REAL dimensions the backend returns — nothing invented. */
export const DIMENSION_GROUPS = {
  movement: ["footwork", "recovery_speed", "movement_efficiency"],
  technique: ["racket_preparation", "contact_height", "shot_timing", "body_alignment", "execution_consistency"],
  stability: ["balance", "stability"],
} as const;

export const DIMENSION_LABELS: Record<string, string> = {
  footwork: "Footwork",
  balance: "Balance",
  stability: "Stability",
  racket_preparation: "Racket preparation",
  contact_height: "Contact height",
  shot_timing: "Shot timing",
  recovery_speed: "Recovery speed",
  movement_efficiency: "Movement efficiency",
  body_alignment: "Body alignment",
  execution_consistency: "Consistency",
};

export function meanScore(cards: Scorecards | null, keys: readonly string[]): { value: number | null; n: number } {
  if (!cards) return { value: null, n: 0 };
  const values = keys
    .map((k) => cards[k]?.score)
    .filter((s): s is number => s !== null && s !== undefined);
  if (!values.length) return { value: null, n: 0 };
  return { value: values.reduce((a, b) => a + b, 0) / values.length, n: values.length };
}

export function meanConfidence(cards: Scorecards | null): number | null {
  if (!cards) return null;
  const values = Object.values(cards)
    .map((c) => c.confidence)
    .filter((c) => typeof c === "number" && c > 0);
  if (!values.length) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

/** Shared loader so the summary and every tab read the same fetched data. */
export function useMatchData(video: Video) {
  const [cards, setCards] = useState<Scorecards | null>(null);
  const [analytics, setAnalytics] = useState<MatchAnalytics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setCards(null);
    setAnalytics(null);
    Promise.allSettled([
      api.get<Scorecards>(`/videos/${video.id}/scorecards`).then((d) => !cancelled && setCards(d)),
      api.get<MatchAnalytics>(`/videos/${video.id}/analytics`).then((d) => !cancelled && setAnalytics(d)),
    ]).finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [video.id]);

  return { cards, analytics, loading };
}
