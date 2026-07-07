"""Generates a synthetic badminton-court-like video for pipeline smoke testing:
a green court with white boundary lines, a net, and two moving dark blobs
(simulated players) plus a small fast bright blob (simulated shuttle)."""
import math
import sys

import cv2
import numpy as np

W, H = 960, 540
FPS = 30
DURATION_S = 6


def make(path: str):
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    court_margin_x, court_margin_y = 100, 60

    for frame_no in range(FPS * DURATION_S):
        t = frame_no / FPS
        img = np.zeros((H, W, 3), dtype=np.uint8)
        img[:] = (40, 110, 40)  # green court surface

        # court boundary + center/net lines (white)
        cv2.rectangle(img, (court_margin_x, court_margin_y), (W - court_margin_x, H - court_margin_y), (255, 255, 255), 3)
        cv2.line(img, (court_margin_x, H // 2), (W - court_margin_x, H // 2), (255, 255, 255), 3)  # net line
        cv2.line(img, (W // 2, court_margin_y), (W // 2, H - court_margin_y), (200, 200, 200), 2)  # center line

        # two "players" moving back and forth, one on each side of the net
        p1x = int(court_margin_x + 150 + 120 * math.sin(t * 1.3))
        p1y = int(H // 2 + 90)
        p2x = int(W - court_margin_x - 150 + 100 * math.sin(t * 1.7 + 1.0))
        p2y = int(court_margin_y + 80)
        cv2.rectangle(img, (p1x - 25, p1y - 60), (p1x + 25, p1y + 60), (30, 30, 200), -1)
        cv2.rectangle(img, (p2x - 25, p2y - 60), (p2x + 25, p2y + 60), (200, 30, 30), -1)
        # simple limb marks so pose has some contrast to find (not realistic anatomy)
        cv2.circle(img, (p1x, p1y - 70), 12, (230, 200, 180), -1)
        cv2.circle(img, (p2x, p2y - 70), 12, (230, 200, 180), -1)

        # small fast "shuttle" arcing across
        sx = int(court_margin_x + (W - 2 * court_margin_x) * ((math.sin(t * 2.2) + 1) / 2))
        sy = int(H // 2 - 100 * abs(math.sin(t * 2.2 * 2)))
        cv2.circle(img, (sx, sy), 4, (255, 255, 255), -1)

        writer.write(img)

    writer.release()


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/synthetic_match.mp4"
    make(out_path)
    print("wrote", out_path)
