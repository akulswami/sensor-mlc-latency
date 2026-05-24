# Pre-Registration: On-Sensor MLC vs. On-Host Inference Latency

**Status:** Committed prior to any experimental data collection.
**Authoritative timestamp:** the Git commit that adds this file to `main`.
**Amendments:** any change to this document after the initial commit must be added as a dated section at the end (`## Amendment YYYY-MM-DD`) and must not edit prior text. Amendments made after data collection has begun must explicitly state what data, if any, had already been collected at the time of the amendment.

---

## 1. Research question

For an IMU-based edge-AI classification pipeline running on an NVIDIA Jetson Orin Nano with an STMicroelectronics LSM6DSOX IMU, does performing classification on the sensor's embedded Machine Learning Core (MLC) produce lower wire-level end-to-end latency than performing classification in software on the host, and how does this comparison change under host CPU contention?

## 2. Hypotheses

Stated as directional, with the null and alternative made explicit. All comparisons are between matched conditions (same stress level, same task, same window).

- **H1 (no-stress):** Median wire-level latency of the on-sensor MLC pipeline is lower than the on-host pipeline under no CPU stress.
  - H1₀: median(latency_MLC | no-stress) ≥ median(latency_host | no-stress)
  - H1₁: median(latency_MLC | no-stress) < median(latency_host | no-stress)

- **H2 (stress):** The median latency advantage of the MLC pipeline over the host pipeline is larger under CPU stress than under no stress.
  - H2₀: Δ_stress ≤ Δ_no-stress, where Δ = median(latency_host) − median(latency_MLC)
  - H2₁: Δ_stress > Δ_no-stress

- **H3 (host degradation):** Median host pipeline latency under CPU stress is greater than under no stress.
  - H3₀: median(latency_host | stress) ≤ median(latency_host | no-stress)
  - H3₁: median(latency_host | stress) > median(latency_host | no-stress)

- **H4 (MLC robustness):** Median MLC pipeline latency under CPU stress differs from no-stress by at most a small effect (defined in §6).

H1 and H3 are expected to be confirmed and are sanity checks. H2 is the substantive contribution. H4 is the falsifiable claim that on-sensor inference is decoupled from host load.

## 3. Design

Two-factor fully-crossed design.

- **Factor A — Pipeline (within-subjects on hardware):** {MLC, host}
- **Factor B — Stress (within-subjects on hardware):** {no-stress, stress}

Four conditions total: (MLC, no-stress), (MLC, stress), (host, no-stress), (host, stress).

**Trials per condition:** n = 500.
**Total trials:** 2,000.

Order of conditions is randomized across blocks; see §7.

## 4. Classification task

**Task:** Single-tap detection on the LSM6DSOX accelerometer.

**Rationale:** ST publishes a canonical MLC reference configuration for tap-class events; the label space is binary and unambiguous (tap event vs. no-tap window); a host-side parity model is straightforwardly trainable from the same raw IMU stream. Tap detection minimizes the labeling-noise confound that gesture and activity recognition would introduce, so observed accuracy and latency differences are attributable to pipeline placement, not labeling disagreement.

**Note on motivation:** Tap detection is a substrate for the latency comparison, not a contribution. The paper does not claim improvement over prior tap-detection methods. If a reviewer objects that tap detection is "too simple" for the contribution, the response is that simplicity of the task is a feature: it isolates the variable of interest (where inference runs), which is the contribution.

## 5. Pipelines

### 5.1 On-sensor MLC pipeline
- LSM6DSOX configured via a `.ucf` file generated in ST MEMS Studio.
- MLC output (class label) drives the sensor's INT pin.
- Jetson reads the class label register over SPI on INT assertion, then asserts a GPIO output (the "decision" edge).
- The full pipeline includes: sensor-internal classification, INT assertion, host SPI read, and host GPIO write.

### 5.2 On-host pipeline
- LSM6DSOX configured to assert data-ready (DRDY) on INT at the same ODR as the MLC pipeline's input rate.
- Jetson reads raw accelerometer samples over SPI on INT assertion.
- A software classifier (sliding window, same window length as the MLC) emits a decision; on positive classification the host asserts the same GPIO output edge.
- Software classifier framework, model architecture, and quantization will be selected during Phase B (see §10) and committed to the repo before any timed runs.

### 5.3 Common
- Both pipelines use the same physical wiring, same INT line as the start-of-window edge, and the same GPIO output pin as the decision edge.
- Both pipelines run on the same Jetson Orin Nano in MAXN power mode with `jetson_clocks` applied.
- Sensor ODR, full-scale range, and filter settings are identical across pipelines.

## 6. Primary and secondary outcomes

### 6.1 Primary outcome
**Wire-level latency per trial:** the time difference, measured by the Saleae Logic Pro 8, between the rising edge of the IMU INT line and the rising edge of the host's decision GPIO, for trials in which a positive classification occurred.

- Sampling: Saleae digital input at ≥ 50 MS/s on both edges.
- Resolution floor: 20 ns at 50 MS/s; reported uncertainty will reflect this.

