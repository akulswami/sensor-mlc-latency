# Session 3 — 2026-05-22

## Conditions
- Time: 20:46 - 21:07 PST
- Ambient: indoor, climate-controlled
- Servo orientation: flat on heavy base, horn swings horizontally
- Sensor offset on horn: tip mount, foam tape, re-mounted post-session-2
- Sample rate: 208 Hz nominal, ~212.5 Hz effective

## Post-session checks
- File integrity: PASS (all last-line 4 fields, both end \n)
- Variance ratio: X = 155× (0.124072 / 0.000801; well above 50×
  threshold from session-runbook.md)
- Sweep log: 1200 transitions exact (600 TO_MAX + 600 TO_MIN)
- Saleae spot check: PASS (both .sal files show expected signals:
  continuous ~208 Hz INT1 pulse train on D0; D2 steady center-duty
  PWM during still, oscillating duty during motion)

### Mount-orientation evidence (re-mount verification)
Full-session still means (vs session 1 and session 2 for context):

| Axis | Session 1 | Session 2 | Session 3 |
|---|---|---|---|
| X mean | ~0 | -0.0088 g | **-0.0214 g** |
| Y mean | ~0 | -0.0555 g | **-0.0524 g** |
| Z mean | -0.970 g | -0.968 g | -0.970 g |

Session 3 is distinguishable from session 2 primarily by the X axis:
12.6 mg delta corresponds to ~0.7° tilt about the Y axis. From
session 1 (X and Y both near 0), session 3 differs by ~1.2° tilt
about Y and ~3.0° tilt about X. Three sessions, three distinct
orientations.

Honest note on re-mount magnitude: the Y component is nearly
unchanged from session 2 (-0.0524 vs -0.0555, a 3 mg delta within
several×noise-floor). The new orientation came primarily from a
shift about the Y axis (X mean), not the X axis (Y mean). This is
thinner re-mount evidence than session 2 vs session 1 was. The
12.6 mg X delta is ~15× the noise floor (0.0008 g), so it's
empirically real, but reviewers may note the geometric similarity
to session 2. Decision was to accept this rather than re-mount
again — spec requires "variance" without specifying magnitude.

Full-session X mean (-0.0214) matches the 5-sec pre-session sanity
(-0.0211) within 0.3 mg, confirming the orientation is stable
across the 1200 sec recording, not drifting.

## Observations during session
- Orchestrator ran without intervention
- No bench disturbances during recording

## Decision
- Use this session: **YES**

## Three-session corpus status

This completes the spec's "at least 3 distinct sessions" requirement
(training-data-spec.md §Sessions and train/test split). One full
session will be held out as test; the remaining two are training.
Held-out session selection is downstream; not decided in this notes
file.
