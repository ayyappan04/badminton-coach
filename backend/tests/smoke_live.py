"""End-to-end smoke test against a REAL running uvicorn server.

Unlike the pytest suite (which uses Starlette's in-process TestClient), this
exercises the actual HTTP stack: middleware, headers, streaming, and the
background analysis worker. Run it against a local dev server only.

    uvicorn app.main:app --port 8131        # terminal 1
    python -m tests.smoke_live              # terminal 2
"""
import sys
import time
import uuid
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8131/api/v1"
PASSWORD = "CorrectHorse9!battery"

passed, failed = [], []


def check(name, condition, detail=""):
    (passed if condition else failed).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}{(' — ' + str(detail)) if detail else ''}")
    return condition


def make_clip(path: Path, seconds=6):
    import cv2
    import numpy as np
    import math
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (1280, 720))
    for i in range(30 * seconds):
        t = i / 30
        img = np.full((720, 1280, 3), (45, 105, 45), dtype=np.uint8)
        cv2.rectangle(img, (150, 90), (1130, 630), (255, 255, 255), 3)
        cv2.line(img, (150, 360), (1130, 360), (255, 255, 255), 3)
        x1 = int(500 + 180 * math.sin(t * 2.2))
        x2 = int(760 + 150 * math.sin(t * 1.7))
        cv2.rectangle(img, (x1 - 30, 460), (x1 + 30, 580), (40, 40, 190), -1)
        cv2.circle(img, (x1, 435), 17, (225, 195, 170), -1)
        cv2.rectangle(img, (x2 - 26, 200), (x2 + 26, 300), (190, 60, 40), -1)
        cv2.circle(img, (x2, 180), 15, (225, 195, 170), -1)
        vw.write(img)
    vw.release()
    return path