### 6.2 Secondary outcomes
- 95th-percentile latency per condition.
- Inter-quartile range per condition.
- Maximum latency per condition.

The 99th percentile **will not** be reported as a primary or secondary outcome at n = 500. With 500 trials, the 99th percentile is estimated from approximately 5 tail samples; this is too coarse for cross-condition claims. If 99th-percentile claims become necessary on revision, n must be increased and the present pre-registration explicitly amended.

### 6.3 Effect-size definitions
- **Δ (latency advantage):** median(latency_host) − median(latency_MLC), within a stress level.
- **"Small effect" for H4:** an absolute median difference between MLC stress and no-stress of less than 10 µs, *and* a Hodges–Lehmann shift estimate with a 95% bootstrap CI contained within ±50 µs. Both criteria must be met to declare H4 supported. If either fails, H4 is not supported and this is reported as such.
- The 10 µs / 50 µs thresholds are committed in advance based on the Saleae timing floor and the expected SPI transaction time at the planned bus speed; they are not derived from observed data.

## 7. Randomization and blocking

- Trials are organized into **blocks of 50 trials per condition**, for 10 blocks per condition (40 blocks total).
- Block order across the four conditions is randomized using a fixed pseudo-random seed committed to the repo (`code/analysis/block_order_seed.txt`) prior to data collection.
- Within a block, each trial is initiated by a programmable tap-event generator (see §10) on a fixed inter-trial interval with jitter to avoid harmonic alignment with sensor ODR or stress-ng timing.

## 8. Stress condition

- **Tool:** `stress-ng`, version pinned in `env/stress-ng-version.txt`.
- **Configuration:** to be committed in `code/stress/run_stress.sh` before data collection. Target: saturate all CPU cores at the highest non-thermal-throttling load achievable on the Jetson Orin Nano in MAXN mode.
- **Verification of stress condition:** before each stress block, `top` / `tegrastats` snapshot is logged. Blocks during which sustained CPU utilization is below 95% across cores are flagged and excluded per §11.
- **No-stress condition:** Jetson idle, only the measurement harness and required system services running. Verified the same way; blocks above 10% mean CPU utilization on non-harness cores are flagged and excluded.

## 9. Accuracy parity gate

Before any latency data is collected for the latency comparison, both pipelines must independently demonstrate classification accuracy on a held-out test set such that:

- **|accuracy_MLC − accuracy_host| ≤ 2 percentage points**, and
- both accuracies are ≥ 90% absolute.

The test set is a labeled IMU dataset collected for this purpose, separate from the latency trials, committed to `data/training/` with a fixed train/test split. The split seed and exact test-set hash are committed before any model training.

If the parity gate is not met, the latency experiment is **not run**. Possible responses, in order of preference: retrain the host model (host is more flexible), redesign the MLC features in ST MEMS Studio, or — if neither closes the gap — switch the classification task. Switching the task triggers a pre-registration amendment.

## 10. Items deferred to Phase B (must be locked before data collection)

The following are committed *to be committed* before the latency experiment starts. Each will be added to this document via amendment and to the repository:

- Exact MLC `.ucf` file (`code/mlc_config/`).
- Host classifier architecture, training data hash, and inference code (`code/jetson/host_inference/`).
- Tap-event generator hardware and trigger waveform (`docs/hardware-setup.md`).
- `stress-ng` invocation flags (`code/stress/run_stress.sh`).
- Sensor ODR, full-scale range, filter settings (`docs/measurement-protocol.md`).
- SPI bus speed and exact register-read sequences for both pipelines (`docs/measurement-protocol.md`).

The latency experiment shall not begin until all six items are committed to `main`.

## 11. Exclusion criteria

A trial is excluded from analysis if and only if one of the following, all defined in advance, is true:

1. The Saleae capture for the trial does not contain both the INT rising edge and the decision GPIO rising edge within a 100 ms window. (Capture failure or missed classification.)
2. The block within which the trial occurred fails the stress-condition verification check in §8.
3. A thermal throttling event is logged by `tegrastats` during the trial. (Thermal stress is explicitly out of scope for this Letter.)
4. A second INT edge occurs before the decision GPIO edge. (Overlapping events; ambiguous attribution.)

All exclusions are logged in `data/processed/exclusions.csv` with the trial ID and the exclusion reason. The exclusion rate per condition is reported in the paper. **If the exclusion rate exceeds 10% in any condition, results from that condition are reported with a caveat and the cause is investigated and disclosed.**

No exclusion criterion based on the latency value itself is permitted. Outliers are not removed.

## 12. Statistical analysis plan

### 12.1 Primary tests

- **H1, H3:** one-sided Mann–Whitney U test on per-trial latency.
- **H2:** test on the difference of medians between stress conditions, using a stratified bootstrap (10,000 resamples) of (Δ_stress − Δ_no-stress); one-sided p-value from the bootstrap distribution.
- **H4:** equivalence test against the bound in §6.3, via two one-sided tests (TOST) using a bootstrap of the median difference.

