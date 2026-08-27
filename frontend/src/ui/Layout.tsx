import type { ButtonHTMLAttributes, ReactNode } from "react";

/* ==========================================================================
   Structural primitives. One analytical concept = one Surface.
   ========================================================================== */

export function Page({
  children,
  width = "wide",
  className = "",
}: {
  children: ReactNode;
  width?: "wide" | "narrow";
  className?: string;
}) {
  return (
    <div
      className={`mx-auto px-4 sm:px-6 pb-20 pt-6 sm:pt-8 ${className}`}
      style={{ maxWidth: width === "narrow" ? "var(--content-width-narrow)" : "var(--content-width)" }}
    >
      {children}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  action,
  back,
  meta,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  back?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <header className="mb-6">
      {back}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h1 className="text-[28px] sm:text-[32px] leading-tight" style={{ color: "var(--text-primary)" }}>
            {title}
          </h1>
          {description && (
            <p className="mt-1.5 text-[14px] max-w-2xl" style={{ color: "var(--text-secondary)" }}>
              {description}
            </p>
          )}
          {meta && <div className="mt-2 flex items-center gap-3 flex-wrap">{meta}</div>}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
    </header>
  );
}

/** The single panel primitive. Replaces the ad-hoc border+bg+rounded pattern. */
export function Surface({
  children,
  raised = false,
  padded = true,
  className = "",
  as: Tag = "section",
  ...rest
}: {
  children: ReactNode;
  raised?: boolean;
  padded?: boolean;
  className?: string;
  as?: "section" | "div" | "article" | "aside";
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag
      className={`rounded-[var(--radius-lg)] border ${padded ? "p-4 sm:p-5" : ""} ${className}`}
      style={{
        background: raised ? "var(--surface-raised)" : "var(--surface)",
        borderColor: "var(--separator)",
      }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

export function SectionHeader({
  title,
  description,
  action,
  className = "",
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex items-start justify-between gap-3 mb-3 ${className}`}>
      <div className="min-w-0">
        <h2 className="text-[16px] font-semibold" style={{ color: "var(--text-primary)" }}>
          {title}
        </h2>
        {description && (
          <p className="text-[13px] mt-0.5" style={{ color: "var(--text-tertiary)" }}>
            {description}
          </p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/** Sub-grouping inside a Surface, without nesting another card. */
export function InsetGroup({ title, children, className = "" }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      {title && (
        <div className="text-[11px] font-medium uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
          {title}
        </div>
      )}
      {children}
    </div>
  );
}

/* --- Buttons -------------------------------------------------------------- */

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "text-white",
  secondary: "",
  ghost: "",
  danger: "",
};

export function Button({
  children,
  variant = "secondary",
  size = "md",
  fullWidth = false,
  className = "",
  ...rest
}: {
  children: ReactNode;
  variant?: Variant;
  size?: Size;
  fullWidth?: boolean;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const sizing =
    size === "sm" ? "h-9 px-3 text-[13px] gap-1.5" : "h-11 px-4 text-[14px] gap-2";

  const styles: React.CSSProperties =
    variant === "primary"
      ? { background: "var(--accent)", borderColor: "transparent" }
      : variant === "secondary"
        ? { background: "var(--surface-raised)", borderColor: "var(--separator-strong)", color: "var(--text-primary)" }
        : variant === "danger"
          ? { background: "transparent", borderColor: "var(--negative)", color: "var(--negative)" }
          : { background: "transparent", borderColor: "transparent", color: "var(--accent)" };

  return (
    <button
      className={`inline-flex items-center justify-center rounded-[var(--radius-md)] border font-medium
        transition-colors disabled:opacity-45 disabled:cursor-not-allowed
        ${sizing} ${fullWidth ? "w-full" : ""} ${VARIANTS[variant]} ${className}
        ${variant === "primary" ? "hover:brightness-110" : ""}
        ${variant === "secondary" ? "hover:bg-[var(--surface-hover)]" : ""}
        ${variant === "ghost" ? "hover:bg-[var(--accent-soft)]" : ""}
        ${variant === "danger" ? "hover:bg-[var(--negative-soft)]" : ""}`}
      style={styles}
      {...rest}
    >
      {children}
    </button>
  );
}

export function IconButton({
  children,
  label,
  className = "",
  ...rest
}: { children: ReactNode; label: string } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      aria-label={label}
      title={label}
      className={`inline-flex items-center justify-center w-9 h-9 rounded-[var(--radius-md)]
        transition-colors hover:bg-[var(--surface-hover)] ${className}`}
      style={{ color: "var(--text-secondary)" }}
      {...rest}
    >
      {children}
    </button>
  );
}

/* --- Status --------------------------------------------------------------- */

export type StatusKind =
  | "created" | "uploading" | "uploaded" | "validating" | "queued" | "normalizing"
  | "processing" | "needs_player_selection" | "analyzed" | "failed" | "cancelled" | "deleted";

// Uploading and processing read differently on purpose: they are different
// things happening in different places, and only one of them requires the user
// to keep the tab open.
const STATUS: Record<StatusKind, { label: string; color: string; dot: string }> = {
  created: { label: "Preparing", color: "var(--text-tertiary)", dot: "var(--text-tertiary)" },
  uploading: { label: "Uploading", color: "var(--accent)", dot: "var(--accent)" },
  uploaded: { label: "Queued", color: "var(--text-tertiary)", dot: "var(--text-tertiary)" },
  validating: { label: "Checking", color: "var(--accent)", dot: "var(--accent)" },
  queued: { label: "Queued", color: "var(--text-tertiary)", dot: "var(--text-tertiary)" },
  normalizing: { label: "Optimizing", color: "var(--accent)", dot: "var(--accent)" },
  processing: { label: "Analyzing", color: "var(--accent)", dot: "var(--accent)" },
  needs_player_selection: { label: "Needs your input", color: "var(--warning)", dot: "var(--warning)" },
  analyzed: { label: "Analyzed", color: "var(--text-secondary)", dot: "var(--positive)" },
  failed: { label: "Failed", color: "var(--negative)", dot: "var(--negative)" },
  cancelled: { label: "Cancelled", color: "var(--text-tertiary)", dot: "var(--text-tertiary)" },
  deleted: { label: "Deleted", color: "var(--text-tertiary)", dot: "var(--text-tertiary)" },
};

/** Compact dot+label. Deliberately not a big coloured box. */
export function StatusLabel({ status, className = "" }: { status: string; className?: string }) {
  const s = STATUS[status as StatusKind] ?? { label: status, color: "var(--text-tertiary)", dot: "var(--text-tertiary)" };
  return (
    <span className={`inline-flex items-center gap-1.5 text-[12px] whitespace-nowrap ${className}`} style={{ color: s.color }}>
      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: s.dot }} aria-hidden="true" />
      {s.label}
    </span>
  );
}

/* --- Segmented control ---------------------------------------------------- */

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  size = "md",
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
  size?: Size;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="inline-flex gap-1 p-1 rounded-[var(--radius-md)] overflow-x-auto max-w-full"
      style={{ background: "var(--surface-sunken)", border: "1px solid var(--separator)" }}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.value)}
            className={`whitespace-nowrap rounded-[var(--radius-sm)] font-medium transition-colors
              ${size === "sm" ? "px-2.5 h-7 text-[12px]" : "px-3 h-8 text-[13px]"}`}
            style={
              active
                ? { background: "var(--surface-raised)", color: "var(--text-primary)", boxShadow: "var(--shadow-sm)" }
                : { color: "var(--text-secondary)", background: "transparent" }
            }
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/* --- Empty / loading / error ---------------------------------------------- */

export function EmptyState({
  title,
  description,
  action,
  compact = false,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`text-center ${compact ? "py-6" : "py-12"}`}>
      <p className="text-[15px] font-medium" style={{ color: "var(--text-primary)" }}>
        {title}
      </p>
      {description && (
        <p className="mt-1.5 text-[13px] max-w-sm mx-auto" style={{ color: "var(--text-tertiary)" }}>
          {description}
        </p>
      )}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function Skeleton({ className = "", height = 16 }: { className?: string; height?: number }) {
  return (
    <div
      className={`relative overflow-hidden rounded-[var(--radius-sm)] ${className}`}
      style={{ height, background: "var(--surface-raised)" }}
      aria-hidden="true"
    >
      <div
        className="absolute inset-0 -translate-x-full"
        style={{
          background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.04), transparent)",
          animation: "shimmer 1.6s infinite",
        }}
      />
    </div>
  );
}

export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2.5">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={i === rows - 1 ? "w-2/3" : "w-full"} />
      ))}
    </div>
  );
}

/** User-facing error. Raw technical detail stays behind a disclosure. */
export function ErrorState({ title, detail }: { title: string; detail?: string | null }) {
  return (
    <div
      className="rounded-[var(--radius-lg)] border p-4"
      style={{ borderColor: "color-mix(in srgb, var(--negative) 35%, transparent)", background: "var(--negative-soft)" }}
    >
      <p className="text-[14px] font-medium" style={{ color: "var(--negative)" }}>
        {title}
      </p>
      {detail && (
        <details className="mt-2">
          <summary className="text-[12px] cursor-pointer" style={{ color: "var(--text-secondary)" }}>
            View details
          </summary>
          <p className="mt-1.5 text-[12px] break-words" style={{ color: "var(--text-tertiary)" }}>
            {detail}
          </p>
        </details>
      )}
    </div>
  );
}

/* --- Data table ------------------------------------------------------------
   Tables are the right tool for dense numeric comparison. On narrow screens
   each row becomes a stacked block rather than a horizontal scroll.
   -------------------------------------------------------------------------- */

export interface Column<T> {
  key: string;
  header: string;
  align?: "left" | "right";
  render: (row: T) => ReactNode;
}

export function DataTable<T>({
  columns,
  rows,
  getRowKey,
  onRowClick,
  empty = "No data",
}: {
  columns: Column<T>[];
  rows: T[];
  getRowKey: (row: T, i: number) => string;
  onRowClick?: (row: T) => void;
  empty?: string;
}) {
  if (!rows.length) {
    return (
      <p className="text-[13px] py-3" style={{ color: "var(--text-tertiary)" }}>
        {empty}
      </p>
    );
  }

  return (
    <>
      {/* Desktop / tablet */}
      <table className="hidden sm:table w-full text-[14px]">
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`pb-2 text-[12px] font-medium ${c.align === "right" ? "text-right" : "text-left"}`}
                style={{ color: "var(--text-tertiary)" }}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={getRowKey(row, i)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={`border-t ${onRowClick ? "cursor-pointer hover:bg-[var(--surface-hover)]" : ""}`}
              style={{ borderColor: "var(--separator)" }}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`py-2.5 tnum ${c.align === "right" ? "text-right" : "text-left"}`}
                  style={{ color: c.align === "right" ? "var(--text-primary)" : "var(--text-secondary)" }}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      {/* Mobile: stacked rows, no horizontal scrolling */}
      <div className="sm:hidden divide-y" style={{ borderColor: "var(--separator)" }}>
        {rows.map((row, i) => (
          <div
            key={getRowKey(row, i)}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
            className="py-3"
          >
            <div className="text-[14px] font-medium mb-1.5" style={{ color: "var(--text-primary)" }}>
              {columns[0].render(row)}
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              {columns.slice(1).map((c) => (
                <div key={c.key} className="flex justify-between gap-2 text-[13px]">
                  <span style={{ color: "var(--text-tertiary)" }}>{c.header}</span>
                  <span className="tnum" style={{ color: "var(--text-primary)" }}>
                    {c.render(row)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