def main():
    c = httpx.Client(timeout=60.0)

    print("\n[1] health + security headers")
    r = c.get(f"{BASE}/health")
    check("health 200", r.status_code == 200)
    check("X-Content-Type-Options", r.headers.get("x-content-type-options") == "nosniff")
    check("X-Frame-Options", r.headers.get("x-frame-options") == "DENY")
    check("Referrer-Policy", "referrer-policy" in r.headers)
    check("CSP present", "content-security-policy" in r.headers)

    print("\n[2] signup (weak password rejected, strong accepted)")
    email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
    weak = c.post(f"{BASE}/auth/register", json={"email": email, "password": "123", "display_name": "S"})
    check("weak password rejected", weak.status_code == 400, weak.status_code)
    reg = c.post(f"{BASE}/auth/register", json={"email": email, "password": PASSWORD, "display_name": "Smoke"})
    check("signup 200", reg.status_code == 200, reg.text[:120])
    token = reg.json().get("token")

    print("\n[3] login")
    bad = c.post(f"{BASE}/auth/login", json={"email": email, "password": "WrongPass1!x"})
    check("wrong password -> 401", bad.status_code == 401)
    ghost = c.post(f"{BASE}/auth/login", json={"email": "ghost@example.com", "password": "WrongPass1!x"})
    check("no account enumeration", bad.json().get("detail") == ghost.json().get("detail"))
    good = c.post(f"{BASE}/auth/login", json={"email": email, "password": PASSWORD})
    check("login 200", good.status_code == 200)
    token = good.json()["token"]
    H = {"Authorization": f"Bearer {token}"}

    print("\n[4] protected routes")
    check("anon /videos -> 401", c.get(f"{BASE}/videos").status_code == 401)
    check("auth /videos -> 200", c.get(f"{BASE}/videos", headers=H).status_code == 200)

    print("\n[5] upload validation")
    bad_type = c.post(f"{BASE}/videos", files={"file": ("x.txt", b"hello", "text/plain")}, headers=H)
    check("non-video rejected", bad_type.status_code == 400, bad_type.status_code)
    fake = c.post(f"{BASE}/videos", files={"file": ("fake.mp4", b"<html>hi</html>" + b"A" * 300, "video/mp4")}, headers=H)
    check("renamed HTML rejected", fake.status_code == 400, fake.status_code)
    empty = c.post(f"{BASE}/videos", files={"file": ("e.mp4", b"", "video/mp4")}, headers=H)
    check("empty file rejected", empty.status_code == 400, empty.status_code)

    print("\n[6] real upload + analysis")
    clip = make_clip(Path("/tmp/smoke-clip.mp4"))
    with clip.open("rb") as fh:
        up = c.post(f"{BASE}/videos", files={"file": ("smoke match.mp4", fh, "video/mp4")},
                    data={"match_format": "singles"}, headers=H)
    if not check("upload 200", up.status_code == 200, up.text[:200]):
        return summarize()
    vid = up.json()["id"]

    proc = c.post(f"{BASE}/videos/{vid}/process", headers=H)
    check("process accepted", proc.status_code == 200, proc.text[:120])

    final, waited = None, 0
    while waited < 180:
        st = c.get(f"{BASE}/videos/{vid}/status", headers=H).json()
        if st["status"] in ("analyzed", "failed", "needs_player_selection"):
            final = st
            break
        time.sleep(2)
        waited += 2
    check("analysis reached a terminal state", final is not None, f"waited {waited}s")
    if final:
        print(f"        -> status={final['status']} stage={final.get('stage')} err={final.get('processing_error')}")
        check("analysis did not crash", final["status"] != "failed", final.get("processing_error"))

    print("\n[7] results endpoints")
    for ep in ("quality-report", "rallies", "phases", "insights"):
        rr = c.get(f"{BASE}/videos/{vid}/{ep}", headers=H)
        check(f"{ep} reachable", rr.status_code in (200, 404), rr.status_code)
    q = c.get(f"{BASE}/videos/{vid}/quality-report", headers=H)
    if q.status_code == 200:
        print(f"        -> quality score {q.json().get('score')}")

    print("\n[8] stream access control")
    check("stream without token blocked", c.get(f"{BASE}/videos/{vid}/stream").status_code in (401, 422))
    s_ok = c.get(f"{BASE}/videos/{vid}/stream", params={"token": token})
    check("owner can stream", s_ok.status_code == 200, s_ok.status_code)
    check("no Content-Disposition filename echo",
          "filename" not in s_ok.headers.get("content-disposition", ""))

    print("\n[9] cross-user isolation")
    other = f"smoke-b-{uuid.uuid4().hex[:8]}@example.com"
    c.post(f"{BASE}/auth/register", json={"email": other, "password": PASSWORD, "display_name": "Other"})
    ot = c.post(f"{BASE}/auth/login", json={"email": other, "password": PASSWORD}).json()["token"]
    OH = {"Authorization": f"Bearer {ot}"}
    check("other user cannot GET video", c.get(f"{BASE}/videos/{vid}", headers=OH).status_code == 404)
    check("other user cannot stream", c.get(f"{BASE}/videos/{vid}/stream", params={"token": ot}).status_code == 404)
    check("other user cannot delete", c.delete(f"{BASE}/videos/{vid}", headers=OH).status_code == 404)
    check("video absent from other's list",
          vid not in [v["id"] for v in c.get(f"{BASE}/videos", headers=OH).json()])

    print("\n[10] password reset (console mail backend)")
    rr = c.post(f"{BASE}/auth/request-password-reset", json={"email": email})
    rg = c.post(f"{BASE}/auth/request-password-reset", json={"email": "ghost@example.com"})
    check("reset ack 200", rr.status_code == 200)
    check("reset response is generic", rr.json() == rg.json())

    print("\n[11] logout revokes the session")
    lo = c.post(f"{BASE}/auth/logout", headers=H)
    check("logout 200", lo.status_code == 200, lo.status_code)
    check("token rejected after logout", c.get(f"{BASE}/auth/me", headers=H).status_code == 401)

    print("\n[12] rate limiting")
    codes = [c.post(f"{BASE}/auth/login",
                    json={"email": email, "password": f"Bad{i}!aaaa"}).status_code for i in range(12)]
    check("login rate limited", 429 in codes, f"codes={sorted(set(codes))}")

    return summarize()


def summarize():
    print(f"\n{'='*60}\nSMOKE: {len(passed)} passed, {len(failed)} failed")
    for f in failed:
        print(f"  FAILED: {f}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