### 12.2 Multiple-comparison correction

Holm–Bonferroni correction applied across the family {H1, H2, H3, H4}, family-wise α = 0.05.

### 12.3 Effect-size reporting
For every comparison: Hodges–Lehmann median shift estimate with 95% bootstrap CI (10,000 resamples), in addition to the p-value. Effect sizes are reported regardless of the test outcome.

### 12.4 Power
At n = 500 per condition, the two-sample Mann–Whitney U test detects a median shift of approximately 0.1 standard deviations of the latency distribution at α = 0.05 with power ≥ 0.95, under typical assumptions for non-normal latency distributions. The expected effect size for H1 and H3 (microseconds-to-milliseconds) is far larger than this, so power is not the limiting factor for medians. Power for H4 (equivalence) and for tail-percentile comparisons is lower; H4 is reported with its CI and tail percentiles are reported descriptively, without significance claims.

### 12.5 Stopping rule
n is fixed at 500 per condition. **No interim analyses, no early stopping, no extension based on observed results.** If hardware failure forces a partial dataset, the paper reports actual n per condition and notes the deviation from this pre-registration.

## 13. Deviations and reporting

Any deviation from this document — protocol, sample size, analysis, exclusions — must be:

1. Documented as a dated amendment to this file.
2. Disclosed in the paper, in a "Deviations from pre-registration" subsection of the methods.

This applies whether the deviation favors or disfavors the hypotheses.

## 14. What this pre-registration does not cover

This document covers the latency comparison only. The following are explicitly out of scope for this Letter and require a separate pre-registration if pursued:

- Memory-pressure stress, I/O stress, thermal stress.
- Cross-platform comparisons (MCU, MPU, TPU, GPU tiers).
- Power consumption.
- Other classification tasks beyond §4.
- Other sensors.

---

## Amendment 2026-05-01 (evening): Switch from SPI to I2C for sensor-host bus

**No experimental data has been collected as of this amendment.** This
amendment is timestamped prior to any measurement code execution beyond
the WHO_AM_I sanity check.

### Change

The original §5.1, §5.2, and §10 reference SPI as the host-sensor bus.
SPI bring-up on the Jetson Orin Nano (JetPack 6.2.2, spidev0.0 on the
40-pin header) failed: the LSM6DSOX did not respond to WHO_AM_I reads
(returned 0x00 / 0x80 / 0xC0 randomly) despite verified wiring and SPI
mode 3 configuration. The same sensor responds correctly on I2C at
address 0x6A on /dev/i2c-7 (Jetson pins 3 and 5).

The host-sensor bus is therefore changed from SPI to I2C for both
pipelines. The change applies uniformly — both the on-sensor MLC
pipeline (host reads class label register) and the on-host pipeline
(host reads raw accelerometer samples) use I2C.

### What is NOT changed

- §1 Research question. Bus choice does not affect the wire-level
  latency comparison.
- §2 Hypotheses. All four hypotheses remain as written.
- §3 Design. Two-factor crossed design unchanged.
- §6.1 Primary outcome (wire-level latency between INT and decision
  GPIO). The Saleae captures both edges regardless of host bus protocol.
- §7 n = 500 per condition.
- §9 Accuracy parity gate.
- §11 Exclusion criteria.
- §12 Statistical analysis plan.

### Effect on the comparison

I2C is slower than SPI for multi-byte reads. This affects both pipelines
equally for register access. For the on-sensor MLC pipeline the host
performs a single-byte register read on INT, so bus latency is small.
For the on-host pipeline the host streams multi-byte raw IMU samples,
so I2C imposes a larger per-sample read overhead than SPI would.

This makes the on-host pipeline strictly slower than it would have been
on SPI. The latency comparison is still a valid comparison, but the
measured difference in favor of MLC will be larger than under an SPI
implementation. The paper must report and disclose this honestly:
results are valid for an I2C-based host pipeline, and the magnitude of
the MLC advantage would be smaller (but presumably still positive) on
SPI.

### Stop condition (carry-over)

The accuracy parity gate (§9) remains a hard requirement. The change in
bus protocol does not affect the parity requirement.

### Repository updates

The following files are updated to reflect this change:
- docs/pin-assignment.md (sensor wiring section)
- docs/lab-notebook/2026-05-01.md (failure log and decision)
- code/jetson/host_inference/whoami_test.py (will be replaced with an
  I2C version before any further work)

---

## Amendment 2026-05-05: Switch classification task from tap detection to binary motion-vs-still

**Data collected under prior protocol that is affected by this amendment:**
The following datasets were collected under the original tap-detection task
and are NOT used as training, validation, or test data for the amended task:

- `data/raw/2026-05-04-taps.csv` (44,154 samples, 54 piezo events)
- `data/raw/2026-05-04-nontaps.csv` (43,265 samples, 0 piezo events)
- `code/jetson/mlc_pipeline/mlc_accuracy.h` and `mlc_latency.h`
  (custom-trained tap classifiers)

