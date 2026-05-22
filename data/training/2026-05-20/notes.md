# Session 1 — 2026-05-20

## Conditions
- Time: 21:14 - 21:54 PST
- Ambient: indoor, climate-controlled
- Servo orientation: flat on heavy base, horn swings horizontally
- Sensor offset on horn: tip mount, foam tape
- Sample rate: 208 Hz nominal, ~212 Hz effective (within LSM6DSOX
  oscillator tolerance per datasheet)

## Post-session checks
- File integrity: PASS (all last-line 4 fields, both end \n)
- Variance ratio: X = 153×, Y = 93× (both well above 50× threshold
  from session-runbook.md)
- Sweep log: 1200 transitions exact (600 TO_MAX + 600 TO_MIN)
- Saleae spot check: PASS (both .sal files show expected signals:
  continuous ~208 Hz INT1 pulse train on D0; D2 steady center-duty
  PWM during still, oscillating duty during motion)

## Observations during session
- Orchestrator ran without intervention
- No bench disturbances during recording

## Decision
- Use this session: **YES**

## Analysis findings (post-hoc, 2026-05-21)

Ran `replay_parity` against the session 1 CSVs with a toy threshold
tree (window=75, decim=2) to characterize feature distributions
before training. Full analysis in `docs/lab-notebook/2026-05-21.md`.
Items below are the ones that affect how THIS session's data should
be used downstream.

**Feature ranges (post-filter, 1697 windows per class):**

| Metric | Still (class=0) | Motion |
|---|---|---|
| var_norm | 2.4e-7 to 9.4e-7 | 3.3e-6 to 3.7e-3 |
| p2p_norm | 1.9e-3 to 4.9e-3 | 1.6e-2 to 4.5e-1 |

Minimum motion-to-maximum-still separation: 3.5× on variance, 3.3×
on p2p (excluding still-class p2p outliers, see warmup note below).
A trained tree on this session alone would find clean thresholds.

Note: this 3.5× is **not** the same statistic as the "Variance ratio
X = 153×" in the Post-session checks above. The 153× is a
class-aggregate ratio (whole-recording per-axis variance of motion
divided by whole-recording per-axis variance of still). The 3.5×
here is a worst-case per-window margin: minimum motion-window
variance divided by maximum still-window variance, on the norm axis,
post-windowing. The worst-case metric is harsher; the trained tree
sees per-window features, so the 3.5× number is the one that
matters for classifier separability.

**Bench-warmup effect — recommended discard region:**

The 7 windows where p2p exceeds the still-class typical ceiling
(>4.9e-3) cluster heavily in the first minute:

- First 60 s: ~85 windows, 6 outliers → **7.1%**
- Remaining 1140 s: ~1612 windows, 1 outlier → **0.06%**

~100× higher outlier rate during warmup. Rate-normalized, so not a
sample-size artifact. Likely cause: bench/mount/electronics settling
after session start.

**Recommendation for downstream training:** when using session 1
still data, consider discarding the first ~60 seconds (~85 windows
at window=75, decim=2). Do **not** apply this as a hard rule — n=1.
Wait for sessions 2 and 3 to confirm the pattern before any spec
amendment. If the pattern is reproducible, the spec's
"transition margin" section (training-data-spec.md §Transition margin)
should be extended with a session-start margin.

**Tools used for this analysis:**
- `/tmp/replay_parity` built from f56dbfe sources
- Toy tree at `/tmp/toy_tree_75.json` (HP filter bypassed, threshold
  on p2p > 0.005 g; not the trained classifier)
