# Example Coaching Outputs

These illustrate the target tone and structure produced by `services/coaching/insight_generator.py`. Every insight includes: observed action, likely impact, prioritized correction, a drill, and a confidence + limitations line.

---

**Insight — Footwork (0:42, Rally 3)**
- **Observed:** Your split step begins roughly 180ms after your opponent contacts the shuttle, based on wrist-swing timing vs. your own foot-lift timing.
- **Impact:** This delays your first step by close to a fifth of a second — against a fast smash or drive that's often the difference between a controlled return and a rushed one.
- **Correction:** Aim to complete your split step landing at or just before opponent contact, not after.
- **Drill:** Shadow split-step timing drill — partner feeds random shots on a call, you split-step on the call, not on shuttle flight.
- **Confidence:** Moderate (61%). Based on estimated contact timing from a single camera angle; true contact frame can be off by 1-2 frames at this video's frame rate.

---

**Insight — Technique (1:15, Rally 5)**
- **Observed:** On your overhead clears, contact point is estimated behind your head rather than above/in front of it.
- **Impact:** This typically shortens reach and reduces the depth you can generate, and can make the shot easier for opponents to read early.
- **Correction:** Focus on contacting the shuttle slightly in front of your head, reaching up rather than back.
- **Drill:** Shadow-swing clears in front of a mirror or phone camera, checking contact point before hitting live shuttles.
- **Confidence:** Moderate (58%) — single-camera contact-point estimation is approximate without depth information; treat as a directional signal, not an exact measurement.

---

**Insight — Positioning (2:03, Rally 7)**
- **Observed:** After a straight net drop, you recovered toward center court within about 0.4s, before your opponent's return direction was visible.
- **Impact:** This left the cross-court net reply mostly uncovered in this rally.
- **Correction:** Hold your recovery position slightly longer at the net before committing to center, especially after your own tight net shots.
- **Drill:** Net-shot-then-hold recovery drill — play a net shot, hold your position one beat, then recover on the coach/partner's shot direction.
- **Confidence:** High (78%) — based on clear court-position tracking; less dependent on pose/contact precision than technique insights.

---

**Insight — Doubles formation (0:58, Rally 2)**
- **Observed:** During your team's attacking sequence, you and your partner were both positioned side-by-side rather than shifting to a front-back attacking shape.
- **Impact:** Side-by-side formation is generally better suited to defense; during your own attack it can leave the net underexposed.
- **Correction:** When your team is attacking (smash/drop initiated), shift to front-back with your partner covering the rear court.
- **Drill:** Rotation drill — practice the front-back ↔ side-by-side transition cued by attack/defense state with a partner.
- **Confidence:** Moderate (65%) — partner tracking in doubles is more prone to occlusion than singles; treat formation calls as approximate for congested frames.
