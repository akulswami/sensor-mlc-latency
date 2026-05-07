# Training Data Specification: Custom Motion-vs-Still MLC

**Status:** Draft, pre-collection
**Last updated:** 2026-05-06
**Supersedes:** activity-recognition .ucf approach (preserved at git tag `activity-recognition-final`)

## Purpose

This document specifies the training data collection and validation protocol
for a custom-trained 2-class motion-vs-still decision tree to be deployed on
the LSM6DSOX MLC and reproduced bit-identically as a host-side classifier on
the Jetson Orin Nano. The custom tree replaces the ST-published
`lsm6dsox_activity_recognition_for_mobile.ucf` because (a) the activity tree
was trained on human gait/biking/driving and exhibited feature-space mismatch
with our servo stimulus, and (b) controlling the training set ourselves
removes a reproducibility gap and makes host-side parity trivial.

This spec defines the contract: anyone with the same hardware and this
document should be able to reproduce the training data and obtain a
functionally equivalent tree.

## Classes

Two classes:

- **Class 0 (still):** sensor mounted on bench (and on servo horn,
  consistent with motion-class mounting), no servo motion. Undisturbed.
- **Class 1 (motion):** sensor mounted to servo horn, servo executing 0°↔150°
  oscillation, at one of two speeds (see below).

## Stimulus parameters

### Servo motion (motion class)

- Hardware: Tower Pro SG90 driven by PCA9685 over Jetson I²C bus 1
  (pins 27/28).
- Motion profile: 0° to 150° and back, sustained oscillation.
- Speed: single fixed PWM endpoints (e.g. 1.0 ms / 2.0 ms at 50 Hz
  frame), producing oscillation at a measured frequency. The
  oscillation frequency is reported in the paper as a measured value
  with uncertainty (computed from accel data and PWM transitions on
  Saleae), not as a setpoint.

### Stillness (still class)

- Sensor mounted in identical physical configuration as motion trials
  (servo present and powered, but not commanded to rotate).
- Undisturbed bench, no manual perturbations.

## Sensor configuration

- ODR: **208 Hz** (LSM6DSOX `XL_ODR=0b1010`).
- Range: ±2 g (LSM6DSOX `XL_FS=0b00`).
- Filter chain (MLC pre-feature pipeline): high-pass at ~1 Hz to remove
  gravity. No low-pass. To be tuned during MEMS Studio training; this is
  the starting point.

Rationale for 208 Hz: future-proofing for follow-up work involving faster
stimuli (taps, impacts, brief gestures). For this paper's 1–2 Hz stimulus
26 Hz would be sufficient; 208 Hz is a deliberate exchange of in-paper
window-design flexibility for cross-paper consistency.

## Window length

To be determined empirically. Train candidate trees at three window lengths:

| Samples | Duration @ 208 Hz |
|---|---|
| 25 | 120 ms |
| 75 | 360 ms |
| 200 | 960 ms |

Select on validation accuracy with a tree-depth penalty (prefer shallower
trees at equal accuracy; reject any window length whose best tree exceeds
depth 5).

## Sample count per class

Target: **≥500 non-overlapping feature-vector windows per class, after the
labeling-margin discard step (below).** With 75-sample windows at 208 Hz,
500 windows = 180 sec of recorded class data per class. With 25-sample
windows, 500 windows = 60 sec per class. Either is feasible.

Practical floor for collection: collect enough raw data to yield ≥500
windows for the *longest* candidate window length, so all three candidate
trainings have the same window count. With a 200-sample window and 500
target windows, that's 480 sec ≈ 8 minutes of recorded data per class per
session.

## Sessions and train/test split

Collect across **at least 3 distinct sessions**, on different days or
different times of day, with bench re-setup (sensor unplugged from servo
horn and re-mounted) between sessions to introduce position/orientation
variance.

Hold out **one full session** as the test set. The decision tree is
trained only on the remaining sessions. Validation accuracy and the 90%
parity gate are reported on the held-out test session.

Random window-level splits are forbidden because windows from a single
servo burst correlate, leaking train-into-test.

## Labeling