The bring-up latency data collected on 2026-05-04 (Phase 1: hardware
single-tap detector at INT_DUR2 sweep, n≈120 events total; Phase 2: on-host
sliding-window classifier, n=14 events) is descriptive bring-up only and
was acknowledged as such in the lab notebook (`docs/lab-notebook/2026-05-04.md`,
"NOT YET ANALYSIS-READY" section). It is not analysis data under the original
or amended pre-registration. The structural-floor finding from the INT_DUR2
sweep is retained as a separate methodological observation about the
LSM6DSOX hardware tap detector and may inform paper discussion but is not
part of the pre-registered hypothesis tests.

**No pre-registered measurement runs (n=500 per condition) have been
executed under either the original or amended protocol as of this amendment.**

### Change

The original §4 (classification task) specifies single-tap detection. This
amendment changes the task to **binary motion-vs-still classification** on
the LSM6DSOX accelerometer.

### Rationale

Pilot work under the original tap-detection task revealed that the LSM6DSOX
Machine Learning Core (MLC) is poorly suited to single-tap classification
at the available window sizes (configurable from ~38 ms to ~2.45 s at 416 Hz
ODR). Specifically:

1. A single hand-tap is a transient event of approximately 5-10 ms duration.
   At the MLC's minimum window size (~38 ms, 16 samples), a tap event
   occupies at most 25-50% of one feature window. Across the available
   feature library (mean, variance, energy, peak-to-peak, zero-crossings),
   the signal-to-noise ratio of any feature computed over such a window
   is poor: the tap's high-amplitude content is diluted by mostly-idle
   samples within the window.

2. Empirical validation of two custom-trained MLC configurations
   (window=16/154 ms with 12-leaf tree at 97.21% training accuracy, and
   window=255/2.45 s with 3-leaf tree at 95.06% training accuracy) showed
   that the trained classifiers do not achieve the >90% accuracy required
   by §9 against piezo-confirmed ground truth. The 154 ms window
   configuration produced ~79% time in the "tap" class during a 16-second
   idle (no-input) recording, indicating overfitting to training-session
   noise rather than learning a tap-specific signature.

3. The LSM6DSOX is documented (ST AN5259, datasheet) as targeted at
   activity-recognition-class workloads — still / walking / running, motion
   vs no-motion, gesture detection — for which ST publishes validated
   reference configurations. Tap detection is not in this design envelope;
   it is handled by the dedicated hardware tap-detection unit, which is a
   separate signal path on chip.

The original choice of tap detection (per §4 rationale: "ST publishes a
canonical MLC reference configuration for tap-class events") was based on
an incorrect characterization of ST's reference materials. ST publishes
hardware-tap-detector reference register configurations, not MLC reference
.ucf files for tap. This amendment corrects the resulting task choice.

### New task definition

**Task:** Binary classification of LSM6DSOX accelerometer windows as
"motion" or "still."

**Operational definitions:**

- **Still:** sensor stationary on a rigid surface (laboratory bench), no
  human contact with the breakout or its supporting structure, no
  externally-induced vibration above ambient laboratory noise floor.

- **Motion:** sensor handheld and being moved through any combination of
  translation and rotation typical of a wearable or handheld device in
  active use. Includes (without restriction): lifting and replacing the
  sensor, walking with sensor in hand, hand-held shaking, deliberate
  rotation. Does NOT include external mechanical impact on the sensor
  (taps, drops, table strikes), which are out of scope for this amendment.

The task is binary; a multi-class formulation (still / walking / running /
stationary motion) is explicitly out of scope and reserved for future work.

### Ground truth

Piezo-disc ground truth is replaced for this task. Motion vs still is not
a transient-event task and a per-event piezo trigger is inappropriate.
Ground truth is provided by experimenter labeling synchronized to a wall
clock, recorded in a CSV alongside each data capture: `(epoch_start,
epoch_end, label)` where `label ∈ {still, motion}`. Epochs are minimum
3 seconds long. Transitions between states are excluded from analysis (a
1-second guard band before and after each labeled epoch boundary is
removed from training/validation/test sets).

This is a methodological deviation from the original protocol's per-trial
piezo trigger. It is necessary because motion-vs-still is a sustained-state
classification, not a transient-event classification, and a piezo trigger
does not provide meaningful ground truth for sustained states.

### Pipelines

**On-sensor MLC pipeline (revised):** The MLC is configured using a
publicly-available ST reference configuration for activity recognition,
collapsed to binary by treating any ST-defined "motion" class as "motion"
and the ST-defined "still" / "stationary" class as "still." The exact ST
reference .ucf file used is committed to `code/mlc_config/` and its source
URL and SHA256 hash are committed to `docs/measurement-protocol.md` before
any data collection.

**On-host pipeline (revised):** The host pipeline computes the same
feature(s) used by the ST reference MLC configuration, over the same window
size, and applies the same threshold(s) as the reference decision tree.
The host implementation is parity-equivalent to the on-sensor decision
algorithm by construction. Implementation details and the exact feature
formulas are committed to `docs/measurement-protocol.md`.

This is a stronger parity requirement than the original protocol allowed
for tap detection, where the host classifier was independently designed.
Reviewers can verify that the comparison is between the same algorithm
running in two locations, not between two different algorithms.

### What is NOT changed

- §1 Research question. The wire-level latency comparison between on-sensor
  and on-host inference placement remains the research question.
- §2 Hypotheses H1, H2, H3, H4. All four hypotheses are retained as written;
  they reference "MLC pipeline" and "host pipeline" without reference to
  the specific task.
- §3 Design. Two-factor (pipeline × stress) fully-crossed design unchanged.
- §6 Primary and secondary outcomes (wire-level latency between INT and
  decision GPIO). Unchanged.
- §7 n = 500 per condition × 4 conditions = 2,000 trials.
- §8 Stress condition. Unchanged.
- §9 Accuracy parity gate (≥90% both, ≤2pp gap). Applies to the new task;
  the gate threshold is unchanged.
- §10 Items deferred to Phase B. The list is unchanged in structure; the
  specific MLC `.ucf` file is now ST's reference file rather than a custom
  trained file.
- §11 Exclusion criteria. Unchanged. The "trial" unit for this task is one
  state-classification window's INT-to-decision-GPIO event, defined exactly
  as in the original protocol.
- §12 Statistical analysis plan. Unchanged.
- §13 Deviations and reporting. Unchanged.

### Effect on the comparison

The change from a transient-event task (tap) to a sustained-state task
(motion vs still) changes what "trial" means:

- Original: one trial = one piezo-triggered tap event, latency measured from
  piezo edge (or, equivalently, from the first INT edge in the on-sensor
  case) to decision-GPIO edge.

- Amended: one trial = one classification-window evaluation by the chip
  during which the chip's output transitions from one class to another (a
  state transition event), latency measured from the INT edge marking that
  transition to the decision-GPIO edge produced by the host on reading the
  new class.

