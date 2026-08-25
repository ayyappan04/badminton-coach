import type { ReactNode } from "react";
import { confidenceTone, deltaSentiment, type Sentiment } from "./format";

/* ==========================================================================
   Data-display primitives.
   These carry the analytical identity: aligned numbers, honest deltas,
   first-class confidence.
   ========================================================================== */

/* --- Delta ----------------------------------------------------------------
   Direction and sentiment are deliberately decoupled. A recovery time going
   DOWN is good; an error count going UP is bad. Coupling the arrow to the
   colour would lie about half the metrics in this product.
   -------------------------------------------------------------------------- */

const SENTIMENT_COLOR: Record<Sentiment, string> = {
  positive: "var(--positive)",
  negative: "var(--negative)",
  neutral: "var(--text-tertiary)",
};

export function Delta({
  value,
  unit = "",
  lowerIsBetter = false,
  sentiment,
  decimals = 0,
  suffix,
  className = "",
}: {
  value: number | null | undefined;
  unit?: string;
  /** True for metrics where a decrease is an improvement (recovery time, errors). */
  lowerIsBetter?: boolean;
  /** Override the computed sentiment when the caller knows better. */
  sentiment?: Sentiment;
  decimals?: number;
  /** e.g. "vs previous match" */
  suffix?: string;
  className?: string;
}) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;

  const tone = sentiment ?? deltaSentiment(value, lowerIsBetter);
  const arrow = value > 0 ? "↑" : value < 0 ? "↓" : "→";
  const magnitude = Math.abs(value).toFixed(decimals);

  // Screen readers get words, not arrows — direction alone must never be the
  // only signal (WCAG 1.4.1).
  const spoken =
    value === 0
      ? "no change"
      : `${value > 0 ? "up" : "down"} ${magnitude}${unit}${
          tone === "neutral" ? "" : `, ${tone === "positive" ? "an improvement" : "a regression"}`
        }`;

  return (
    <span
      className={`tnum inline-flex items-baseline gap-1 text-[13px] font-medium ${className}`}
      style={{ color: SENTIMENT_COLOR[tone] }}
    >
      <span aria-hidden="true">
        {arrow} {magnitude}
        {unit}
      </span>
      <span className="sr-only">{spoken}</span>
      {suffix && (
        <span className="font-normal" style={{ color: "var(--text-tertiary)" }}>
          {suffix}
        </span>
      )}
    </span>
  );
}

/* --- Confidence -----------------------------------------------------------
   Confidence is a first-class metric here, not a disclaimer. Below 50% the
   styling deliberately de-emphasises the value it accompanies.
   -------------------------------------------------------------------------- */

export function Confidence({
  value,
  showLabel = false,
  basis,
  className = "",
}: {
  /** 0–1 ratio. */
  value: number | null | undefined;
  showLabel?: boolean;
  /** Methodology text, surfaced on hover. */
  basis?: string;
  className?: string;
}) {
  if (value === null || value === undefined) return null;
  const pct = Math.round(value * 100);
  const tone = confidenceTone(value);
  const color =
    tone === "high"
      ? "var(--text-secondary)"
      : tone === "medium"
        ? "var(--warning)"
        : "var(--negative)";

  return (
    <span
      className={`tnum text-[12px] whitespace-nowrap ${className}`}
      style={{ color }}
      title={basis || `Analysis confidence: ${pct}%`}
    >
      {pct}%{showLabel ? " confidence" : ""}
    </span>
  );
}

/** Shown instead of a fabricated number when evidence is too thin. */
export function InsufficientEvidence({ detail }: { detail?: string }) {
  return (
    <span className="text-[13px]" style={{ color: "var(--text-tertiary)" }}>
      Not enough evidence
      {detail && <span className="block text-[12px]">{detail}</span>}
    </span>
  );
}

/* --- Metric ---------------------------------------------------------------
   One metric. Label, value, unit, optional delta and confidence. Numbers use
   tabular figures so columns line up.
   -------------------------------------------------------------------------- */

export type MetricSize = "sm" | "md" | "lg" | "hero";

const VALUE_SIZE: Record<MetricSize, string> = {
  sm: "text-[15px] font-semibold",
  md: "text-[22px] font-semibold",
  lg: "text-[30px] font-semibold",
  hero: "text-[40px] font-semibold",
};

