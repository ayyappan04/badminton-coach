import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { TrackedPerson, Video } from "../types";

interface HeatmapData {
  grid_rows: number;
  grid_cols: number;
  occupancy: number[][];
  confidence: number;
  sample_count: number;
}

export function HeatmapPanel({ video }: { video: Video }) {
  const [heatmap, setHeatmap] = useState<HeatmapData | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    setUnavailable(false);
    Promise.all([
      api.get<TrackedPerson[]>(`/videos/${video.id}/tracked-persons`),
      api.get<Record<string, { heatmap?: HeatmapData }>>(`/videos/${video.id}/heatmap`),
    ])
      .then(([persons, tactics]) => {
        const self = persons.find((p) => p.role === "self");
        const data = self ? tactics[String(self.track_id)]?.heatmap : undefined;
        if (data) setHeatmap(data);
        else setUnavailable(true);
      })
      .catch(() => setUnavailable(true));
  }, [video.id]);

  if (unavailable || !heatmap) {
    return (
      <p className="text-sm text-[var(--text-secondary)]">
        Court heatmap isn't available yet — this needs a confirmed court calibration and an
        identified player.
      </p>
    );
  }

  const max = Math.max(...heatmap.occupancy.flat(), 0.0001);

  return (
    <div>
      <div
        className="grid gap-0.5 mx-auto"
        style={{
          gridTemplateColumns: `repeat(${heatmap.grid_cols}, 1fr)`,
          maxWidth: 220,
          aspectRatio: `${heatmap.grid_cols} / ${heatmap.grid_rows}`,
        }}
      >
        {heatmap.occupancy.flat().map((v, i) => (
          <div
            key={i}
            className="rounded-[2px]"
            style={{ backgroundColor: `rgba(61, 139, 253, ${Math.min(1, (v / max) * 0.9 + 0.06)})` }}
          />
        ))}
      </div>
      <p className="text-xs text-[var(--text-secondary)] mt-2 text-center">
        Based on {heatmap.sample_count} tracked positions · {Math.round(heatmap.confidence * 100)}%
        confidence (depends on court calibration accuracy)
      </p>
    </div>
  );
}