The wire-level measurement methodology (Saleae captures INT and decision-GPIO
edges; latency is the difference) is unchanged. What is captured is also
unchanged: a rising edge on INT, a rising edge on the decision GPIO, and a
ground-truth signal (now: experimenter labels rather than piezo).

The on-host pipeline now also performs windowed classification and asserts
its decision GPIO on each window's classification, providing a directly
comparable measurement. Both pipelines emit one decision per window. Trial
count is generated by collecting state transitions during alternating
labeled motion/still epochs.

Latency magnitudes may differ from those that would have been observed
under the original tap task. The H1, H2, H3, H4 hypotheses are tested on
whatever latency distributions are produced by the new task. We do not
predict in advance whether the on-sensor MLC will be faster or slower
than the on-host pipeline under the new task; H1₀ and H1₁ are the same as
in the original protocol.

### Stop condition

The accuracy parity gate (§9) is a hard requirement. If the ST reference
MLC configuration and the parity-matched host implementation do not both
hit ≥90% on a held-out test set with ≤2pp gap, the latency experiment is
not run, regardless of how reasonable individual numbers may look.

### Repository updates

The following files are added or updated to reflect this amendment:
- `docs/measurement-protocol.md` (new): operational definitions, ST .ucf
  source and hash, host classifier feature/threshold specification, ground
  truth labeling procedure
- `code/mlc_config/` (new directory): ST reference .ucf file, source URL,
  SHA256 hash
- `data/raw/2026-05-04-taps.csv` and `2026-05-04-nontaps.csv`: retained
  in the repository for reproducibility, marked as not-used in
  `data/raw/README.md`
- `docs/lab-notebook/2026-05-05.md` (new): logs the diagnostic work that
  led to this amendment, including the bank-constant fix in
  `latency_test_mlc.c` (FUNC_CFG_ACCESS embedded-bank value 0x40 → 0x80)

### External timestamp

