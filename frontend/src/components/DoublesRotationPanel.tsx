import type { DoublesRotationBlock } from "../types";

/** Phase 3: doubles rotation & formation analysis. Rendered only when the
 * match analytics contain a doubles_rotation block (i.e. a partner was
 * identified). All numbers are match-level tendencies from occlusion-prone
 * doubles tracking — the basis line keeps that visible. */
export function DoublesRotationPanel({ block }: { block: DoublesRotationBlock }) {
  if (!block.available) {
    return (
      <p className="text-sm text-[var(--text-secondary)]">
        Doubles rotation analysis needs enough overlapping tracking of you and your partner — {block.basis}
      </p>
    );
  }

  const fs = block.formation_split;
  const rot = block.rotation;
  const sp = block.spacing;

  return (
    <div className="space-y-4">
      <div className="grid sm:grid-cols-3 gap-3">
        {fs && (
          <div className="border border-[var(--separator)] rounded-lg p-3 bg-[var(--surface-raised)]">
            <div className="flex justify-between items-baseline mb-2">
              <h3 className="text-sm font-medium">Formation split</h3>
              <span className="text-[10px] text-[var(--text-secondary)]">{Math.round(block.confidence * 100)}% conf.</span>
            </div>
            <div className="flex h-2.5 rounded-full overflow-hidden mb-1.5">
              <div className="bg-[var(--accent)]" style={{ width: `${fs.front_back_pct}%` }} />
              <div className="bg-[var(--viz-series-2)]" style={{ width: `${fs.side_by_side_pct}%` }} />
            </div>
            <p className="text-xs text-[var(--text-secondary)]">
              <span className="text-[var(--accent)]">■</span> Front-back {fs.front_back_pct}% ·{" "}
              <span className="text-[var(--viz-series-2)]">■</span> Side-by-side {fs.side_by_side_pct}%
            </p>
          </div>
        )}

        {rot && (
          <div className="border border-[var(--separator)] rounded-lg p-3 bg-[var(--surface-raised)]">
            <h3 className="text-sm font-medium mb-2">Rotation into attack</h3>
            <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
              {rot.attacks_started_side_by_side} attacking sequences began side-by-side.
              {rot.missed_rotations > 0 && (
                <> <span className="text-[var(--warning)]">{rot.missed_rotations}</span> never reached front-back.</>
              )}
              {rot.avg_rotation_delay_s !== null && <> Average rotation took <span className="text-[var(--text-primary)]">{rot.avg_rotation_delay_s}s</span>.</>}
            </p>
          </div>
        )}

        {sp && (
          <div className="border border-[var(--separator)] rounded-lg p-3 bg-[var(--surface-raised)]">
            <h3 className="text-sm font-medium mb-2">Partner spacing</h3>
            <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
              Overlapping the same space {sp.overlap_pct}% of tracked time; wide gaps {sp.wide_gap_pct}%.
              {sp.open_middle_in_defense_pct !== null && (
                <> Middle channel open during defense <span className={sp.open_middle_in_defense_pct > 30 ? "text-[var(--warning)]" : ""}>{sp.open_middle_in_defense_pct}%</span>.</>
              )}
            </p>
          </div>
        )}
      </div>

      {block.findings && block.findings.length > 0 && (
        <div className="space-y-2">
          {block.findings.map((f, i) => (
            <div key={i} className="border-l-2 border-[var(--accent)] pl-3 py-1">
              <p className="text-sm">{f.finding}</p>
              <p className="text-xs text-[var(--text-secondary)] mt-0.5">Try: {f.suggestion}</p>
            </div>
          ))}
        </div>
      )}

      <p className="text-[11px] text-[var(--text-secondary)]">{block.basis}</p>
    </div>
  );
}