export function Metric({
  label,
  value,
  unit,
  delta,
  confidence,
  detail,
  size = "md",
  muted = false,
  className = "",
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  delta?: ReactNode;
  confidence?: number | null;
  detail?: ReactNode;
  size?: MetricSize;
  /** Low-confidence data must not read with the same authority. */
  muted?: boolean;
  className?: string;
}) {
  return (
    <div className={`min-w-0 ${className}`} style={muted ? { opacity: 0.6 } : undefined}>
      <div className="text-[12px] leading-tight" style={{ color: "var(--text-tertiary)" }}>
        {label}
      </div>
      <div className="mt-1 flex items-baseline gap-1.5 flex-wrap">
        <span className={`tnum leading-none ${VALUE_SIZE[size]}`} style={{ color: "var(--text-primary)" }}>
          {value}
        </span>
        {unit && (
          <span className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
            {unit}
          </span>
        )}
        {delta}
      </div>
      {(detail || confidence !== undefined) && (
        <div className="mt-1 flex items-center gap-2 text-[12px]" style={{ color: "var(--text-tertiary)" }}>
          {detail}
          {confidence !== undefined && confidence !== null && <Confidence value={confidence} />}
        </div>
      )}
    </div>
  );
}

/* --- MetricRow ------------------------------------------------------------
   A label/value/delta line inside a grouped surface. This is the pattern that
   replaces "every number in its own card".
   -------------------------------------------------------------------------- */

export function MetricRow({
  label,
  value,
  unit,
  delta,
  confidence,
  muted = false,
  onClick,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  delta?: ReactNode;
  confidence?: number | null;
  muted?: boolean;
  onClick?: () => void;
}) {
  const content = (
    <>
      <span className="text-[14px] truncate" style={{ color: "var(--text-secondary)" }}>
        {label}
      </span>
      <span className="flex items-baseline gap-1.5 justify-end">
        <span className="tnum text-[15px] font-medium" style={{ color: "var(--text-primary)" }}>
          {value}
        </span>
        {unit && (
          <span className="text-[12px]" style={{ color: "var(--text-tertiary)" }}>
            {unit}
          </span>
        )}
      </span>
      <span className="text-right">{delta}</span>
      {confidence !== undefined && (
        <span className="text-right">
          <Confidence value={confidence} />
        </span>
      )}
    </>
  );

  const base = `grid items-baseline gap-3 py-2 ${
    confidence !== undefined
      ? "grid-cols-[1fr_auto_auto_auto]"
      : "grid-cols-[1fr_auto_auto]"
  }`;

  if (onClick) {
    return (
      <button
        onClick={onClick}
        className={`${base} w-full text-left rounded-[var(--radius-sm)] px-1 -mx-1 transition-colors hover:bg-[var(--surface-hover)]`}
        style={muted ? { opacity: 0.6 } : undefined}
      >
        {content}
      </button>
    );
  }
  return (
    <div className={base} style={muted ? { opacity: 0.6 } : undefined}>
      {content}
    </div>
  );
}

/** Divided stack of MetricRows. */
export function MetricGroup({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`divide-y ${className}`} style={{ borderColor: "var(--separator)" }}>
      {children}
    </div>
  );
}

/* --- Score bar ------------------------------------------------------------ */

export function ScoreBar({ value, tone = "accent" }: { value: number | null | undefined; tone?: "accent" | Sentiment }) {
  const pct = value === null || value === undefined ? 0 : Math.max(0, Math.min(100, value));
  const color =
    tone === "accent"
      ? "var(--accent)"
      : tone === "positive"
        ? "var(--positive)"
        : tone === "negative"
          ? "var(--negative)"
          : "var(--text-tertiary)";
  return (
    <div
      className="h-1.5 w-full rounded-[var(--radius-full)] overflow-hidden"
      style={{ background: "var(--surface-sunken)" }}
      role="presentation"
    >
      <div className="h-full rounded-[var(--radius-full)] transition-[width]" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

/* --- Sparkline ------------------------------------------------------------
   Deliberately tiny and dependency-free. Used sparingly.
   -------------------------------------------------------------------------- */

export function Sparkline({
  points,
  width = 72,
  height = 20,
  tone = "var(--accent)",
}: {
  points: number[];
  width?: number;
  height?: number;
  tone?: string;
}) {
  if (points.length < 2) return null;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const d = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * width;
      const y = height - ((p - min) / span) * (height - 2) - 1;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} aria-hidden="true" className="overflow-visible">
      <path d={d} fill="none" stroke={tone} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
