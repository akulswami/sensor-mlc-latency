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
