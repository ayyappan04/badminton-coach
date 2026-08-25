# BWF footage — manual observational test protocol

## Why this document exists instead of automated BWF tests

BWF match footage on YouTube is rights-reserved. Downloading it to feed into
the analysis pipeline would breach both YouTube's terms and the copyright in
the broadcast, so **the automated test suite does not and will not do that.**

There are two lawful ways to cover this material, and this repo uses both:

1. **Openly-licensed real footage** — CC0 / public-domain / CC BY / CC BY-SA
   clips from Wikimedia Commons, downloaded and run through the real pipeline.
   Results: `docs/evidence/real-footage-matrix.json`, attribution in
   `docs/evidence/real-footage-attribution.md`. This includes elite tour-level
   broadcast footage (China Open 2025), which is the closest available
   equivalent to BWF broadcast conditions.
2. **This protocol** — a structured *observational* procedure. You watch BWF
   footage through BWF's own player, and separately analyse footage **you have
   the right to use**, then score the app's output against what you observed.
   Nothing is downloaded and nothing leaves the official player.

If your organisation holds a BWF licence or a written permission covering
analysis use, the automated path opens up: drop the licensed files into
`/tmp/bc-real/`, add entries to `backend/tests/footage_manifest.py`, and run
`python -m tests.run_real_footage_matrix`. The harness is source-agnostic.

---

## A. Observational pass (no download)

**Purpose:** calibrate expectations. Establish what "correct" looks like for
each scenario so the app's output can be judged against something real.

**Source:** BWF's official channels — `youtube.com/@bwftv` and
`bwfbadminton.com`. Watch in the official player. Do not download, screen-
record, or re-host.

For each scenario below, find a representative passage, note the video title
and timestamp, and record what a competent human analyst would say. Fill the
**Observed (human)** column by watching; leave **App output** blank until
section B.

| # | Scenario | What to look for | Observed (human) | App output | Match? |
|---|---|---|---|---|---|
| 1 | High serve (singles) | Contact below waist, deep landing | | | |
| 2 | Low serve (doubles) | Tape-height crossing, peak before net | | | |
| 3 | Flick serve | Same preparation as low serve, late acceleration | | | |
| 4 | Serve return | Receiver racket up before contact | | | |
| 5 | Forehand clear | Contact above/in front of head, full pronation | | | |
| 6 | Backhand clear | Elbow leads, thumb-braced, contact ahead of shoulder | | | |
| 7 | Smash | Highest controllable contact, steep angle | | | |
| 8 | Jump smash | Take-off, contact, two-foot landing, recovery | | | |
| 9 | Drop shot | Same preparation as clear, decelerated contact | | | |
| 10 | Net shot | Tight tape crossing, controlled push | | | |
| 11 | Net kill | Downward tap from above tape | | | |
| 12 | Defensive lift | Under-contact, depth to rear court | | | |
| 13 | Drive exchange | Flat, fast, racket stays up between shots | | | |
| 14 | Singles rally | Base recovery after each shot | | | |
| 15 | Doubles rally | Front-back on attack, side-by-side on defence | | | |
| 16 | Doubles rotation | Timing of the switch after an attacking shot | | | |
| 17 | Broadcast angle | Elevated behind-baseline; court fully visible? | | | |
| 18 | Replay / slow-mo cut | Scene change mid-rally | | | |
| 19 | Camera cut to crowd | Tracking should reset, not carry identities over | | | |
| 20 | Player occlusion | Players crossing at the net | | | |

**Known-answer calibration.** Scenarios 17–20 are the ones the current
pipeline is measured weakest on (see §C). Use them to sanity-check that the
app *says so* rather than producing confident nonsense.

---

## B. Comparison pass (footage you may use)

**Purpose:** score the app against ground truth you established in A.

Use footage you own or are licensed to use: your own match recordings, club
footage with participant consent, or the openly-licensed clips already in the
harness. Record one clip per scenario where practical.

For each clip:

1. Upload via the dashboard (or `POST /api/v1/videos`).
2. Trigger analysis, wait for `analyzed`.
3. Record the app's output for the same moments you annotated in A.
4. Score each dimension 0–5 using the rubric below.
5. Note explicitly whether the app **communicated uncertainty** where it was
   in fact uncertain — this matters as much as raw accuracy.

### Scoring rubric

| Score | Meaning |
|---|---|
| 0 | Fails completely |
| 1 | Mostly unusable |
| 2 | Works only in easy cases |
| 3 | Usable with noticeable issues |
| 4 | Good with minor issues |
| 5 | Excellent |

Score: upload handling · video processing · pose/keypoint detection · player
tracking · stroke recognition · footwork feedback · coaching feedback · safety
of coaching advice · latency · UI clarity · uncertainty communication.

### Honesty checks (pass/fail, not scored)

- [ ] Every numeric claim carries a confidence value.
- [ ] Limitation tags appear when a stage degrades.
- [ ] Court detection falls back rather than inventing geometry when the court
      is not clearly visible.
- [ ] Shuttle output is labelled experimental.
- [ ] Rally *outcomes* (winner / forced / unforced error) are **not** claimed —
      the pipeline cannot determine these and must not imply otherwise.
- [ ] No medical or injury diagnosis is offered anywhere.

---

## C. What to expect, based on measured results

From `docs/evidence/real-footage-matrix.json` (real footage) and
`docs/evidence/video-matrix.json` (synthetic conditions):

| Stage | Expectation | Basis |
|---|---|---|
| Upload + processing | Reliable | 14/14 synthetic + real clips completed |
| Video-quality gate | Discriminates well | low-light 52, blur 60, good 84 |
| Court detection | Good on clear full-court views; **falls back honestly** otherwise | 0.15 confidence + `needs_user_calibration` on unclear footage |
| Player tracking | **Weak** — degrades badly on occlusion and partial court | 0 tracks under crossing players |
| Pose estimation | See real-footage matrix | Requires real bodies; synthetic clips gave 0 |
| Stroke recognition | **Unvalidated / weak** | Rule-based heuristic, not a trained classifier |
| Shuttle tracking | **Experimental, false-positive prone** | 170 "shuttle points" emitted on non-badminton footage |
| Coaching safety | Strong | Refuses diagnosis, refers to physio |

Broadcast footage is the *hardest* case for this pipeline: cuts, zooms,
replays, on-screen graphics, and a camera position that compresses court depth.
Expect the quality gate to flag cuts, and expect tracking to be the weak link.

---

## D. Recording results

Add completed runs to `docs/evidence/` as
`bwf-manual-<yyyy-mm-dd>.md`, including: video title, timestamp range,
scenario, human observation, app output, score, and notes. Do **not** paste
frames, thumbnails, or transcript text from rights-reserved footage into the
repository — reference it by title and timestamp only.
