# Wireframe-Level Page Layouts

## Page 1 — Welcome & AI Coach

```
┌──────────────────────────────────────────────────────────┐
│  [Logo]                                    [Profile ▾]   │
├──────────────────────────────────────────────────────────┤
│                                                            │
│      ( animated coach avatar, subtle idle motion )        │
│                                                            │
│      "Welcome back, Arun."                                │
│      "You uploaded 4 matches so far. Your biggest         │
│       opportunity right now is recovery speed after        │
│       straight net drops — want to work on that today?"   │
│                                                            │
│      [ Upload a Match ]  [ Review Latest Session ]         │
│      [ Start a Training Plan ]                             │
│                                                            │
│      "Insights are based on video analysis and may vary    │
│       with camera angle and quality."  (trust footnote)    │
└──────────────────────────────────────────────────────────┘
```
First-time state (no uploads yet): coach explains the 3-step flow (upload → review → train) instead of showing a "current focus."

## Page 2 — Player Dashboard

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Match Library (left rail)   │   Main panel                               │
│ ─────────────────────────   │  ┌───────────────────────────────────────┐ │
│  ▸ 2026-07-01 vs. J. Lin     │  │        Video + canvas overlay         │ │
│    Singles · Win 21-18       │  │   (skeleton / court / shuttle /       │ │
│  ▸ 2026-06-24 vs. Doubles A  │  │    trails toggle chips, top-right)    │ │
│    Doubles · Loss            │  └───────────────────────────────────────┘ │
│  [+ Upload new match]        │  ───────────── Rally / shot timeline ───── │
│                              │  |▏▎▍▍▏ ▎▎▏▍▎▏  (click to seek + tag)      │
├──────────────────────────────┴────────────────────────────────────────────┤
│  Coaching Insights (timestamp-linked)         │  Scorecards                │
│  ─────────────────────────────────           │  Technique  ███████░ 74    │
│  0:42 Your split step starts late...  [72%]  │  Footwork   █████░░░ 58    │
│       [Open Correct Form]                    │  Positioning ██████░░ 66   │
│  1:15 Contact point behind head on...  [61%] │  Stability  ███████░ 71    │
│       [Open Correct Form]                    │                             │
├───────────────────────────────────────────────┴────────────────────────────┤
│  Court heatmap + movement trails   │  Play-style radar chart                │
│  (per player, per rally or match)  │  attack/control/endurance/defense/     │
│                                     │  mobility/net/power/consistency/      │
│                                     │  tactical awareness                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  Suggested drills & training plan  (cards: name, target, duration)          │
└─────────────────────────────────────────────────────────────────────────────┘
```

Advanced users can click "View raw data" on any card to expand joint angles, per-frame confidence, and calibration details — hidden by default to avoid overwhelming recreational players.

## Page 3 — Community & Training

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Friends & Training Partners          │  Activity                        │
│  [Search / Add friend]                │  "Priya shared a clip: her new   │
│  ▸ Priya K. (training partner)        │   cross-court smash — nice!"     │
│  ▸ Coach Dan                          │  "Club Riverside: practice        │
│  ▸ 3 pending requests                 │   session Sat 7am — 4 joined"     │
├────────────────────────────────────────┴───────────────────────────────────┤
│  Practice & Match Planning                                                 │
│  [+ Plan practice]  [+ Plan match]  [+ Challenge a friend]                 │
│  Upcoming: Sat 7am — Riverside Club — Footwork ladder + net drills         │
├─────────────────────────────────────────────────────────────────────────────┤
│  Clubs / Team Spaces          │  Privacy controls (per item)               │
│  ▸ Riverside Badminton Club   │  Profile visibility: [Friends ▾]           │
│    12 members                 │  Match results:      [Friends ▾]           │
│                                │  Full analysis:      [Private ▾]          │
│                                │  This clip:          [Public ▾]           │
└─────────────────────────────────────────────────────────────────────────────┘
```