Ground truth comes from the PWM signal driving the servo, captured on
Saleae channel D2 (or whichever digital channel is allocated; documented
per-session in the lab notebook).

- "Motion" PWM duty: any servo command other than the neutral
  ~1.5 ms / 50 Hz (configured per servo speed).
- "Still" PWM duty: 0 V (PWM disabled) or sustained neutral.

### Transition margin

The servo physically takes ~50–100 ms to begin or stop motion after a PWM
command change. To prevent label noise at boundaries:

- Discard the **first 200 ms** after any PWM "rotate" command.
- Discard the **first 200 ms** after any PWM "stop" command.

### Mid-transition windows

A window whose timespan straddles a PWM transition (some samples labeled
"motion," others "still") is **discarded**, never relabeled. Windows used
for training/test must lie entirely within a stable-label region after the
transition margin.

## Saleae capture configuration

- Digital sample rate: ≥1 MS/s (Logic Pro 8 default 6.25 MS/s is fine).
- Channels:
  - D0 = LSM6DSOX INT1 (sensor data-ready / MLC interrupt, kept for
    cross-reference with measurement runs)
  - D1 = decision GPIO from latency-test binary (Jetson Pin 11). Present
  during all bench runs but not required for training data collection.
  - D2 = PCA9685 OUT0 (PWM signal driving the servo) — labeling ground
    truth
  - A0 = (reserved)
- Capture format: per-session `.sal` file in `data/training/<YYYY-MM-DD>/`
  with raw accel CSV exported from MEMS Studio's HSDataLog.

## Data formats

- Raw accelerometer logs: MEMS Studio HSDataLog CSV format
  (one row per sample, columns: timestamp, ax, ay, az), exported via
  MEMS Studio Data Analysis tab.
- Per-session metadata file: `data/training/<YYYY-MM-DD>/session.json`
  containing servo speed schedule, sensor mount orientation, room
  temperature, time of day, any anomalies.

## Out of scope for this spec

- Tree depth, feature set, and final window length: determined during
  MEMS Studio training based on the data collected per this spec.
- Stress-ng configuration and the experimental measurement protocol:
  separate documents.
- The host-side parity classifier implementation: depends on the trained
  tree; specified after training is complete.

## Feature set

Two MLC features, computed on the acceleration norm only:

- VARIANCE_NORM
- PEAK_TO_PEAK_NORM

Rationale: the experimental stimulus is horizontal oscillation, so gravity
remains on a single axis throughout both classes and norm-axis features
carry the discriminative information without orientation coupling.
Variance and peak-to-peak are both expected to be high during motor-on
and near-zero during motor-off; both are retained for redundancy and
because either may produce a cleaner threshold during MEMS Studio
training. AFS (Automatic Feature Selection) is not used; the feature
set is fixed manually for reproducibility.

## Feature set

Two MLC features, computed on the acceleration norm only:

- VARIANCE_NORM
- PEAK_TO_PEAK_NORM

Rationale: the experimental stimulus is horizontal oscillation, so gravity
remains on a single axis throughout both classes and norm-axis features
carry the discriminative information without orientation coupling.
Variance and peak-to-peak are both expected to be high during motor-on
and near-zero during motor-off; both are retained for redundancy and
because either may produce a cleaner threshold during MEMS Studio
training. AFS (Automatic Feature Selection) is not used; the feature
set is fixed manually for reproducibility.

## Reproducibility checklist

A successful training data collection must produce, for each session:

- [ ] Raw accelerometer CSV(s), one per recording within the session
- [ ] Saleae `.sal` capture spanning the entire session
- [ ] PWM event log derived from Saleae (motion-start/stop timestamps)
- [ ] `session.json` with mount orientation, servo speed schedule, anomalies
- [ ] Lab notebook entry describing setup, deviations, observations

A successful training run must produce:

- [ ] Three candidate `.ucf` files (one per window length) and their
      corresponding decision tree exports
- [ ] Validation accuracy on held-out session for each candidate
- [ ] Selected window length with rationale
- [ ] Final `.ucf` deployed to chip and verified to reproduce the same
      decisions as the host implementation on the same input window