This amendment is committed to the public repository at github.com/akulswami/sensor-mlc-latency
and the commit is tagged as `prereg-amendment-2026-05-05`. The repository
release is mirrored to Zenodo with DOI: 10.5281/zenodo.20042123 (https://doi.org/10.5281/zenodo.20042123) The
DOI of the Zenodo release containing this amendment is the authoritative
external timestamp.


## Amendment 2026-05-06: Replace ST reference activity-recognition .ucf with custom-trained 2-class motion-vs-still MLC

**Data collected under prior protocol that is affected by this amendment:**

The following datasets and artifacts were produced under the v2 amendment
(activity-recognition .ucf, 2026-05-05) and are NOT used as training,
validation, or test data for the amended task:

- Smoke-test latency observations from `latency_test_mlc_activity` runs
  on 2026-05-05 and 2026-05-06 (idle: ~464–479 µs across n=4 transitions;
  under stress-ng matrixprod CPU saturation: ~489–516 µs across n=18
  transitions). These are bring-up validation of the measurement pipeline,
  documented in chat transcripts and lab notebook entries; they are not
  pre-registered measurement runs.
- The integrated `code/mlc_config/lsm6dsox_activity_recognition_for_mobile.{ucf,h}`
  ST reference files and the derived `mlc_activity.h`. Retained in the
  repository at git tag `activity-recognition-final` for reproducibility
  of the v2 protocol; not used under the v3 protocol.

No pre-registered measurement runs (n=500 per condition) have been executed
under either the original, v2-amended, or v3-amended protocol as of this
amendment.

### Change

The v2 amendment (2026-05-05) committed the on-sensor MLC pipeline to use
ST's publicly-available activity-recognition reference configuration
(`lsm6dsox_activity_recognition_for_mobile.ucf`), with the host pipeline
implementing a parity-equivalent reproduction of the same decision tree.

This v3 amendment replaces that commitment. The on-sensor MLC will be
configured with a **custom-trained 2-class motion-vs-still decision tree**,
trained per `docs/training-data-spec.md`. The host pipeline will be a
direct software port of the same trained tree (same features, same
thresholds, same window length), trained once and deployed to both
locations — making bit-identical parity automatic by construction rather
than something to be earned through reverse-engineering ST's reference.

### Rationale

Empirical work on 2026-05-05 and 2026-05-06 evaluated the ST activity-
recognition .ucf against the planned servo-driven stimulus
(0°↔150° horizontal oscillation via SG90, see `docs/training-data-spec.md`).
The polling probe (`mlc_poll_probe2_activity`) captured classifier behavior
across multiple stimulus regimes:

1. **Stationary baseline (n=11,951 polls, 24 s):** 100% class 0x00.
   Noise floor is clean.

2. **Hand-shake at servo-equivalent profile (n=11,945 polls, 24 s):**
   First non-zero class transition observed at t=25.3 s, transitioning to
   class 0x0C ("Driving"). Hand-shake matched the intended servo motion
   profile (~2 Hz oscillation, ~2 cm amplitude); the classifier mapped it
   to Driving rather than Walking, indicating the servo stimulus is out
   of distribution relative to the human-gait training corpus on which
   ST's tree was trained.

3. **Sustained high-amplitude rotation (n=11,909 polls, 24 s):** Classifier
   transitions stabilize on a deterministic ~2.83-second cadence,
   consistent with one MLC feature window (75 samples at 26 Hz =
   2.885 s). State transitions occur at window boundaries with ±2 ms
   variance across n=16 transitions, indicating the latency between true
   stimulus change and classifier output is dominated by window-boundary
   quantization (0–2.83 s) rather than by inference delay.

4. **Onset latency from cold start: 11.2 s** (≈4 windows of sustained
   motion before first non-zero class output), making the originally
   pre-registered burst protocol (1 s rotate / 5 s still / 1 s rotate
   / 5 s still) unusable: bursts shorter than one feature window cannot
   produce a state transition. The minimum viable burst length under the
   ST .ucf is ~3 s motion / ~6 s still, yielding ~9 transitions per
   minute and requiring approximately 7.5 hours of bench time to reach
   n=500 transitions per condition × 4 conditions.

The above are not failure modes of the ST .ucf — it is correctly
classifying its training distribution. They are evidence that ST's
human-gait training corpus is mismatched with the servo-driven stimulus
this protocol uses, and that the resulting feature-window quantization
constrains the experimental design more than is necessary.

A custom-trained tree, trained on data collected from the actual
servo rig per `docs/training-data-spec.md`, addresses both:

- The training distribution matches the deployment distribution by
  construction. Accuracy on motor-on vs motor-off is expected to be
  near-trivially high (variance and peak-to-peak features are large
  during oscillation, near-zero during still).
- Window length becomes a tunable parameter selected on validation
  accuracy. Smaller windows enable shorter bursts and faster experimental
  campaigns.

### What is NOT changed

- §1 Research question. Unchanged.
- §2 Hypotheses H1, H2, H3, H4. Unchanged. The hypotheses reference
  "MLC pipeline" and "host pipeline" without reference to which specific
  classifier those pipelines run.
- §3 Design. Two-factor (pipeline × stress) fully-crossed, n=500 per
  condition × 4 conditions = 2,000 trials. Unchanged.
- §4 Classification task remains binary motion-vs-still (per v2). The
  task definition is unchanged; only the implementation of the classifier
  changes.
- §6 Primary and secondary outcomes. Wire-level INT-to-decision-GPIO
  latency, measured by Saleae. Unchanged.
- §8 Stress condition. Unchanged.
- §9 Accuracy parity gate (≥90% both pipelines, ≤2pp gap). Unchanged.
- §11 Exclusion criteria. Unchanged.
- §12 Statistical analysis plan. Unchanged.
- §13 Deviations and reporting. Unchanged.

### What changes

- §5.1 (On-sensor MLC pipeline): The MLC `.ucf` is now a custom-trained
  2-class tree per `docs/training-data-spec.md` rather than ST's
  activity-recognition reference. Training methodology, feature set,
  window length selection, sample count, sessions, and train/test split
  are specified in `docs/training-data-spec.md`.
- §5.2 (On-host pipeline): The host classifier is a direct software port
  of the same trained tree, sharing features, thresholds, and window
  length. Implementation in `code/jetson/host_inference/`. Parity is
  bit-identical by construction, not by reproduction of an external
  reference.
- §10 Items deferred to Phase B: the specific MLC `.ucf` is no longer
  ST's reference but a custom-trained file produced via MEMS Studio per
  the training-data spec.

### Stop condition

The §9 accuracy parity gate remains the hard requirement. If the
custom-trained MLC and the host port do not both hit ≥90% on the
held-out test session with ≤2pp gap, the latency experiment is not run.
The custom-trained approach should make this gate easier to satisfy
than the v2 approach, not harder, because the host pipeline is the
same trained tree rather than a reverse-engineered reproduction.

### Repository updates

- `docs/training-data-spec.md` (committed at git SHA 57b16bd): authoritative
  specification of training data collection, feature set, window length
  selection, sessions, and train/test split.
- Tag `activity-recognition-final` (commit `b900463`) preserves the v2
  protocol artifacts for reproducibility.
- New `.ucf` file and host port to be committed under `code/mlc_config/`
  and `code/jetson/host_inference/` respectively, after training data
  collection and MEMS Studio training are complete. Those commits are
  the operational gating event for execution of the pre-registered
  measurement runs.

### External timestamp

This amendment is committed to the public repository at github.com/akulswami/sensor-mlc-latency
and the commit will be tagged as `prereg-amendment-2026-05-06`. The
repository release will be mirrored to Zenodo with a new DOI distinct
from the v2 DOI (10.5281/zenodo.20042123). The new DOI is 10.5281/zenodo.20060848 (https://doi.org/10.5281/zenodo.20060848). The DOI of the Zenodo release containing this amendment is the authoritative external timestamp.
## Amendment 2026-05-22: MLC ODR clarification, training-time labeling protocol, and window-length evaluation status

**Data collected under prior protocol that is affected by this amendment:**

Training data collected on 2026-05-20, 2026-05-21, and 2026-05-22 (see
`data/training/`) was collected under the protocol described in
`docs/training-data-spec.md` as committed at git SHA 57b16bd, with the
implementation deviations documented below. All three sessions were
collected before this amendment was written; this amendment documents
the actual protocol used and the corrections required, rather than
proposing a new protocol going forward.

The data is retained and is the input to the custom-trained 2-class MLC
under the v3 amendment. No pre-registered measurement runs (n=500 per
condition) have been executed; this amendment precedes measurement.

### Change 1: MLC ODR specified at 104 Hz (sensor ODR remains 208 Hz)

The training-data-spec (§"Sensor configuration") states "ODR: **208 Hz**"
without distinguishing the accelerometer output data rate from the MLC
output data rate. AN5259 (LSM6DSOX Machine Learning Core application
note, §1) caps the MLC ODR at 104 Hz; the sensor can sample faster than
the MLC consumes.

The training and host-side classifier in this work use:

- **Accelerometer ODR: 208 Hz** (matches spec)
- **MLC ODR: 104 Hz** (decimation ratio 2:1, applied inside the MLC)

Window-length calculations in the spec table (e.g. "75 samples = 360 ms
@ 208 Hz") implicitly assumed the MLC ODR equaled the sensor ODR. With
the corrected MLC ODR of 104 Hz, MLC windows are twice as long:

| Samples | Spec implied | Actual @ 104 Hz |
|---|---|---|
| 25  | 120 ms | 240 ms |
| 75  | 360 ms | 721 ms |
| 200 | 960 ms | 1923 ms |

This does not affect §6 (latency outcome) or §9 (parity gate), which are
defined on MLC inference events at the actual MLC ODR.

### Change 2: Training-data labeling protocol — by-file, not by-PWM-transition

The training-data-spec §"Labeling" specifies:

> Ground truth comes from the PWM signal driving the servo, captured on
> Saleae channel D2. ... Discard the first 200 ms after any PWM "rotate"
> command. Discard the first 200 ms after any PWM "stop" command.

This protocol assumed each training session would interleave rotate
bursts and still segments within a single recording, with PWM transitions
on Saleae D2 providing the ground truth at sample granularity.

This protocol was **not implemented**. The actual training data
(`data/training/2026-05-{20,21,22}/`) was collected by the orchestrator
(`code/orchestrator/run_session.py`) which records each class as a
separate continuous recording: 1200 sec of pure still data (PWM at center
or disabled, no commanded motion) followed by 1200 sec of pure motion
data (PWM oscillating continuously). The two recordings are saved as
`still/accel.csv` and `motion/accel.csv` respectively.

Labels are therefore assigned **by source file**, not by PWM state at
sample time. Saleae captures (`still/saleae.sal`, `motion/saleae.sal`)
were collected but do not drive labeling — they serve cross-reference
for measurement runs (per the spec's mention of "kept for cross-reference
with measurement runs").

**This deviation is unplanned.** No prior lab-notebook entry or commit
documents a decision to abandon the PWM-transition labeling protocol;
it appears the orchestrator's per-class design and the spec's
PWM-transition design were never reconciled, and the spec's protocol was
silently superseded by the orchestrator's. The deviation is identified
and documented here at first audit.

**Methodological assessment:** The by-file protocol is, on examination,
defensible — arguably strictly simpler than the PWM-transition protocol:

- **No transition-margin labeling noise.** With no within-recording
  transitions, the 200-ms post-transition margin and mid-transition
  window discard rules of the spec are moot. All samples in a recording
  are unambiguously labeled.
- **Train/test split integrity is preserved.** The spec's intent that
  random window-level splits leak train-into-test is honored: holdout
  is by session (session 3 held out per `docs/train-test-split-decision.md`,
  commit b5a5fd6), not by random window.
- **Equivalent statistical power.** Spec's target of ≥500 windows per
  class is exceeded. MEMS Studio reports 6,734 instances in the
  combined session-1+2 training corpus; sample-count gate cleared.

**Methodological cost:** The by-file protocol does not test the
classifier's behavior at the boundary moment when motion stops or
starts. Pre-registered measurement runs at §6 latency outcomes do
involve such transitions and therefore exercise this regime; if the
classifier behaves anomalously near transitions, measurement runs
will surface it. The training set's lack of transition-region windows
is acknowledged but not corrected — by-file is the protocol now.

**Going forward:** future training data collections under this
pre-registration use the by-file protocol. `docs/training-data-spec.md`
will be updated by a separate commit to reflect this. Any return to the
PWM-transition protocol will require a further amendment.

### Change 3: Window-length evaluation in progress

The spec §"Window length" requires three candidate trees (window =
{25, 75, 200} samples) be trained and the best selected on validation
accuracy with a tree-depth penalty.

As of this amendment, only **w=75** has been trained
(`data/mems-studio/2026-05-22-w75/`). The corresponding decision tree is
depth 1, a single threshold on PEAK_TO_PEAK at 0.049316 on the IIR1-HP
filtered acceleration norm. Training-set accuracy on sessions 1+2
combined is 100%.

This is not yet a generalization claim; the parity gate at §9 (host
classifier and silicon classifier each ≥90% on the held-out test session,
with ≤2pp gap) is the gating criterion, and is run on session 3
(2026-05-22) which was not loaded into MEMS Studio for training.

Window lengths 25 and 200 will be trained, evaluated against the parity
gate, and a final selection made on validation accuracy. The trained
w=75 classifier is preserved at `data/mems-studio/2026-05-22-w75/` for
reproducibility regardless of which window length is finally selected.

### What is NOT changed

The hypothesis structure (§2), design (§3), task definition (§4),
primary and secondary outcomes (§6), stress condition (§8), accuracy
parity gate (§9), exclusion criteria (§11), statistical analysis (§12),
and deviations-reporting protocol (§13) are unchanged.

The classifier itself — features (VARIANCE_NORM, PEAK_TO_PEAK_NORM on
acceleration norm), filter (IIR1 HP at fc=1 Hz), AFS-off, and feature
selection by manual specification — is unchanged from the v3 amendment.

### Implementation details NOT requiring pre-registration

The following choices in `code/jetson/host_inference/parity_core.c` and
`code/analysis/mlc_json_to_parity.py` are implementation defaults
verified against silicon by the §9 parity gate, not pre-registered
methodological choices:

- IIR filter coefficient sign convention. MEMS Studio's UI uses
  H(z) = (b1+b2·z⁻¹)/(1−a2·z⁻¹) (Convention B); parity_core.c uses
  H(z) = (b1+b2·z⁻¹)/(1+a2·z⁻¹) (Convention A, matching AN5259's
  notation). The extractor `mlc_json_to_parity.py` sign-flips a2
  when emitting `tree.json`. Verified via scipy.signal.freqz that
  the two conventions yield identical frequency response with the
  sign-flip applied.
- Variance estimator: biased (1/N) is the default; will be revised to
  unbiased (1/(N−1)) if parity gate fails at the variance feature.
- Threshold comparison operator: `<=` (lte) is the default; will be
  revised to `<` (lt) if parity gate fails on exact-threshold windows.

These are verifiable against silicon, not methodological commitments
that require pre-registration.

### External timestamp

This amendment is committed to the public repository at
github.com/akulswami/sensor-mlc-latency and the commit is tagged as
`prereg-amendment-2026-05-22`. The repository release is mirrored
to Zenodo at a new DOI distinct from the v2 (10.5281/zenodo.20042123)
and v3 (10.5281/zenodo.20060848) DOIs. The new DOI is
10.5281/zenodo.20358317 (https://doi.org/10.5281/zenodo.20358317).
The DOI of the Zenodo release containing this amendment is the
authoritative external timestamp.
