import { useEffect, useRef, useState } from "react";
import { api, getToken } from "../api/client";
import type { Video } from "../types";

const SAMPLE_FPS = 10; // must match backend FRAME_SAMPLE_FPS (app/core/config.py)

interface OverlayManifest {
  court: { corners_px: number[][]; method: string; confidence: number };
  boxes_by_frame: Record<string, { track_id: number; role: string; x: number; y: number; w: number; h: number; confidence: number }[]>;
  poses_by_frame: Record<string, { track_id: number; landmarks: { name: string; x: number; y: number }[]; confidence: number }[]>;
  shuttle_by_frame: Record<string, { x: number; y: number; confidence: number }>;
}

const SKELETON_EDGES: [string, string][] = [
  ["left_shoulder", "right_shoulder"], ["left_shoulder", "left_hip"], ["right_shoulder", "right_hip"],
  ["left_hip", "right_hip"], ["left_shoulder", "left_elbow"], ["left_elbow", "left_wrist"],
  ["right_shoulder", "right_elbow"], ["right_elbow", "right_wrist"], ["left_hip", "left_knee"],
  ["left_knee", "left_ankle"], ["right_hip", "right_knee"], ["right_knee", "right_ankle"],
];

export function VideoOverlayPlayer({ video, seekTo }: { video: Video; seekTo: number | null }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [manifest, setManifest] = useState<OverlayManifest | null>(null);
  const [showSkeleton, setShowSkeleton] = useState(true);
  const [showCourt, setShowCourt] = useState(true);
  const [showShuttle, setShowShuttle] = useState(true);
  const [showBoxes, setShowBoxes] = useState(true);

  useEffect(() => {
    api
      .get<OverlayManifest>(`/videos/${video.id}/overlay-manifest`)
      .then(setManifest)
      .catch(() => setManifest(null));
  }, [video.id]);

  useEffect(() => {
    if (seekTo !== null && videoRef.current) {
      videoRef.current.currentTime = seekTo;
      videoRef.current.play().catch(() => {});
    }
  }, [seekTo]);

  useEffect(() => {
    let raf: number;
    function draw() {
      const canvas = canvasRef.current;
      const vid = videoRef.current;
      if (canvas && vid && vid.videoWidth) {
        canvas.width = vid.clientWidth;
        canvas.height = vid.clientHeight;
        const scaleX = vid.clientWidth / vid.videoWidth;
        const scaleY = vid.clientHeight / vid.videoHeight;
        const ctx = canvas.getContext("2d")!;
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        if (manifest) {
          if (showCourt && manifest.court.corners_px.length === 4) {
            ctx.strokeStyle = manifest.court.confidence > 0.5 ? "#22c55e" : "#f59e0b";
            ctx.lineWidth = 2;
            ctx.beginPath();
            manifest.court.corners_px.forEach(([x, y], i) => {
              const px = x * scaleX, py = y * scaleY;
              if (i === 0) ctx.moveTo(px, py);
              else ctx.lineTo(px, py);
            });
            ctx.closePath();
            ctx.stroke();
          }

          const frameIndex = Math.round(vid.currentTime * SAMPLE_FPS);
          const key = String(frameIndex);

          if (showBoxes && manifest.boxes_by_frame[key]) {
            for (const b of manifest.boxes_by_frame[key]) {
              ctx.strokeStyle = b.role === "self" ? "#2b6cb0" : "#dc2626";
              ctx.lineWidth = 2;
              ctx.strokeRect(b.x * scaleX, b.y * scaleY, b.w * scaleX, b.h * scaleY);
            }
          }

          if (showSkeleton && manifest.poses_by_frame[key]) {
            for (const pose of manifest.poses_by_frame[key]) {
              const byName: Record<string, { x: number; y: number }> = {};
              pose.landmarks.forEach((l) => (byName[l.name] = l));
              ctx.strokeStyle = "#f5f3ea";
              ctx.lineWidth = 2;
              for (const [a, b] of SKELETON_EDGES) {
                const pa = byName[a], pb = byName[b];
                if (!pa || !pb) continue;
                ctx.beginPath();
                ctx.moveTo(pa.x * vid.videoWidth * scaleX, pa.y * vid.videoHeight * scaleY);
                ctx.lineTo(pb.x * vid.videoWidth * scaleX, pb.y * vid.videoHeight * scaleY);
                ctx.stroke();
              }
            }
          }

          if (showShuttle && manifest.shuttle_by_frame[key]) {
            const s = manifest.shuttle_by_frame[key];
            ctx.fillStyle = "#facc15";
            ctx.beginPath();
            ctx.arc(s.x * scaleX, s.y * scaleY, 5, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }
      raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [manifest, showSkeleton, showCourt, showShuttle, showBoxes]);

  const src = `/api/v1/videos/${video.id}/stream?token=${encodeURIComponent(getToken() || "")}`;

  return (
    <div>
      <div className="flex gap-2 mb-2 text-xs flex-wrap">
        {[
          { label: "Skeleton", state: showSkeleton, set: setShowSkeleton },
          { label: "Court", state: showCourt, set: setShowCourt },
          { label: "Shuttle", state: showShuttle, set: setShowShuttle },
          { label: "Boxes", state: showBoxes, set: setShowBoxes },
        ].map((chip) => (
          <button
            key={chip.label}
            onClick={() => chip.set(!chip.state)}
            className={`px-2.5 py-1 rounded-full border ${
              chip.state ? "bg-[var(--accent)] text-white border-[var(--accent)]" : "border-[var(--separator)]"
            }`}
          >
            {chip.label}
          </button>
        ))}
      </div>
      <div className="relative bg-black rounded-lg overflow-hidden">
        <video ref={videoRef} src={src} controls className="w-full max-h-[480px] block" />
        <canvas ref={canvasRef} className="absolute inset-0 pointer-events-none w-full h-full" />
      </div>
      {!manifest && (
        <p className="text-xs text-[var(--text-secondary)] mt-2">
          Overlay data isn't available yet for this video (it may need re-processing after a server
          restart, or processing hasn't completed).
        </p>
      )}
    </div>
  );
}
