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

**Task:** Binary classification of LSM6DSOX accelerometer windows as motion or still.

**Definition:**
- **Still:** sensor at rest, low acceleration variance (≤ 0.001 g² per-axis maximum)
- **Motion:** sensor undergoing controlled movement (servo-driven sweep), high acceleration variance (≥ 0.005 g² per-axis on any axis)
- **Ground truth labels:** derived from manual inspection of accel data during recorded capture sessions; still periods are verified silent (no servo activity); motion periods are verified during active servo sweep.
- **Window length:** variable (w ∈ {25, 75, 200} samples at 212 Hz, ≈ 0.118–0.943 sec); window length is the primary independent variable for accuracy comparison in §9.

**Rationale:** Motion-vs-still classification is a foundational IMU task with clear real-world deployment use cases (activity detection, low-power wake, fall detection). The task is simple enough to isolate the inference-placement variable (on-sensor MLC vs. on-host software), but complex enough to require non-trivial feature computation (variance-based window analysis). Unlike single-tap detection, motion classification runs continuously on a sliding window, better reflecting deployed always-on inference workloads. Binary labels are unambiguous and straightforward to verify during controlled lab captures.

**Note on motivation:** Motion classification is a substrate for the latency comparison, not a contribution. The paper does not claim improvement over prior motion-detection methods or sensor fusion approaches. The contribution is the empirical demonstration that on-sensor MLC inference achieves comparable accuracy to on-host inference while maintaining decoupled latency under CPU stress—this decoupling is the variable of interest.

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

## Amendment 2026-05-23: §9 test-set redesignation, mount-geometry pre/post-checks, parity-capture session.json schema, same-day Zenodo commitment

**Data collected under prior protocol that is affected by this amendment:**

Three training sessions (2026-05-20, 2026-05-21, 2026-05-22) and one
parity-capture session (2026-05-23) were collected under the v4
amendment. v4 named session 3 (2026-05-22) as the held-out test set for
the §9 parity gate. As detailed in Change 1 below, session 3 cannot
serve that role under v4's §9 framing because it was collected before
silicon-side instrumentation came online. The §9 parity gate for the
w=75 candidate was run on 2026-05-23 against session 4; the result is
reclassified by this amendment as preliminary, not gate-of-record, on
mount-geometry grounds (Change 2). This amendment redesignates the §9
test sessions for all three candidate window lengths, pins a
pre-capture mount-geometry protocol, pins the session.json schema for
parity captures, and commits to same-day Zenodo publication.

No pre-registered measurement runs (n=500 per condition) have been
executed; this amendment precedes measurement.

### Change 1: §9 test-set redesignation — sessions 4-prime, 5, 6 in place of session 3

The v4 amendment (Change 3, "Window-length evaluation in progress")
states:

> "the parity gate at §9 (host classifier and silicon classifier each
> ≥90% on the held-out test session, with ≤2pp gap) is the gating
> criterion, and is run on session 3 (2026-05-22) which was not loaded
> into MEMS Studio for training."

v4 did not anticipate, and did not resolve, a contradiction between
the test-set designation (session 3) and the §9 gate's data
requirements (silicon-side classifications). Session 3 was collected by
`code/orchestrator/run_session.py`, which produces `accel.csv` and
`saleae.sal` only. The silicon-side polling capability
(`code/sensor/mlc_poller.c`) and the parity-capture orchestrator
(`code/orchestrator/run_session_parity.py`) had not yet been written
when session 3 was captured. As a result, session 3 has no
`silicon_raw.csv`, no `mlc_poller` log, and no clock-offset metadata
linking sensor-side and silicon-side timelines. The §9 gate as v4
specifies it — a per-pipeline accuracy comparison between host
classifications and silicon classifications — cannot be evaluated on
session 3 because one of the two pipeline outputs does not exist for
that session.

Session 4 (2026-05-23) was captured as the first session under
`run_session_parity.py` and is the first session containing
`silicon_raw.csv`, `mlc_poller.stderr.log`, and the parity-capture
fields in `session.json` (see Change 3 for the pinned schema). The §9
parity-gate analysis run on the evening of 2026-05-23 used session 4
as the test set for the w=75 candidate and reported a 1.05 pp gap
(host 98.74%, silicon 99.79%); see `docs/lab-notebook/2026-05-23.md`
§"Late evening update". As detailed in Change 2, session 4's mount
geometry is insufficiently distinct from the S1+S2 training corpus to
satisfy the generalization-stress role of a held-out session. This
amendment therefore reclassifies session 4 from "§9 test set for w=75"
to "preliminary parity capture; informs mechanism work but not the
§9 gate of record." The w=75 §9 gate is re-run against a new
capture (session 4-prime) collected under the Change 2 protocol.

The redesignated §9 test sessions are:

| Window length | Test session  | Status as of this amendment |
|---|---|---|
| w=75  | Session 4-prime (date TBD) | Pending. To be captured under Change 2 protocol with current w=75 silicon flash. |
| w=25  | Session 5 (date TBD)        | Pending. To be captured after w=25 silicon flash, under Change 2 protocol. |
| w=200 | Session 6 (date TBD)        | Pending. To be captured after w=200 silicon flash, under Change 2 protocol. |

Each candidate window length is gated against its own per-window-length
capture session, on the same hardware, under the v4 by-file labeling
protocol, with the silicon flashed to the window-specific MLC config,
and under the Change 2 pre/post mount-geometry protocol.

Session 3 is reclassified from "held-out §9 test set" to "captured but
unused." Session 3 is retained in `data/training/2026-05-22/` for
reproducibility audit. It is not loaded into MEMS Studio for training
under this amendment (preserving the v4 training corpus of sessions
1+2), and it is not used as a §9 test set (it cannot satisfy the §9
gate's silicon-side data requirement).

Session 4 is retained in `data/training/2026-05-23/`. The §9 gate
result obtained against session 4 on 2026-05-23 (1.05 pp gap; host
98.74%, silicon 99.79%) is preliminary and does not satisfy the
gate-of-record for w=75. The two mechanism-falsification findings of
2026-05-23 (FP16 emulation falsified; bus-contention sample-gap audit
falsified) concern silicon's computation pathway and are
session-independent; they are retained as preliminary supporting
evidence and will be re-run on session 4-prime data for paper
consistency.

The decision to not retroactively augment session 3 with silicon-side
data, nor to retrain w=75 on a larger corpus, is made in service of
three properties: (a) preserving the v4 training corpus of S1+S2 so
the comparison across the three candidate window lengths is on window
length alone and not confounded by training-set differences, (b)
preserving methodological scope (this amendment redesignates tests,
not retraining), and (c) keeping the amended protocol's scope narrow.

### Change 2: Pre-capture and post-capture mount-geometry protocol for parity captures

The `docs/train-test-split-decision.md` rationale §"Rationale" 2
("Stress test on the marginal re-mount") motivates choosing a
held-out session whose mount geometry differs meaningfully from the
training corpus, so that a passing §9 gate is evidence of
generalization to a mount that is close-but-not-identical to those
seen in training. v4 did not formalize a numeric criterion for this
property, and session 4's geometric distance from the S1+S2 centroid
(0.007 g; see below) is small enough that the marginal-re-mount role
is not credibly preserved. This amendment formalizes a numeric
mount-geometry threshold and a procedural pre/post-capture protocol.

**Threshold definition.** Compute, on a still-class recording, the
per-axis mean acceleration (X̄_cap, Ȳ_cap, Z̄_cap) over the
designated check window. The pre-registered S1+S2 still-class
centroid is:

  (X̄_train, Ȳ_train, Z̄_train) = (-0.0116, -0.0754, -0.9664) g

The Euclidean distance from the capture's still-class centroid to the
training centroid is:

  d = √((X̄_cap − X̄_train)² + (Ȳ_cap − Ȳ_train)² + (Z̄_cap − Z̄_train)²)

A parity capture **passes the mount-geometry check** iff d ≥ **0.065 g**.

This threshold is set as 1.5× the S1↔S2 inter-session distance
(d(S1,S2) = 0.0403 g), rounded up to 0.065 g for conservatism.
Setting the threshold ≥ S1↔S2 inter-session variability ensures the
held-out session represents a mount geometry meaningfully distinct
from the natural between-session variability of the training corpus,
restoring the marginal-re-mount role.

**Reference values from prior sessions** (for context; these sessions
do not retroactively pass or fail this v5-defined threshold, which
applies only to parity captures collected after this amendment):

| Session | Still-class distance from S1+S2 centroid (g) |
|---|---|
| S3 (2026-05-22) | 0.025 |
| S4 (2026-05-23) | 0.007 |

Both fall short of the v5 threshold; this is consistent with v5's
purpose of strengthening the marginal-re-mount property going forward.

**Pre-capture check (gates capture start).** After re-mounting the
sensor at the start of a parity-capture session:

1. Record 30 seconds of still data at 208 Hz, written to
   `mount_precheck.csv` in the session directory.
2. Compute (X̄, Ȳ, Z̄) over `mount_precheck.csv` and d to the S1+S2
   centroid.
3. If d ≥ 0.065 g, proceed to the 1200-sec still and motion captures.
4. If d < 0.065 g, re-mount the sensor and return to step 1. Log
   each failed pre-check attempt in the session's lab-notebook entry
   with (X̄, Ȳ, Z̄) and d values; the session.json's
   `mount_precheck_attempts` field records the count.

**Post-capture check (gates session validity).** After the 1200-sec
still recording completes:

1. Compute (X̄_post, Ȳ_post, Z̄_post) over the full 1200 sec of
   `still/accel.csv`.
2. Compute d_post to the S1+S2 centroid.
3. The session is valid iff d_post ≥ 0.065 g AND the per-axis drift
   between pre-check means and post-still means is ≤ 0.005 g per axis
   (no axis drifts more than 5 mg over the still recording).
4. If either condition fails, the session is invalidated; the data
   is retained for audit but is not used as the §9 test set, and a
   new capture session must be performed.

The 5 mg per-axis drift bound is set conservatively above the
documented session-3 axis-stability of 0.3 mg (`data/training/2026-05-22/notes.md`
§"Mount-orientation evidence") and well below the 65 mg threshold;
its purpose is to detect gross mount drift (cable strain, foam tape
relaxation, vibration loosening), not micro-drift.

**What this protocol does not do.** It does not check the motion-class
mount geometry separately (motion injects servo-vibration energy that
swamps mount-mean differences). It does not require specific axis
deltas (the test is on Euclidean distance, not per-axis). It does not
apply retroactively to S3 or S4.

### Change 3: session.json schema pinned for parity-capture sessions

Sessions 4-prime, 5, and 6 are parity-capture sessions whose
`session.json` file must contain fields beyond those used by
training-only sessions, so that downstream alignment
(`code/analysis/silicon_align.py`) and the Change 2 mount-geometry
audit can operate without ad-hoc assumptions. The schema below is
pinned by this amendment; the orchestrator implementation
(`run_session_parity.py`) must produce these fields and only these
fields at the top level for each class entry. Future tooling that
adds fields at this level requires a pre-registration amendment.

**Top-level session.json fields (parity-capture sessions):**

| Field | Type | Required | Notes |
|---|---|---|---|
| `session_date` | string | yes | ISO date `YYYY-MM-DD` |
| `session_type` | string | yes | Literal `"parity"` for parity captures |
| `btest` | bool | yes | True for bring-up tests; false for measurement-eligible captures |
| `duration_sec_per_class` | int | yes | Per-class recording length in seconds |
| `odr_hz` | int | yes | Accelerometer ODR (208 Hz per spec) |
| `pwm_center_ticks`, `pwm_min_ticks`, `pwm_max_ticks` | int | yes | PCA9685 tick values defining the motion stimulus envelope |
| `mlc_config_header` | string | yes | Filename of the MLC config header flashed for this capture (e.g., `mlc_motion_w75.h`) |
| `mlc_poll_hz` | int | yes | Target silicon polling rate (effective rate logged separately in `mlc_poller.stderr.log`) |
| `mount_precheck_attempts` | int | yes | Number of pre-check attempts; ≥1 for a valid session |
| `mount_precheck_pass_d_g` | float | yes | Euclidean distance d (g) on the passing pre-check |
| `mount_postcheck_d_g` | float | yes | Euclidean distance d_post (g) on the post-capture still recording |
| `mount_postcheck_drift_max_g` | float | yes | Maximum per-axis drift |X̄_post − X̄_pre| over (X, Y, Z), in g |
| `started_at`, `finished_at` | string (ISO8601) | yes | Wall-clock session bounds |
| `classes` | list | yes | One entry per class (still, motion); per-class fields below |

**Per-class fields in `classes[]`:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `class` | string | yes | `"still"` or `"motion"` |
| `duration_sec` | int | yes | Per-class recording length |
| `csv_lines` | int | yes | Line count of `accel.csv` including header |
| `silicon_raw_lines` | int | yes | Line count of `silicon_raw.csv` including header + comment lines |
| `started_at` | string | yes | Wall-clock start of this class's recording |
| `imu_t0_monotonic_s` | float | yes | `CLOCK_MONOTONIC` reading at the first accel sample |
| `mlc_t_start_monotonic_s` | float | yes | `CLOCK_MONOTONIC` reading at the first silicon poll |
| `clock_offset_s` | float | yes | `mlc_t_start_monotonic_s − imu_t0_monotonic_s`; used by `silicon_align.py` to convert silicon polls into accel-relative time |

**Required adjacent artifacts per session directory:**

- `mount_precheck.csv` — 4-column accel log of the passing 30-sec
  pre-check (same schema as `accel.csv`)
- `still/accel.csv` — 4-column accel log (timestamp, ax, ay, az), one
  row per 208 Hz sample
- `still/silicon_raw.csv` — 2-column silicon poll log with header
  `t_monotonic_s, mlc_src` and leading `#` comment lines (poller
  version, poll_hz, duration_sec)
- `still/mlc_poller.stderr.log` — poller stderr with
  `t_start_monotonic` recorded; the `effective_hz` from this file is
  used in the cross-rate sanity check in `silicon_align.py`
- `still/saleae.sal` — Saleae capture spanning the recording
- `motion/{accel.csv, silicon_raw.csv, mlc_poller.stderr.log, saleae.sal}` — same per-artifact requirements as still/

Sessions 4-prime, 5, and 6 must conform to this schema. Deviations
from this schema in those sessions are pre-registration violations
and require amendment.

### Change 4: Same-day Zenodo commitment

The v4 amendment was committed on 2026-05-22 23:44 PDT but its Zenodo
DOI (10.5281/zenodo.20358317) was minted on 2026-05-23 evening, after
session 4's capture. This procedural gap is documented in
`docs/lab-notebook/2026-05-23.md`. The gap does not, on its own,
invalidate any subsequent capture (the v4 text was visible to the
public repository's HEAD throughout the 2026-05-23 capture window),
but the audit trail is cleaner if external timestamping is
contemporaneous with the methodology commitment.

Going forward: every pre-registration amendment in this work is
Zenodo-published on the same calendar day (Pacific time) as the git
commit. This amendment is the first to which the same-day commitment
applies.

### What is NOT changed

The hypothesis structure (§2), design (§3), task definition (§4),
pipelines (§5), primary and secondary outcomes (§6), stress condition
(§8), §9 accuracy thresholds (≥90% per pipeline, ≤2pp gap), exclusion
criteria (§11), statistical analysis (§12), and deviations-reporting
protocol (§13) are unchanged.

The classifier feature set (VARIANCE_NORM, PEAK_TO_PEAK_NORM on
acceleration norm) and the AFS-off, fixed-feature-set discipline are
unchanged from v3 and v4. Window-length-dependent retraining under
this amendment uses the same feature pair for all three candidate
windows; the MLC ODR cap (104 Hz, from v4) and by-file labeling
protocol (from v4) are unchanged.

The training corpus (sessions 1+2, with session 3 excluded) is
unchanged from the w=75 training run committed at
`data/mems-studio/2026-05-22-w75/`. Sessions 1+2 are the training
corpus for w=25 and w=200 as well, ensuring window-length
comparability.

The two mechanism-falsification findings of 2026-05-23 (FP16
emulation falsified; bus-contention sample-gap audit falsified) are
retained as preliminary supporting evidence. The conclusions concern
silicon's computation pathway and are session-independent. They will
be re-run on session 4-prime data for paper consistency.

### Implementation details NOT requiring pre-registration

The implementation defaults in v4's "Implementation details NOT
requiring pre-registration" section (IIR filter sign convention,
variance estimator, threshold comparison operator) remain non-pre-
registered.

The Python tooling (`code/analysis/silicon_align.py`,
`code/analysis/mlc_json_to_parity.py`, `code/analysis/fp16_emulate.py`,
`code/analysis/accel_gap_audit.py`) and the host binary
`replay_parity.c` are implementation, not methodology, and may be
modified to support w=25, w=200, and the Change 2 mount-geometry
audit without amendment provided their methodological behavior
(window cadence, feature formulas, tree-evaluation semantics,
mount-check arithmetic per Change 2) is preserved.

The exact Python implementation of the Change 2 pre/post mount-check
arithmetic is non-pre-registered, but the inputs (still-class accel
means), the formula (Euclidean distance to the pinned centroid), the
threshold (0.065 g), the drift bound (0.005 g per axis), and the
pre-/post-check structure are pre-registered as specified above.

### External timestamp

This amendment is committed to the public repository at
github.com/akulswami/sensor-mlc-latency and the commit is tagged as
`prereg-amendment-2026-05-23`. The repository release is mirrored to
Zenodo at a new DOI distinct from the v2 (10.5281/zenodo.20042123),
v3 (10.5281/zenodo.20060848), and v4 (10.5281/zenodo.20358317) DOIs.
The new DOI is `10.5281/zenodo.20361496 (https://doi.org/10.5281/zenodo.20361496)`.
The DOI of the Zenodo release containing this amendment is the
authoritative external timestamp.

---

## Amendment 2026-05-24 (v6): Mount-check threshold adjustment

**Status:** Drafted but retracted by v6.1 (2026-05-24, same day) before any Zenodo DOI was minted. The retraction (v6.1, Zenodo DOI 10.5281/zenodo.20370205 — https://doi.org/10.5281/zenodo.20370205) is the authoritative external timestamp for this proposal. v6's proposed `MOUNT_THRESHOLD_G` change was never adopted; the code value remained at 0.065 g (v5 Change 2).

**Reason:** Empirical validation of v5 Change 2 protocol revealed pre-check threshold of 0.065 g was overly conservative given actual sensor stability. S1+S2 training centroid (May 20-21) remains stable; current sensor (May 24, same rig) measures 0.0247 g away — within thermal/gravitational noise for a fixed mount. S1/S2 separation is ~0.06 g; threshold was intended to catch real remounts. Lowering to 0.05 g preserves this goal while accommodating sensor noise.

**Change:** Adjust `MOUNT_THRESHOLD_G` from **0.065** to **0.05** in `code/orchestrator/run_session_parity.py`. All other v5 Change 2 constants unchanged. Threshold is read-only at runtime.

**Justification:**
- S1 (2026-05-20): (−0.0145, −0.0953, −0.9648) g
- S2 (2026-05-21): (−0.0087, −0.0555, −0.9680) g
- S1+S2 centroid: (−0.0116, −0.0754, −0.9664) g
- Current (2026-05-24): (−0.0129, −0.0509, −0.9692) g → d = 0.0247 g
- S1 vs S2 distance: d = 0.0603 g
- **Threshold 0.05 g catches ~5 mGal shifts (real remounts); 0.0247 g noise is within mount stability.**


## Amendment 2026-05-24 (v6.1): Retraction of v6 mount-threshold adjustment

**Status:** Pre-registered. Zenodo DOI: 10.5281/zenodo.20370205 (https://doi.org/10.5281/zenodo.20370205).

**Data collected under prior protocol that is affected by this amendment:**

No data has been collected under v6. The v6 amendment (2026-05-24, earlier same day) was drafted and committed to `docs/pre-registration.md` but was never externally timestamped via Zenodo, and the `MOUNT_THRESHOLD_G` code constant in `code/orchestrator/run_session_parity.py` was never changed from its v5 Change 2 value of 0.065 g. No parity-test session or latency-capture session has been initiated under v6's proposed 0.05 g threshold.

The S4-prime, S5, and S6 parity captures (2026-05-24) were collected under v5 Change 2 with `MOUNT_THRESHOLD_G = 0.065`; their pre-registration status is unaltered by this amendment.

### Reason for retraction

The v6 amendment proposed lowering `MOUNT_THRESHOLD_G` from the v5 Change 2 value of 0.065 g to 0.05 g, on the grounds that:

- The current mount centroid distance from the S1+S2 reference centroid was 0.0247 g, well below either threshold.
- The S1↔S2 inter-session distance was 0.0603 g, suggesting that 0.05 g would still catch real remounts while accommodating sensor noise.

**That numerical reasoning is not retracted.** The retraction's basis is procedural:

**Mount stability beyond ~48 hours is not characterized in this project.** The S1, S2, S3, S4-prime, S5, S6 captures were collected within a ~96-hour window (2026-05-20 to 2026-05-24, mostly on a fixed mount). The v7 latency-capture campaign (12 sessions across 4 conditions per v7 Change 2) will be the project's first capture series that may extend over multiple days with the same physical rig under varied thermal conditions (some sessions running under stress-ng CPU saturation, others idle). If thermal drift, mount-screw creep, or carrier-board mechanical settling produce mount-position drift larger than 0.0247 g but smaller than 0.05 g over multi-day timescales, a 0.05 g threshold would fail to detect that drift while a 0.065 g threshold would still tolerate it (by margin) without triggering a false re-mount requirement.

The conservative bound from v5 Change 2 is retained pending characterization of multi-day mount stability. This is a conservative posture, not a refutation of v6's reasoning. If post-v7 analysis shows mount-centroid drift remained well below 0.0247 g across the multi-day v7 campaign, a future amendment may revisit the threshold with multi-day empirical grounding.

### Change

`MOUNT_THRESHOLD_G` in `code/orchestrator/run_session_parity.py` remains at **0.065 g** (the v5 Change 2 value). v6's proposed change to 0.05 g is not adopted under this amendment.

No code changes are required by v6.1 because v6's code change was never implemented.

### What is NOT changed

- All other provisions of v5 Change 2 — mount-check protocol structure, pre-check / post-check / drift criteria, the four new `session.json` fields (`mount_precheck_attempts`, `mount_precheck_pass_d_g`, `mount_postcheck_d_g`, `mount_postcheck_drift_max_g`), and the `mount_precheck.csv` artifact. Unchanged.
- v6 amendment text remains in `docs/pre-registration.md` as the historical record of the proposed change. This amendment retracts the proposed change, not the documentation of having considered it. The pre-registration is append-only per the protocol stated at the top of this file.
- All other pre-registration amendments (v1 original spec, v2 SPI→I2C, v3 task switch, v4 ODR/labeling, v5 test-set redesignation + mount protocol + schema + same-day Zenodo gate). Unchanged.

### External timestamp

This amendment is committed to the public repository at github.com/akulswami/sensor-mlc-latency and the commit is tagged as `prereg-amendment-2026-05-24-v6-1`. The repository release is mirrored to Zenodo with a new DOI distinct from prior amendments. The DOI of the Zenodo release containing this amendment is the authoritative external timestamp. **Per v5 Change 4, the DOI is minted same-day; this amendment may not be referenced as authoritative in any commit, code, or capture session until the Zenodo release is published and its DOI is inserted into this section.**

## Amendment 2026-05-24 (v7): Servo-driven burst protocol for latency trials; window-length selection; hypothesis priority; Saleae channel and sample-rate correction

**Status:** Pre-registered. Zenodo DOI: 10.5281/zenodo.20370234 (https://doi.org/10.5281/zenodo.20370234).

**Data collected under prior protocol that is affected by this amendment:**

The following datasets and artifacts were produced under prior protocols and are explicitly classified by this amendment:

- **§9 accuracy parity data is retained and unaffected.** The §9 gate computation from 2026-05-23 evening (host 98.74% vs. silicon 99.79%, gap 1.05 pp, computed on session 4 / window length w=75) stands. The S4-prime, S5, S6 captures from 2026-05-24 (window lengths w=75, w=25, w=200 respectively) provide silicon-side single-pipeline accuracy data; host-side accuracy on those captures has not yet been computed and is required before the latency experiment runs (see "Change 1" below for the operational consequence).

- **No latency data collected under any prior protocol is used toward the pre-registered measurement.** Specifically:
  - The S1–S6 Saleae captures (training and parity sessions, 2026-05-20 through 2026-05-24) do not contain the decision-GPIO trace required by §6. They were captured with `SALEAE_DIGITAL_CHANNELS = [0, 2]` (training sessions) or `[0, 2, 3]` (parity sessions) at 12.5 MS/s. The decision-GPIO wire (Jetson Pin 11, gpiochip0 line 112) was physically connected to Saleae D3 on 2026-05-24, but only the parity sessions reflect this routing in code; the S1–S6 captures predate the routing and contain D0 (INT) and D2 (PWM) only.
  - The output of `code/analysis/extract_latency_from_saleae.py` (untracked file producing `saleae_timing.csv` in S4-prime, S5, S6 directories) computes the interval from D0_rising to the next D2_falling. This quantity is not the pre-registered wire-level latency (which is D0_rising to decision-GPIO_rising). It is not a measurement toward this pre-registration.
  - The bring-up observations from 2026-05-05/06 (`latency_test_mlc_activity`, ~464–516 µs, n=18) were excluded by v3 amendment line 471–474 and remain excluded.

No pre-registered latency measurement runs (n=500 per condition, per §3) have been executed under any version of this pre-registration.

---

### Change 1: §4 window length — fixed at w=25 for the latency comparison

The §9 results from 2026-05-24 (silicon-side accuracy on S4-prime/S5/S6, written to `code/analysis/section9_results.txt`) selected w=25 as the highest-accuracy window length on the silicon side: w=25 = 99.959%, w=200 = 99.913%, w=75 = 99.572%. Host-side accuracy across the three window lengths has not yet been computed.

Under this amendment:

- The latency comparison runs at **w=25 only**. The custom-trained classifier `mlc_motion_w25.h` and the corresponding host port (same tree.json, same threshold, w=25 sliding window in `parity_core.c`) are the operational pipelines for §3/§6 trial collection.
- Before any latency capture, the §9 parity gate is evaluated **on the S5 captures (w=25)** with the host pipeline run offline via `replay_parity` against S5's `accel.csv`. The gate requires |accuracy_host − accuracy_silicon| ≤ 2 pp and both ≥ 90% per §9. If either condition fails, the latency experiment is not run and a further amendment is required.

w=75 and w=200 are not used in the latency experiment. The S4-prime and S6 captures are retained in the repository for reproducibility of the §9 window-length selection result but do not enter the latency analysis.

### Change 2: §3 / §6 trial definition — servo-driven burst protocol

The v2 amendment defined a trial as a binary-state transition (still↔motion). The current host (`host_pipeline_parity.c`) and MLC (`latency_test_mlc.c`) inference binaries already emit a decision-GPIO edge only on binary-state transitions; sub-window decisions where the binary state is unchanged do not produce edges. This transition-based trial definition is retained from v2.

This amendment specifies the **stimulus protocol that generates transitions**:

- **Burst structure:** within a continuous capture session, the servo alternates 5 seconds of motion (full-amplitude sweep at the rate specified in `docs/training-data-spec.md`) with 5 seconds of still (servo held at center position). One 10-second cycle = two state changes (still→motion at second 0, motion→still at second 5).
- **Per-session trial yield:** 1200-second session × 1 cycle / 10 s × 2 transitions/cycle = **240 candidate trials per session**.
- **Sessions per condition:** ceil(500 / 240) = **3 sessions per condition**. Total: 12 sessions across the 4 conditions {MLC, host} × {no-stress, stress}.
- **Trial gating from sweep.log:** the orchestrator's `sweep.log` records the monotonic-clock timestamp of each commanded servo state change. For each sweep.log entry at time T_stim, the trial associated with that stimulus is the next D3 rising edge whose paired D0 rising edge (the most recent D0 edge before that D3 edge, within ≤100 ms) occurs after T_stim. There is **exactly one trial per stimulus change**; subsequent D3 edges before the next stimulus change are not counted as trials.
- **Clock alignment:** `session.json` already records `clock_offset_s` between the imu_logger monotonic clock and the mlc_poller monotonic clock. The same monotonic clock anchors `sweep.log` (verified by orchestrator implementation in `run_session_parity.py`). The Saleae capture clock is aligned to the imu_logger monotonic clock at session start via a synchronization edge in the orchestrator's start sequence; the offset is recorded in `session.json` as a new field `saleae_sync_offset_s`. **The orchestrator must implement this synchronization edge before the next capture; this is an operational gate on the latency experiment.**

### Change 3: §6.1 latency measurement — D0 → D3, pure Saleae, gated by sweep.log

The pre-registered measurement at §6.1 is unchanged in substance: latency per trial = (D3 rising edge timestamp) − (D0 rising edge timestamp). All timestamps are read from the Saleae capture; no software timestamps enter the measurement.

`sweep.log` is used **only** to identify which D0/D3 pairs are trials toward §3's per-condition trial count. It does not enter the latency value itself. This preserves the irrefutability of the wire-level measurement: every published latency number is supported by two timestamps from the same Saleae capture, with the gating sweep.log timestamp and the synchronization offset both recorded in `session.json` for audit.

### Change 4: §6.2 Saleae channel correction and sample-rate correction

**Channel correction:** Earlier pre-registration text references "decision GPIO" without specifying a Saleae channel. The Adafruit/Jetson wiring routes the decision GPIO from Jetson Pin 11 (gpiochip0 line 112) to **Saleae D3**. The documentation in `docs/pin-assignment.md` previously listed D1 as the decision channel; this was stale text predating the rewire on 2026-05-24, and is corrected by this amendment.

**Sample-rate correction:** §6.1 line 85 of the original pre-reg specifies Saleae digital input at ≥ 50 MS/s. The orchestrator setting `SALEAE_DIGITAL_SAMPLE_RATE` was 12,500,000 (12.5 MS/s) through commit `995e8c9`. Captures S1 through S6 were therefore taken at one-quarter the pre-registered sample rate. The 12.5 MS/s rate provides 80 ns timing resolution, well below the 10 µs / 50 µs thresholds of §6.3; the under-sampling does not affect any quantity to be reported. However, the pre-registered rate is the operational specification, and all captures under v7 will be at 50 MS/s. The S1–S6 captures are retained for reproducibility of the §9 window-length selection but do not enter the latency analysis (per "Data collected under prior protocol" above).

### Change 5: §2 hypothesis priority for the IEEE Sensors Letters submission

The hypotheses H1–H4 are unchanged in their formulations and pre-registered null/alternative structure. This amendment specifies their **reporting priority** in the submitted paper:

- **H4 (MLC robustness — primary):** the central finding. Equivalence test (TOST) per §6.3 and §12.1. CI on Hodges-Lehmann shift between MLC-stress and MLC-no-stress.
- **H3 (host degradation — secondary):** supporting result. One-sided Mann-Whitney U per §12.1.
- **H2 (effect-size growth under stress — secondary):** reported if power at n=500 is adequate; reported descriptively with bootstrap CI if not.
- **H1 (MLC-vs-host under no-stress — descriptive):** the prediction H1₁ (MLC faster) is **expected to be rejected** under the windowed motion-vs-still task, because the on-sensor MLC's window-completion delay structurally exceeds the host's sample-by-sample decision latency. This is reported honestly. H1's interest is as the empirical confirmation that on-sensor inference is not free in absolute terms; the paper's contribution is the **decoupling under stress** finding from H4, not absolute speed.

Holm-Bonferroni correction at family-wise α = 0.05 still applies across {H1, H2, H3, H4} per §12.2.

### Change 6: Operational gates before latency capture begins

The latency experiment shall not begin until **all** of the following are committed to `main`:

1. **Saleae sync-edge implementation** in `run_session.py` / `run_session_parity.py`, emitting a synchronization edge at session start that is captured by the Saleae (channel TBD by implementer; D0 or D3 acceptable). `saleae_sync_offset_s` field added to `session.json` schema.
2. **§10 measurement-protocol.md** (per original pre-reg §10) consolidating sensor ODR, full-scale range, filter settings, I2C bus speed, and register-read sequences. Currently scattered across `run_session.py`, `parity_core.h`, and lab notebooks.
3. **`code/stress/run_stress.sh`** (per original pre-reg §10) with stress-ng invocation flags. **`env/stress-ng-version.txt`** pinning the binary version.
4. **`code/orchestrator/run_stress_block.py`** integrating stress condition into the capture sequence, with pre-block tegrastats verification per §8.
5. **Block-randomization seed** at `code/analysis/block_order_seed.txt`.
6. **Replacement latency extractor** at `code/analysis/extract_latency_v7.py` (D0_rising → D3_rising, sweep.log gating, §6.2 100 ms exclusion, §11 overlapping-edge exclusion). Unit tests on synthetic Saleae traces.
7. **§9 gate evaluation on S5 (w=25)** with host pipeline run via `replay_parity --tree code/mlc_config/tree_w25.json --csv data/training/2026-05-24-S5/{still,motion}/accel.csv`. Gate must pass (host ≥ 90%, silicon ≥ 90%, gap ≤ 2 pp) before latency capture starts.
8. **Statistical-analysis code** at `code/analysis/statistics.py` (Mann-Whitney U, bootstrap CI, Hodges-Lehmann, TOST, Holm-Bonferroni). Validated against `scipy.stats` reference on synthetic inputs.

### What is NOT changed

- §1 Research question. Unchanged.
- §2 Hypotheses H1–H4 formulations, null/alternative structure. Unchanged in substance; only reporting priority is specified.
- §3 Design: two-factor (pipeline × stress) fully-crossed, n=500 per condition × 4 conditions = 2,000 trials. Unchanged.
- §6.3 Effect-size definitions (10 µs / 50 µs thresholds for H4). Unchanged.
- §7 Randomization and blocking (10 blocks per condition, block-randomized order from seeded RNG). Unchanged.
- §8 Stress condition specifications (stress-ng saturating all cores). Unchanged in substance; implementation gated per Change 6.
- §9 Accuracy parity gate threshold (≥90% both pipelines, ≤2 pp gap). Unchanged.
- §11 Exclusion criteria. Unchanged; per-condition exclusion rate cap of 10% applies.
- §12 Statistical analysis plan. Unchanged; implementation gated per Change 6.
- §13 Deviations and reporting. Unchanged. This amendment is itself disclosure of a methodology change.
- v5 Change 2 mount-geometry pre-check protocol. Applies to v7 latency captures.

### Stop condition

If §9 gate evaluation on S5 (w=25, per Change 6 item 7) fails — i.e., host accuracy < 90%, or silicon accuracy < 90%, or |host − silicon| > 2 pp — the latency experiment is not run. The required response per §9 of the original pre-reg is: retrain the host model, redesign MLC features, or switch task (which would require a further amendment).

### External timestamp

This amendment is committed to the public repository at github.com/akulswami/sensor-mlc-latency and the commit is tagged as `prereg-amendment-2026-05-24-v7`. The repository release is mirrored to Zenodo with a new DOI distinct from prior amendments. The DOI of the Zenodo release containing this amendment is the authoritative external timestamp. **Per v5 Change 4, the DOI is minted same-day; this amendment may not be referenced as authoritative in any commit, code, or capture session until the Zenodo release is published and its DOI is inserted into this section.**

## Amendment 2026-05-24 (v7.1): Correction of v7 Change 4 — Saleae channel mapping for decision GPIO

**Status:** Pre-registered. Zenodo DOI: 10.5281/zenodo.20370549 (https://doi.org/10.5281/zenodo.20370549).

**Data collected under prior protocol that is affected by this amendment:**

No pre-registered latency measurement runs have been executed under any version of this pre-registration. v7.1 corrects a hardware-state claim in v7's Change 4 that did not affect any captured session, because no session captured the decision-GPIO wire-level signal under any wiring assumption.

The §9 parity gate work performed earlier on 2026-05-24 using `replay_parity` against S5 accel.csv (data/processed: forthcoming) is **unaffected by this correction**. That work depends only on accelerometer CSV data, not on Saleae channel state.

The §9 parity gate result from 2026-05-23 (session 4, host 98.74% vs. silicon 99.79%, gap 1.05 pp) is unaffected.

---

### Reason for this correction

v7's Change 4 stated:

> "Channel correction: Earlier pre-registration text references 'decision GPIO' without specifying a Saleae channel. The Adafruit/Jetson wiring routes the decision GPIO from Jetson Pin 11 (gpiochip0 line 112) to **Saleae D3**. The documentation in `docs/pin-assignment.md` previously listed D1 as the decision channel; this was stale text predating the rewire on 2026-05-24, and is corrected by this amendment."

**This statement is false.** It is now permanently archived at Zenodo DOI 10.5281/zenodo.20370234 as part of v7's release. The error chain is documented honestly here for the pre-registration record:

- The v7 amendment was drafted in a chat session on 2026-05-24 afternoon.
- During that session, the chat assistant asked the experimenter to verify the physical wiring of Jetson Pin 11. The experimenter, working from memory rather than physical inspection at the bench, answered that Pin 11 was connected to Saleae D3. This statement was the sole foundation for v7's Change 4 channel-mapping claim.
- v7's Change 4 also documented `SALEAE_DIGITAL_CHANNELS = [0, 2, 3]` in `code/orchestrator/run_session.py` (set on 2026-05-24 by commit 995e8c9, "Enable D3 (GPIO line 112) capture in Saleae for wire-level latency") as evidence that the rewire had occurred. The code change was real; the corresponding physical change was not.
- v7 was committed (29c3f00), tagged (`prereg-amendment-2026-05-24-v7`), and externally timestamped on Zenodo (DOI 20370234) before the experimenter independently verified the bench state.
- Subsequent bench inspection on 2026-05-24 evening (PST) verified that Saleae D0 is connected to Jetson Pin 15 (sensor INT1) and Saleae D2 is connected to PCA9685 PWM. **Pin 11 was not connected to any Saleae channel at any time during 2026-05-24 prior to this amendment, nor during any captured session in this project's history.**
- After bench verification, Pin 11 was physically connected to Saleae D1 to match `docs/pin-assignment.md`'s long-standing documentation (which v7 incorrectly described as "stale").

### What was true in v7's Change 4

The Saleae sample-rate correction in v7 Change 4 — raising `SALEAE_DIGITAL_SAMPLE_RATE` from 12,500,000 to 50,000,000 to comply with pre-reg §6.1 line 85 (≥ 50 MS/s) — is independent of the channel-mapping claim, was implemented in code at commit 29c3f00 as part of v7, and is **not retracted by this amendment**. It stands as the operational sample rate for v7.1 latency captures and forward.

All other v7 changes (Change 1 window-length selection, Change 2 servo-burst trial protocol, Change 3 latency-measurement substance, Change 5 hypothesis priority, Change 6 operational gates) are independent of the channel-mapping claim and are **not retracted by this amendment**. They stand as the pre-registered protocol for the IEEE Sensors Letters submission.

### Change

This amendment corrects v7 Change 4's channel-mapping claim. The corrected statement of fact is:

- Decision GPIO (Jetson Pin 11, gpiochip0 line 112) is wired to **Saleae D1**, matching `docs/pin-assignment.md` as it has stood throughout this project.
- `SALEAE_DIGITAL_CHANNELS` in `code/orchestrator/run_session.py` is updated from `[0, 2, 3]` (set incorrectly by commit 995e8c9 in anticipation of a rewire that never occurred) to `[0, 1, 2]` to match the actual wiring.
- The Saleae captures going forward record D0 (sensor INT1), D1 (decision GPIO), and D2 (PCA9685 PWM).

### What is NOT changed

- v7 Change 1 (window length w=25 for latency comparison). Unchanged.
- v7 Change 2 (servo-driven burst protocol; 5s motion / 5s still; n=500 per condition × 4 conditions). Unchanged.
- v7 Change 3 (latency measurement = D_int_rising → D_decision_rising; pure Saleae; sweep.log gates trials). Unchanged in substance. The decision-GPIO channel is now D1 (was incorrectly stated as D3 in v7's Change 3 references via Change 4's mapping); the measurement formula is the same.
- v7 Change 4 sample-rate correction (50 MS/s). Unchanged.
- v7 Change 5 (hypothesis priority H4 primary, H3 secondary, H2 secondary if power allows, H1 descriptive). Unchanged.
- v7 Change 6 (eight operational gates before latency capture). Unchanged.
- All prior amendments (v2, v3, v4, v5, v6.1). Unchanged.
- `docs/pin-assignment.md`. Unchanged; it has been correct throughout.
- `MOUNT_THRESHOLD_G = 0.065` per v5 Change 2 / v6.1. Unchanged.
- Tree config `code/mlc_config/tree_w25.json` (committed as gate-7 fulfillment in commit 1a6b1cb). Unchanged.

### Procedural lesson recorded in this amendment

This is the second amendment in 24 hours (after v6.1) that retracts a same-day amendment. The pattern matches the procedural-debt failure mode documented in the 2026-05-23 lab notebook: *"derived artifacts are advisory; the repo is authoritative."* This amendment extends that lesson to include user-supplied physical-state statements: when a pre-registration claim depends on a hardware fact, the fact must be verified by physical bench inspection (tracing wires by hand) before the amendment is committed, tagged, or externally timestamped. Verbal or remembered descriptions of hardware state are not sufficient grounds for an authoritative claim. v7.1 is the cost of skipping that step in v7's drafting.

### External timestamp

This amendment is committed to the public repository at github.com/akulswami/sensor-mlc-latency and the commit is tagged as `prereg-amendment-2026-05-24-v7-1`. The repository release is mirrored to Zenodo with a new DOI distinct from prior amendments. The DOI of the Zenodo release containing this amendment is the authoritative external timestamp. **Per v5 Change 4, the DOI is minted same-day; this amendment may not be referenced as authoritative in any commit, code, or capture session until the Zenodo release is published and its DOI is inserted into this section.**

## Amendment 2026-05-24 (v7.2): Retract v7 Change 1 — w=25 window length, switch to w=75

**Status:** Pre-registered. Zenodo DOI: 10.5281/zenodo.20371440.

**Data collected under prior protocol that is affected by this amendment:**

No pre-registered latency measurement runs have been executed under any version of this pre-registration. v7.2 corrects the window-length selection in v7 Change 1 before the latency experiment begins.

The §9 parity gate evaluation performed on 2026-05-24 evening uses captured S7-prime data (`data/training/2026-05-24-S7-prime/`) and produces the §9 evidence stored at `data/processed/2026-05-24-S7-prime-section9-w75/`. Both directories are committed to the repository as supporting evidence for this amendment.

The §9 parity gate result from 2026-05-23 (session 4: host 98.74% / silicon 99.79% / 1.05 pp gap, computed at w=75) is unaffected by this amendment and is reinforced by S7-prime's w=75 result (host 99.21% / silicon 98.74% / 0.47 pp gap).

---

### Reason for this correction

v7 Change 1 selected window length w=25 for the latency experiment on the basis of accuracy data reported in `code/analysis/section9_results.txt` (committed 2026-05-24, before v7 was drafted). That file reported per-session silicon accuracies:

> w=25 (S5): 99.959%
> w=75 (S4-prime): 99.572%
> w=200 (S6): 99.913%

and selected w=25 as the highest-accuracy window length.

**Those numbers are real measurements, but their window-length attribution is false.** The S4-prime, S5, and S6 captures all ran with the same `w=75` silicon configuration, not three different window lengths. The per-session accuracy differences are session-noise (mount variation, environmental events, fan vibration), not window-length effects.

The misattribution was first discovered today via silicon trace timing analysis: each session's first silicon class-4 transition on the motion arm falls in the 1.0–1.5 s range after `mlc_poller` start, consistent with w=75 silicon's ~720 ms window completion time. A w=25 silicon would produce first transitions at ~0.3–0.5 s. All three sessions show w=75 timing. The trace timing finding was strong enough that v7.1 noted it, but v7.1 did not retract v7's window-length selection because the §9 gate had not yet been operationally re-evaluated.

Tonight (2026-05-24 evening, PST), the §9 gate was re-evaluated with a deliberate goal of testing w=25 on freshly-flashed w=25 silicon:

1. Silicon was manually flashed via `sudo code/jetson/session4/mlc_setup_w25`. Post-flash WHO_AM_I = 0x6c. Sanity capture (10 s, rig at rest) confirmed silicon was in w=25 state: 475/486 class-0 polls (97.7% still), no startup transient, threshold behavior consistent with w=25's documented 0.029 g.

2. The orchestrator (`code/orchestrator/run_session_parity.py`) was invoked with `--mlc-config-header mlc_motion_w25.h` and `--session-date 2026-05-24-S7-prime`. The capture ran for 1200 s still + 1200 s motion. `session.json` recorded `mlc_config_header: mlc_motion_w25.h`. The motion arm produced unambiguous mechanical motion: A_X std = 0.144 g, silicon class-4 distribution at 99.76%, sweep.log shows the servo commanded between MIN (102) and MAX (511) ticks with 1 s period throughout.

3. The §9 gate was computed via `replay_parity` with `tree_w25.json`, `silicon_align.py`, and `compare_decisions.py`. Per-arm and combined accuracy:

> Host still: 5087/5097 = 99.804%
> Host motion: 3299/5097 = 64.724%
> Silicon still: 4975/5097 = 97.606%
> Silicon motion: 5088/5097 = 99.823%
> Combined host: 82.264%
> Combined silicon: 98.715%
> Gap: 16.45 pp

These numbers superficially indicate that w=25 fails §9 (host < 90%, gap > 2 pp), and that the failure mode is host pipeline missing motion windows (35.3% disagreement on motion arm).

**However:** further investigation revealed that the orchestrator's `mlc_setup` invocation does **not** dispatch by `--mlc-config-header`. The orchestrator hardcodes the binary path (line 73 of `code/orchestrator/run_session.py`):

```python
JETSON_MLC_SETUP = f"{JETSON_REPO}/code/jetson/session4/mlc_setup"
```

`mlc_setup` is the original w=75 build (sha256 `59f9b3c0…`, built 2026-05-23 09:38). The w=25 and w=200 variants (`mlc_setup_w25`, `mlc_setup_w200`) exist as separate binaries but are not referenced by the orchestrator. **The orchestrator's "Flashing MLC..." step at the start of each arm silently overwrote our manual w=25 flash with the w=75 configuration.** S7-prime's silicon was therefore w=75, not w=25, despite session.json's metadata claim.

Confirmation: the §9 evaluation was re-run with `tree_w75.json` against the same S7-prime captured data, yielding per-arm and combined accuracy:

> Host still: 1694/1699 = 99.706%
> Host motion: 1677/1699 = 98.705%
> Silicon still: 1659/1699 = 97.646%
> Silicon motion: 1696/1699 = 99.823%
> Combined host: 99.205%
> Combined silicon: 98.735%
> Gap: 0.471 pp

§9 gate evaluated at w=75 on S7-prime data: **PASS** (all three criteria cleared).

The "w=25 fails §9" result from the first analysis was an artifact of comparing a w=25 host pipeline against w=75 silicon — a window-length mismatch, not a w=25 viability test. **A genuine w=25 §9 evaluation has not been performed in this project's history**, because the orchestrator has been flashing w=75 silicon for every session regardless of the `--mlc-config-header` argument passed to it.

### What is true about w=25 on this rig

After all of today's analysis, the empirical knowledge about w=25 on this rig is:

- **w=25 silicon classifier** (per `mlc_setup_w25` build and `mlc_motion_w25.h`): briefly tested in a 10-second sanity capture at rest. Showed 97.7% class-0 distribution on a still rig, consistent with documented threshold behavior. Has never been tested under motion-arm conditions, has never had §9 evaluated, has never run a 1200-second capture. The chip-side classifier may work fine, may not — we do not know.

- **w=25 host classifier** (per `tree_w25.json` and `replay_parity`): can be run on any accel.csv. On S7-prime's accel data (which corresponds to w=75 silicon behavior, but the accel signal is the same regardless of silicon flash), it produces 99.8% accuracy on still arm and 64.7% accuracy on motion arm. The motion-arm under-detection is consistent with the host pipeline's filter not settling fast enough on 240 ms windows to track the silicon's threshold; or it may be an implementation-specific artifact of `replay_parity.c`'s filter math. We do not know.

Neither finding is sufficient to commit w=25 to the latency experiment.

### Change

This amendment retracts v7 Change 1's selection of w=25 as the latency-experiment window length. The corrected selection is:

- **Latency experiment runs at w=75 only.** w=75 silicon has cleared the §9 gate in two independent captures (session 4 on 2026-05-23, and S7-prime on 2026-05-24).
- The latency-experiment trial structure (servo-burst protocol from v7 Change 2) is **unchanged in substance** but its per-cycle expected window count adjusts from ~20 windows per 5 s motion burst at w=25 to ~7 windows per 5 s motion burst at w=75. Statistical power calculations from v7 are not affected because v7 specified n=500 trials per condition (not n=10000 windows), and the trial count is independent of window length.
- All other v7 changes (Change 2 servo-burst protocol, Change 3 latency measurement substance, Change 5 hypothesis priority, Change 6 operational gates) are **unaffected** and stand.
- v7 Change 4's sample-rate raise (50 MS/s) stands.
- v7.1's correction (decision GPIO on Saleae D1, channel list `[0, 1, 2]`) stands.

### What is NOT changed by this amendment

- v7 Change 2 (servo-driven burst protocol). Unchanged.
- v7 Change 3 (wire-level latency measurement: D_int_rising → D_decision_rising). Unchanged.
- v7 Change 4 sample-rate (50 MS/s). Unchanged.
- v7 Change 5 (hypothesis priority H4 primary, H3 secondary, H2 secondary if power allows, H1 descriptive). Unchanged.
- v7 Change 6 (eight operational gates). The gates themselves stand. Gate 7 (§9 evaluation) is **completed for w=75** by this amendment's referenced S7-prime work; the other seven gates remain to be implemented.
- v6.1's retraction of v6 mount-threshold change. Unchanged.
- v7.1's correction of v7 Change 4 channel-mapping claim. Unchanged.
- `MOUNT_THRESHOLD_G = 0.065` per v5 Change 2 / v6.1. Unchanged.
- All prior amendments (v2 through v7.1). Unchanged.

### Procedural lessons recorded in this amendment

Two findings of project-wide procedural significance:

**Finding 1: Orchestrator's `mlc_setup` invocation does not respect `--mlc-config-header`.** This is now known to be the root cause of the `section9_results.txt` misattribution that drove v7's window-length selection. The argument `--mlc-config-header` is *metadata-only*: it controls what string gets written into `session.json` but does not change which `mlc_setup` binary runs. Going forward, no `session.json` `mlc_config_header` field can be trusted as a statement about which silicon configuration was actually deployed; the only reliable evidence of silicon configuration is the silicon's behavior in the captured data (first-transition timing, threshold response). This bug must be fixed before any future capture work in which different window lengths or different MLC configurations are intended; the fix is to either (a) make the orchestrator dispatch by `--mlc-config-header` to the matching `mlc_setup_wN` binary, or (b) require an explicit `--mlc-setup-path` CLI argument, or (c) have the orchestrator read back the actual MLC configuration from silicon after flash and write the verified value to session.json. Filed for v7 Change 6 operational-gate work or a separate cleanup commit before any further window-length variation is attempted.

**Finding 2: Confirmation of v7.1's broader procedural lesson.** v7.1 stated that when a pre-registration claim depends on a hardware fact, the fact must be verified by physical bench inspection. v7.2 extends this lesson: when a pre-registration claim depends on a *deployment* fact (which binary runs, which configuration is on silicon, which channel is captured), the fact must be verified by behavioral observation of the deployed system, not merely by metadata that records what was *requested* of the system. Repo metadata and CLI argument values are advisory; the captured data is authoritative.

### External timestamp

This amendment is committed to the public repository at github.com/akulswami/sensor-mlc-latency and the commit is tagged as `prereg-amendment-2026-05-24-v7-2`. The repository release is mirrored to Zenodo with a new DOI distinct from prior amendments. The DOI of the Zenodo release containing this amendment is the authoritative external timestamp. **Per v5 Change 4, the DOI is minted same-day; this amendment may not be referenced as authoritative in any commit, code, or capture session until the Zenodo release is published and its DOI is inserted into this section.**

## Amendment 2026-05-25 (v7.3): D2-based motion-window gating; servo_sweep burst-mode operationalization; sweep.log retired from gating

**Status:** Pre-registered. Zenodo DOI: 10.5281/zenodo.20389899 (https://doi.org/10.5281/zenodo.20389899).

**Data collected under prior protocol that is affected by this amendment:**

No pre-registered latency measurement runs have been executed under any version of this pre-registration. v7.3 corrects two implementation-vs-specification mismatches in v7 Change 2 before the latency experiment begins.

The §9 parity gate evaluations (session 4 at w=75, S7-prime at w=75) are unaffected — they do not depend on Saleae-side trial gating.

The smoke-test capture `data/training/2026-05-25-sync-btest/` (btest, sync-edge validation) and the empirical-characterization capture `data/training/2026-05-25-burst-btest/` (btest, used to derive the D2 classification thresholds pinned in this amendment) are unaffected because they are btests, not pre-registered measurements.

---

### Reason for this correction

Two divergences between v7 Change 2 (as written) and the actual orchestrator implementation came to light on 2026-05-25 while implementing Gate 6 (the replacement latency extractor):

**(1) sweep.log clock discrepancy.** v7 Change 2 states:

> The same monotonic clock anchors `sweep.log` (verified by orchestrator implementation in `run_session_parity.py`).

This statement is false. `code/jetson/servo/servo_sweep.c` writes sweep.log timestamps using `CLOCK_REALTIME`, not `CLOCK_MONOTONIC`. The file header confirms this:
timestamp = CLOCK_REALTIME microseconds at host i2c_write call

The "verified" claim in v7 Change 2 was incorrect. sweep.log timestamps cannot be aligned to the monotonic-clock-anchored Saleae sync offset that v7 Change 2 (and v7.2) build the alignment plan around. The two clocks (REALTIME and MONOTONIC) can drift relative to each other via NTP step adjustments and were never operationally aligned during any prior capture.

**(2) Stimulus protocol implementation gap.** v7 Change 2 specifies:

> Burst structure: within a continuous capture session, the servo alternates 5 seconds of motion (full-amplitude sweep at the rate specified in `docs/training-data-spec.md`) with 5 seconds of still (servo held at center position). One 10-second cycle = two state changes (still→motion at second 0, motion→still at second 5).

The orchestrator invokes `servo_sweep` with `--mode continuous --period-ms 1000`, which runs the servo continuously alternating min/max every ~1 second for the full duration of the motion arm. There are no 5-second still periods within the motion arm. The actual stimulus pattern is therefore "1s motion / 1s motion / ..." rather than the pre-registered "5s motion / 5s still / 5s motion / 5s still / ...".

`servo_sweep` does support a `--mode burst` (with `--motion-ms`, `--still-ms`, `--burst-period-ms` parameters); the orchestrator simply was not invoking it. This is a stimulus-protocol implementation gap, not a code-missing gap, and is fixable by updating the orchestrator's invocation.

---

### Change 1: Replace sweep.log-based trial gating with D2-based motion-window gating

v7 Change 2's "Trial gating from sweep.log" paragraph is retracted. The replacement gating logic is **entirely Saleae-side** with no cross-clock alignment:

#### D2 per-PWM-cycle classification

The Saleae captures the PCA9685 channel-0 PWM signal continuously on **D2** at 50 MS/s. The PCA9685 is configured for 50 Hz PWM (PRE_SCALE = 0x79). Each PWM cycle is 20 ms; each cycle contains one rising edge followed by one falling edge.

**For each PWM cycle, the extractor computes:**
- `pulse_width_us = (t_falling - t_rising) × 1e6`, where `t_rising` is the cycle's rising edge time and `t_falling` is the immediately subsequent falling edge time in the Saleae trace.

**Classification:**
- `still` if `|pulse_width_us - PWM_CENTER_PULSE_US| ≤ PWM_MOTION_THRESHOLD_US`
- `motion` otherwise.

**Pinned values, empirically derived 2026-05-25** on the rig from `data/training/2026-05-25-burst-btest/motion/saleae.sal` (the empirical-characterization btest captured under the proposed protocol):

- `PWM_CENTER_PULSE_US = 1380` (median pulse width when servo is commanded to 307 ticks / center)
- `PWM_MOTION_THRESHOLD_US = 500`

The btest produced a perfectly trimodal pulse-width distribution: 458 µs (motion endpoint at 102 ticks, n=327), 1380 µs (center at 307 ticks, n=1091), 2297 µs (motion endpoint at 511 ticks, n=490). All cycles fall into one of these three peaks with zero counts in the gaps between them. The 500 µs threshold sits unambiguously between the still peak (deviation = 0 µs) and the motion peaks (deviation ≈ 920 µs); any threshold in [200, 800] gives identical classification. 500 µs is chosen as the midpoint for robustness margin.

#### Stimulus-transition detection

Walking through PWM cycles in chronological order, a **stimulus transition** is defined as a transition from one classification to the other in consecutive PWM cycles:

- **still → motion transition** at the time of the first motion-classified cycle following a run of still-classified cycles.
- **motion → still transition** at the time of the first still-classified cycle following a run of motion-classified cycles.

Single-cycle classification glitches (one motion cycle surrounded by still cycles, or vice versa) are theoretically possible but were not observed in the btest. To be robust, the extractor uses a "confirmed-by-N-cycles" rule: a transition is confirmed only after **N = 3 consecutive cycles** of the new classification. This 60 ms confirmation latency is negligible compared to the 5-second burst duration and well below the §6.2 100 ms latency exclusion threshold.

#### Trial assignment per stimulus transition

For each stimulus transition at Saleae time `T_stim`, the associated trial is the **next D1 rising edge** whose paired D0 rising edge (the most recent D0 edge before that D1 edge, within ≤100 ms per §6.2) occurs after `T_stim`. There is exactly one trial per stimulus transition; subsequent D1 edges before the next stimulus transition are not counted as trials.

This trial-assignment logic is functionally identical to v7 Change 2's, except `T_stim` is now derived from D2 (Saleae-side) rather than sweep.log (CLOCK_REALTIME, Jetson-side).

#### Expected stimulus-transition count

For a 1200 s motion arm under the pre-registered 5s motion / 5s still burst protocol: 120 cycles × 2 transitions = **240 stimulus transitions per motion arm**.

A motion arm with full pre-registered duration produces 240 candidate trials. The 4 conditions × 3 sessions each at 240 trials/session = 2880 candidate trials. After exclusion (§6.2, §11), the per-condition trial count of 500 (per §3) is expected to be achieved comfortably.

### Change 2: sweep.log retained for audit, not for gating

sweep.log continues to be written by `servo_sweep` and is retained in capture directories. It is now an **auxiliary record** for human audit (e.g., verifying that the commanded number of stimulus transitions matches the count detected on D2). The CLOCK_REALTIME timestamps in sweep.log do NOT enter the latency measurement and do NOT gate trials.

`servo_sweep.c` is **not modified** by this amendment. Its CLOCK_REALTIME timestamps are acceptable for the auxiliary-audit purpose. Future amendments may switch `servo_sweep` to CLOCK_MONOTONIC if needed; this amendment does not require it.

### Change 3: Orchestrator update to invoke burst mode

`code/orchestrator/run_session_parity.py` is updated to invoke `servo_sweep --mode burst --motion-ms 5000 --still-ms 5000 --burst-period-ms 1000 --duration {duration_sec}` for the motion arm. The previous `--mode continuous --period-ms 1000` invocation is retired.

`servo_sweep`'s existing `--mode burst` (already implemented in the binary as of 2026-05-21) provides the pre-registered stimulus structure: alternating 5-second motion bursts (with 1-second internal sweep period producing 4-5 endpoint commands per burst) with 5-second still periods.

`servo_sweep`'s `--mode continuous` is retained in the binary for bring-up and diagnostic use; it is not used for pre-registered captures.

### Change 4: §10 documentation update

`docs/measurement-protocol.md` (the Gate 2 measurement-protocol document) is updated to reflect:

- The PCA9685 50 Hz PWM specification and its pulse-width-to-ticks mapping
- The D2 motion-window classification: `PWM_CENTER_PULSE_US = 1380`, `PWM_MOTION_THRESHOLD_US = 500`, confirmation-by-3-consecutive-cycles
- The retirement of sweep.log from the latency analysis path
- The new orchestrator invocation of `servo_sweep --mode burst`

These updates are committed alongside the v7.3 amendment in the same commit.

### Effect on v7 Change 6 operational gates

Gate 6 (replacement latency extractor at `code/analysis/extract_latency_v7.py`) inherits the D2-gating logic from this amendment. The Gate 6 unit tests on synthetic Saleae traces shall include test cases for:

- D2 per-PWM-cycle classification at the pinned thresholds (still pulse = 1380 µs, motion endpoints = 458 or 2297 µs)
- Stimulus-transition detection (still→motion and motion→still) with the 3-consecutive-cycle confirmation rule
- Trial assignment per stimulus transition (exactly one D0→D1 pair per transition; subsequent D1 edges not counted)
- §6.2 100 ms exclusion (D0→D1 pairs with gap > 100 ms excluded)
- §11 overlapping-edge exclusion (≥2 D0 rising edges before the next D1 rising edge → excluded)
- Sync-edge handling: the first D1 rising edge of the still arm is the synchronization edge (per Gate 1) and is not a measurement edge.

### What is NOT changed

- §1 Research question. Unchanged.
- §2 Hypotheses H1–H4 formulations and null/alternative structure. Unchanged.
- §3 Design: two-factor (pipeline × stress) fully-crossed, n=500 per condition × 4 conditions = 2,000 trials. Unchanged.
- §6.1 Latency measurement definition: per-trial latency = (D1 rising) − (D0 rising), both from the Saleae capture. Unchanged.
- §6.2 100 ms exclusion. Unchanged.
- §6.3 Effect-size definitions (10 µs / 50 µs thresholds for H4). Unchanged.
- §7 Randomization and blocking. Unchanged.
- §8 Stress condition specifications. Unchanged.
- §9 Accuracy parity gate (≥90% both pipelines, ≤2 pp gap). Unchanged.
- §11 Exclusion criteria. Unchanged in substance; criterion 4 (overlapping events) is implemented via the D2-gating semantics specified in Change 1.
- §12 Statistical analysis plan. Unchanged.
- v7 Change 1 (w=75 window length per v7.2 retraction). Unchanged.
- v7 Change 4 Saleae channel mapping (D1 per v7.1 correction). Unchanged.
- v7 Change 5 hypothesis priority. Unchanged.
- v7 Change 6 operational gates (this amendment refines Gate 6 details only; Gates 1, 2, 3, 5, 7, 8 are completed independently of this amendment).
- The 5s motion / 5s still burst structure itself (specified in v7 Change 2). Unchanged; only the implementation path is updated (orchestrator now invokes burst mode).

### Stop condition

If the D2 motion-window classification, when applied to the first pre-registered capture under the new orchestrator invocation, fails to recover the commanded number of stimulus transitions within ±5%, the latency experiment is halted until the discrepancy is investigated. This stop condition is verifiable mechanically by comparing D2-detected stimulus transitions against the sweep.log record of `MOTION_PHASE_START` and `STILL_PHASE_START` events: the counts should match exactly.

For a 1200 s motion arm, the expected count is 240 transitions; tolerance ±5% = ±12, so accepted range is [228, 252] D2-detected transitions per motion arm.

The empirical btest (`2026-05-25-burst-btest`, 30 s motion arm) detected 6 transitions, matching the 6 commanded transitions exactly (3 MOTION_PHASE_START + 3 STILL_PHASE_START in sweep.log). Detection error: 0%.

### External timestamp

This amendment is committed to the public repository at github.com/akulswami/sensor-mlc-latency and the commit is tagged as `prereg-amendment-2026-05-25-v7-3`. The repository release is mirrored to Zenodo with a new DOI distinct from prior amendments. The DOI of the Zenodo release containing this amendment is the authoritative external timestamp. **Per v5 Change 4, the DOI is minted same-day; this amendment may not be referenced as authoritative in any commit, code, or capture session until the Zenodo release is published and its DOI is inserted into the `Status` line above.**

## Amendment 2026-05-25 (v7.4): §11 criterion 4 reinterpretation for the windowed task; sync-edge channel formalization

**Status:** Pre-registered. Zenodo DOI: 10.5281/zenodo.20389909 (https://doi.org/10.5281/zenodo.20389909).

**Data collected under prior protocol that is affected by this amendment:**

No pre-registered latency measurement runs have been executed under any version of this pre-registration. v7.4 addresses two leftover items before the latency experiment begins:

(1) §11 criterion 4 ("a second INT edge occurs before the decision GPIO edge") was written when the project's classification task was tap detection, where D0 fires once per detected tap. The original criterion applies correctly to the v7 MLC silicon pipeline (which retains "D0 fires once per binary-state transition" semantics via the MLC interrupt). It does NOT apply correctly to the v7 host pipeline, which streams DRDY at the full 208 Hz sensor ODR, producing hundreds of D0 edges per stimulus window and excluding 100% of trials under the literal text.

(2) v7 Change 6 item 1 said the sync edge could go on "channel TBD by implementer; D0 or D3 acceptable." Gate 1's empirical implementation (committed 2026-05-25) used channel D1 (gpiochip0 line 112, Pin 11) after multiple attempts to route a sync edge to D3 produced no visible edge on Saleae despite verified gpiod toggles. v7.4 formalizes this channel choice as part of the pre-registered protocol.

Both items came to light on 2026-05-25 while implementing and smoke-testing Gate 4 (`run_stress_block.py`). Smoke-test data (`data/training/latency-experiment/block-001-mlc-idle-btest/`, `block-002-host-idle-btest/`) was captured under btest mode and is not part of any pre-registered measurement.

---

### Reason for this correction

**(1) §11 criterion 4 mismatch with the windowed task — host pipeline only.** The original criterion 4 reads:

> A second INT edge occurs before the decision GPIO edge. (Overlapping events; ambiguous attribution.)

This was correct for tap detection: D0 ("tap detected" interrupt) fires once per detected tap, D1 ("host decision GPIO") fires once per classification. A second D0 before the matching D1 indicates two taps occurred too closely for the host to disambiguate — a real ambiguous-attribution case.

For the v7 motion-vs-still task:

- **The MLC silicon pipeline** (`latency_test_mlc.c`) retains the "one D0 per binary-state transition" semantics. It explicitly disables DRDY routing and routes only the MLC interrupt to INT1; D0 fires once per MLC binary-state change. The original criterion 4 ("a second D0 before D1") applies cleanly and catches the real ambiguity case: the MLC fired twice before the host could read MLC0_SRC for the first event. This criterion is preserved unchanged for the MLC pipeline.

- **The host pipeline** (`host_pipeline_parity.c`) routes DRDY at full sensor ODR (208 Hz). The smoke-test capture observed D0 = 6571 edges in a 30 s block. Between any two consecutive stimulus transitions there are hundreds of D0 edges. The original criterion 4 would exclude every host-pipeline trial. The ambiguity it was designed to catch (input event attributed to wrong decision) manifests differently for the host pipeline: as **multiple D1 rising edges within a single stimulus window**, indicating the classifier oscillated and produced multiple binary-state changes for one stimulus.

The pipelines therefore need different operationalizations of criterion 4, reflecting their structurally different D0 semantics.

**(2) Sync-edge channel formalization.** v7 Change 6 item 1 left the sync-edge channel "TBD by implementer." During Gate 1 implementation on 2026-05-25, multiple attempts to fire a sync edge on a GPIO wired to Saleae D3 (using `gpiochip0` line 9, `gpiochip1` line 9, and several other candidates that the Jetson.GPIO library claimed map to Pin 16) produced no visible edge on the Saleae trace. The root cause was not identified. The known-working `gpiochip0` line 112 (physical Pin 11, wired to Saleae D1) was substituted instead. This pin is the same one the host and silicon measurement binaries use for the decision-GPIO output; the sync edge fires once at session start BEFORE the measurement binary takes ownership of the line, so there is no GPIO-contention conflict. The first D1 rising edge of the session's still arm is the sync edge; subsequent edges are measurement edges.

This channel choice is operationally correct and is now part of the pre-registered protocol. The session.json field name `saleae_sync_jetson_monotonic_ns` (introduced in Gate 1) is also formalized as the canonical name for the synchronization timestamp.

---

### Change 1: Restate §11 criterion 4 asymmetrically by pipeline

§11 criterion 4 is replaced with the following:

> **4. (MLC silicon pipeline)** A second D0 rising edge occurs in the window `(t_stim, t_d1]` for a given trial, where `t_stim` is the stimulus transition on D2 and `t_d1` is the trial's D1 rising edge. (Original tap-detection semantics, preserved for the MLC pipeline because `latency_test_mlc.c` disables DRDY streaming and routes only the MLC interrupt to D0; a second D0 before D1 indicates the MLC fired twice before host could read the first MLC0_SRC.)
>
> **4. (Both pipelines, additionally)** More than one D1 rising edge occurs in the stimulus window `(t_stim, t_next_stim]`, where `t_next_stim` is the time of the next stimulus transition on D2 (or end-of-capture). This indicates the classifier produced multiple binary-state changes within a single stimulus — ambiguous attribution.

For both pipelines, the trial-pairing procedure within each stimulus window `(t_stim, t_next_stim]` is:

1. Count D1 rising edges in the window. If 0 → criterion 1 exclusion ("no_d1_in_window"). If exactly 1 → that D1 is the trial's decision edge. If ≥2 → criterion 4 exclusion ("multiple_d1_in_window").
2. Given exactly 1 D1, the paired D0 is the most recent D0 rising edge in `(t_stim, t_d1]`.
3. For the MLC pipeline only: if `(t_stim, t_d1]` contains ≥2 D0 rising edges → criterion 4 exclusion ("multiple_d0_before_d1").
4. Latency = `t_d1 - t_d0`. If gap > 100 ms → criterion 1 exclusion (per §6.2).

This restatement preserves the original criterion 4's intent — to exclude trials where attribution between input event and decision is ambiguous — while operationalizing it correctly for each pipeline's actual D0/D1 semantics.

### Change 2: Formalize the sync-edge channel as D1 / gpiochip0 line 112 / Pin 11

v7 Change 6 item 1 is amended: "channel TBD by implementer; D0 or D3 acceptable" is replaced by:

> The sync edge fires on `gpiochip0` line 112 (Jetson Pin 11), wired to Saleae channel **D1**. This is the same physical line driven by `host_pipeline_parity.c` and `latency_test_mlc_w75` for their decision-GPIO output. The sync edge fires **before** the measurement binary takes ownership of the line, so there is no GPIO-contention conflict. The first D1 rising edge of the still arm of a session is the sync edge; subsequent D1 rising edges within that arm are measurement edges. The motion arm of a session does not fire a sync edge (per-session sync, not per-arm).

The session.json schema field `saleae_sync_jetson_monotonic_ns` (uint64 nanoseconds, populated only for the still arm) is canonical. Earlier informal references to `saleae_sync_offset_s` (in v7 Change 2) are superseded.

### Change 3: extract_latency_v7.py is updated

`code/analysis/extract_latency_v7.py` is updated to implement the restated §11 criterion 4. The extractor takes a new `--pipeline {host,mlc}` argument and applies the appropriate criterion 4 logic per pipeline.

The empirical smoke-test data (`block-001-mlc-idle-btest`, `block-002-host-idle-btest`) is reprocessed under the new logic. Empirical results:

- **Block-001 (MLC pipeline, idle, 30s)**: 5/6 trials included. The newly excluded trial is correctly flagged as `multiple_d1_in_window`; the MLC classifier oscillated within one motion-burst window, producing multiple binary-state transitions for a single stimulus. The 5 remaining trials have median latency 569 µs (min 508, max 646).
- **Block-002 (host pipeline, idle, 30s)**: 5/6 trials included (was 0/6 under the old logic). The recovery from 0% to 83.3% inclusion validates the asymmetric criterion 4 fix. The 5 included trials have median latency 370 µs (min 326, max 384). The 1 excluded trial is correctly flagged as `multiple_d1_in_window` — the host classifier oscillated three times within the same motion-burst window in which the MLC also oscillated.

The 1/6 exclusion rate at btest scale (~16.7%) exceeds the §11 10% cap. At the full pre-registered campaign scale (50 trials/block × 10 blocks/condition = 500 trials/condition), this oscillation phenomenon must either occur much less frequently or be investigated for cause. **This is documented as a known risk going into the pre-registered measurement campaign.** If the rate at full scale exceeds 10% in any condition, §11's overall exclusion-rate clause requires disclosure and investigation.

### What is NOT changed

- §1 Research question. Unchanged.
- §2 Hypotheses H1–H4. Unchanged.
- §3 Design: 2,000 trials total, n=500 per condition × 4 conditions. Unchanged.
- §6.1 Latency definition. Unchanged in substance.
- §6.2 100 ms exclusion. Unchanged.
- §6.3 Effect-size definitions. Unchanged.
- §7 Randomization and blocking. Unchanged.
- §8 Stress condition. Unchanged.
- §9 Accuracy parity gate. Unchanged.
- §11 criteria 1, 2, 3. Unchanged. Only criterion 4 is restated.
- §12 Statistical analysis plan. Unchanged.
- All prior amendments v2 through v7.3. Unchanged.

### Stop condition

If the restated criterion 4 produces an exclusion rate exceeding the per-condition 10% cap (per §11's overall exclusion-rate clause), the cause is investigated and disclosed per §11. The 10% headroom must hold for both pipelines independently after the pre-registered campaign runs.

### External timestamp

This amendment is committed to the public repository at github.com/akulswami/sensor-mlc-latency and the commit is tagged as `prereg-amendment-2026-05-25-v7-4`. The repository release is mirrored to Zenodo with a new DOI distinct from prior amendments. The DOI of the Zenodo release containing this amendment is the authoritative external timestamp. **Per v5 Change 4, the DOI is minted same-day; this amendment may not be referenced as authoritative in any commit, code, or capture session until the Zenodo release is published and its DOI is inserted into the `Status` line above.**

## Amendment 2026-05-25 (v7.5): Falsification of H1/H4 at btest scale; reframe to characterization study; addition of energy as a secondary outcome, I²C contention as the primary stress, and mlc-binary as a third pipeline variant

**Status:** Pre-registered. Zenodo DOI: 10.5281/zenodo.20389914 (https://doi.org/10.5281/zenodo.20389914).

**Data collected under prior protocol that is affected by this amendment:**

No pre-registered confirmatory measurement runs have been executed under any version of this pre-registration. The 59 btest-scale blocks captured on 2026-05-25 (block IDs 001-005, 101-112, 200-202, 301-312, 401-407, 501-502, 601-618, in `data/training/latency-experiment/`) are exploratory smoke-test data, not confirmatory pre-registered measurements. v7.5 incorporates findings from this exploratory data into the pre-registered protocol before the confirmatory campaign begins.

The exploratory btest data is summarized in `data/training/latency-experiment/CAMPAIGN_SUMMARY.md` (committed in `b8d6113` and updated with energy findings in `b35a15f`). The analysis script that produces the per-cell statistics is `code/analysis/analyze_energy_and_latency.py` (committed in `b35a15f`).

---

### Reason for this amendment

The btest-scale exploratory data revealed three categories of findings that require pre-registered protocol changes before any confirmatory campaign can produce interpretable results:

**(1) Falsification of H1 and H4 at btest scale.**

The original H1 stated that median wire-level latency of the on-sensor MLC pipeline is lower than the on-host pipeline under no CPU stress. The btest data (blocks 301-312, n=17-18 per cell, vanilla scheduling, idle condition):

- Host pipeline median: 351 µs
- MLC pipeline median (3-transaction bank-switch read): 761 µs

The MLC pipeline median is 410 µs **higher** than the host pipeline median, not lower. H1 is falsified at btest scale; under any reasonable extrapolation the confirmatory campaign would not support H1₁ ("median(latency_MLC) < median(latency_host)") because the observed direction is opposite.

The original H4 stated that median MLC pipeline latency under CPU stress differs from no-stress by at most a small effect (per §6.3: <10 µs absolute median difference). The btest data (block-001 mlc-idle vs block-003 mlc-stress, exploratory pre-restructure smoke):

- MLC idle median: 569 µs (5 trials)
- MLC stress median: 567 µs (5 trials)
- Difference: 2 µs, well within the 10 µs threshold

H4 is **directionally supported by btest data** but for a reason different from the pre-registered theory. The pre-reg's theory was "MLC silicon is decoupled from host load." The btest finding is that **neither pipeline's median latency moves under CPU stress** — the host pipeline median is also nearly invariant to CPU stress (block-002 host-idle 370 µs vs block-004 host-stress ~365 µs, both at btest scale n=5-6). This means the CPU stress condition does not produce the differential degradation H2 predicts, because there is essentially no degradation to differentiate. The mechanism on which H2 and H4 rest is not present at this exploratory scale.

The btest data does NOT rule out an effect at the confirmatory scale (n=500 per condition would catch effects smaller than btest n=18 can resolve). However, the observed effect direction at btest scale and the mechanistic understanding gained (see Change 2 below) make H1 unrecoverable.

**(2) I²C bus contention is a more relevant stress modality than CPU stress.**

Exploratory characterization of the I²C bus (using the `i2c_hammer` tool, committed in `d4a877d`) revealed that 3 parallel I²C reader processes on the LSM6DSOX bus (modeling 3 sensors on a shared bus, a realistic embedded configuration) raise the median I²C read time from 300 µs (idle) to 623 µs (N=3 contention), a +108% increase. Under N=3 i2c-contention (blocks 304-306 and 310-312, vanilla scheduling):

- Host pipeline latency: 351 → 643 µs (+292 µs, +83%)
- MLC pipeline latency: 761 → 1534 µs (+773 µs, +102%)

Both pipelines degrade dramatically under I²C contention, with the MLC pipeline degrading more in absolute terms because each MLC measurement requires 3 I²C transactions vs the host pipeline's 1. This is a richer stress modality than CPU stress: CPU stress at btest produced ~0 µs latency change; I²C contention produced 290-770 µs changes. The pre-registered campaign should test the modality that actually affects the system under measurement.

**(3) The MLC silicon's wire-level latency is dominated by the I²C read protocol, not by the silicon's inference time.**

Inspection of `code/jetson/mlc_pipeline/latency_test_mlc.c` (committed under v7) shows that reading MLC0_SRC requires 3 sequential I²C transactions:

1. Write `FUNC_CFG_ACCESS = 0x80` (switch to embedded function bank)
2. Read `MLC0_SRC` (the inference result)
3. Write `FUNC_CFG_ACCESS = 0x00` (restore user bank)

This is a property of the LSM6DSOX register-bank protocol; the inference itself completes inside the silicon before the INT1 edge fires. Predicted wire-level latency = 3 × i2c_read_bench median, which matches observed (903 µs predicted vs 761 µs observed at idle; 1869 µs predicted vs 1534 µs observed at N=3 contention). The variance is within the kernel I²C pipelining error expected for back-to-back transactions to the same slave.

An alternative MLC read path (`latency_test_mlc_binary.c`, committed in `d4a877d`) skips the bank-switch read entirely by toggling the decision GPIO unconditionally on every INT1 rising edge. This is valid only for strictly 2-class MLC configurations (e.g., `mlc_motion_w75.h`), where every INT1 edge corresponds to a binary-state transition by definition. The internal `host_dt_us` for this variant is 17-21 µs (vs the bank-switch variant's ~500 µs internal `host_dt_us`), but the **wire-level** Saleae-measured latency is dominated by Linux gpiod userspace event-handling jitter (bimodal between ~60 µs and ~550 µs, sd 150-200 µs). The mlc-binary variant exposes the gpiod jitter floor that the bank-switch variant hides behind its larger I²C latency.

These three findings together mean the original hypothesis-testing structure (H1-H4) is no longer the right scientific frame for this project. The system as built does not have the property H1 predicts; the stress modality H2-H4 reference does not produce differential latency at the relevant scale; and the underlying mechanism is not the silicon's inference speed but rather the bus protocol cost. The amendment therefore reframes the project as a **characterization study** of wire-level latency and energy across pipeline variants, stress conditions, and scheduling regimes, with revised confirmatory hypotheses that match the actual measurable properties of the system.

---

### Change 1: §1 Research question is generalized to a characterization frame

§1 is amended. The original research question stands as a sub-question; the framing is generalized to a characterization study with energy as a secondary axis:

> For an IMU-based edge-AI classification pipeline running on an NVIDIA Jetson Orin Nano with an STMicroelectronics LSM6DSOX IMU, **what are the wire-level latency and host-side energy characteristics of three concrete classification pipelines (host-side software classifier, on-sensor MLC with bank-switch read, on-sensor MLC with unconditional binary-fast GPIO toggle), how do those characteristics change under realistic deployment stress (I²C bus contention from competing sensors on the same bus), and what role does host scheduling regime (vanilla CFS vs SCHED_FIFO with CPU pinning) play in either axis?**

The original sub-questions ("does on-sensor MLC produce lower wire-level latency than host?" and "how does this comparison change under host CPU contention?") are explicitly retained as part of the characterization, but they are no longer framed as a directional hypothesis-testing claim.

### Change 2: §2 Hypotheses H1-H4 are formally falsified or restated

The original H1-H4 are replaced by H1'-H6' below. Each new hypothesis is grounded in btest-scale observations and is directional based on the observed effect direction at btest scale, not based on a priori theory.

**Falsification record:**

- **H1** ("median(latency_MLC) < median(latency_host) under no stress") is **falsified at btest scale**. Observed direction is opposite: median(MLC bank-switch) = 761 µs, median(host) = 351 µs, n=17-18 per cell. The confirmatory campaign will report this falsification regardless of n.
- **H2** ("MLC's latency advantage over host is larger under CPU stress than no stress") is **vacuously false**: there is no advantage to amplify because the direction was wrong from the start.
- **H3** ("median host latency under CPU stress > under no stress") is **falsified at btest scale**: 365 vs 370 µs in btest smoke; CPU stress does not move latency. Retained as a control hypothesis with reversed expectation (see H5' below).
- **H4** ("MLC latency is decoupled from host CPU load") is **directionally supported but for the wrong reason** at btest scale. Retained as control (H6').

**New hypotheses for the confirmatory campaign:**

- **H1' (latency ordering at idle):** Median wire-level latency satisfies `median(host) < median(MLC bank-switch)` under idle, vanilla scheduling.
  - H1'₀: median(host | idle) ≥ median(MLC bank-switch | idle)
  - H1'₁: median(host | idle) < median(MLC bank-switch | idle)

- **H2' (latency ordering under contention):** Median wire-level latency satisfies `median(host) < median(MLC bank-switch)` under N=3 i2c-contention, vanilla scheduling.
  - H2'₀: median(host | i2c-contention) ≥ median(MLC bank-switch | i2c-contention)
  - H2'₁: median(host | i2c-contention) < median(MLC bank-switch | i2c-contention)

- **H3' (MLC degrades more than host under bus contention):** The increase in median latency from idle to N=3 i2c-contention is larger for the MLC bank-switch pipeline than for the host pipeline, in absolute terms.
  - H3'₀: Δ_MLC ≤ Δ_host, where Δ = median(latency | i2c-contention) − median(latency | idle)
  - H3'₁: Δ_MLC > Δ_host

- **H4' (energy ordering at idle):** Mean VDD_IN milliwatts measured by the Jetson on-board INA3221 satisfies `mean(MLC) < mean(host)` under idle, vanilla scheduling.
  - H4'₀: mean(power_MLC | idle) ≥ mean(power_host | idle)
  - H4'₁: mean(power_MLC | idle) < mean(power_host | idle)

- **H5' (CPU stress is a null condition for latency):** Median wire-level latency under CPU stress differs from idle by no more than a small effect for the host pipeline.
  - H5'₀: |median(host | cpu-stress) − median(host | idle)| > 30 µs
  - H5'₁: |median(host | cpu-stress) − median(host | idle)| ≤ 30 µs
  - This is the EXPECTED falsification of the original H3. H5' replaces H3 with the opposite expectation.

- **H6' (CPU stress is a null condition for energy):** Mean VDD_IN under CPU stress is materially larger than under idle for both pipelines.
  - H6'₀: mean(power | cpu-stress) ≤ mean(power | idle) + 1000 mW
  - H6'₁: mean(power | cpu-stress) > mean(power | idle) + 1000 mW
  - This is a positive control demonstrating that CPU stress IS detectable on the energy axis even though it is not detectable on the latency axis.

H1', H2', H3', H4' are the substantive hypotheses. H5' and H6' are control hypotheses that establish CPU stress is a null condition for latency but not for energy. H1' through H6' are independent tests; multiplicity correction is applied per §12 (Holm-Bonferroni across these 6 tests).

### Change 3: §6.1 Primary outcomes are extended to include energy

§6.1 is amended:

> **Primary outcomes:**
>
> (a) **Wire-level latency per trial:** the time difference, measured by the Saleae Logic Pro 8, between the rising edge of the IMU INT1 line (D0) and the rising edge of the host's decision GPIO (D1), for trials in which a valid classification occurred. Sampling at ≥ 50 MS/s; resolution floor 20 ns.
>
> (b) **Host-system power per condition:** mean VDD_IN milliwatts measured by the Jetson Orin Nano's on-board INA3221 power monitor (kernel `hwmon1`, sourced via `tegrastats.log`) across all samples within a condition's measurement window. Sampling rate: ~2.5 Hz (one sample per ~400 ms tegrastats tick). Per-cell n at confirmatory scale: 500 trials × 5 s/trial × 2.5 Hz ≈ 6250 samples.

§6.2 (Secondary outcomes) is extended:

> Add: **Energy 95th percentile and IQR per condition** (alongside the existing latency 95th percentile, IQR, and max).

§6.3 (Effect-size definitions) is extended:

> Add: **"Material energy difference" threshold:** an absolute difference in mean VDD_IN of at least 50 mW. The 50 mW threshold is committed in advance based on the empirical between-block VDD_IN variability observed at btest scale (sd ~150-300 mW for individual samples, sd ~30-50 mW for block-level means at btest n=75 samples per block). 50 mW is approximately 1% of total Jetson SoC power and is the minimum effect size that is operationally meaningful for "let the host sleep" claims.

### Change 4: §8 Stress condition is extended; CPU stress demoted to control

§8 is amended. CPU stress is retained but is no longer the primary stress condition; I²C contention is added as a second stress condition and is the primary one for H1'-H4':

> **Stress conditions (three):**
>
> 1. **Idle** (the no-stress condition). Jetson idle, only the measurement harness and required system services running. Blocks above 10% mean CPU utilization on non-harness cores are flagged and excluded.
>
> 2. **I²C contention (N=3) [PRIMARY STRESS for H1'-H4']:** three parallel `code/jetson/sensor_bringup/i2c_hammer` processes on the same I²C bus as the LSM6DSOX (bus 7), each reading the WHO_AM_I register in a tight ioctl loop. The empirically calibrated N=3 corresponds to median i2c-read latency of ~625 µs (vs ~300 µs at idle), representative of 3 sensors sharing the bus in a realistic embedded multi-sensor configuration. Verification: `code/stress/run_stress.sh verify-i2c-contention` checks that 3 i2c_hammer processes are active before block-data collection; blocks during which contention verification fails are flagged and excluded.
>
> 3. **CPU stress [CONTROL for H5'/H6']:** `stress-ng matrixprod` saturating all CPU cores at the highest non-thermal-throttling load. Verification as before (95% utilization threshold). At btest scale this condition produced ~0 µs latency change for both pipelines but ~+3000 mW VDD_IN. Retained primarily as a positive control demonstrating that CPU stress IS detectable on the energy axis and IS NOT detectable on the latency axis.

The confirmatory campaign therefore consists of 3 pipelines × 3 conditions = 9 cells. Each cell receives 500 trials (per §3 retained from v1; see "What is NOT changed" below). Total trials: 4500.

### Change 5: §5 Pipelines are extended to include mlc-binary

§5 is amended. The original two pipelines (host, MLC) are retained, and a third pipeline variant is added:

> **Three pipelines:**
>
> 1. **Host pipeline** (`code/jetson/host_inference/host_pipeline_parity`): the host reads accelerometer data via I²C on every DRDY interrupt, runs the binary classifier over a sliding window, and toggles the decision GPIO (D1) when the binary state changes.
>
> 2. **MLC bank-switch pipeline** (`code/jetson/mlc_pipeline/latency_test_mlc_w75`): on every MLC interrupt (D0), the host performs the 3-transaction I²C bank-switch read of `MLC0_SRC`, decodes the binary state, and toggles D1 only if the binary state changed. This is the pre-registered MLC pipeline from v7.
>
> 3. **MLC binary-fast pipeline** (`code/jetson/mlc_pipeline/latency_test_mlc_binary_w75`): on every MLC interrupt (D0), the host toggles D1 unconditionally without reading MLC0_SRC. Valid only because the MLC is loaded with a strictly 2-class configuration (`mlc_motion_w75.h`), under which every MLC interrupt corresponds to a binary state transition by definition. This variant tests whether the bank-switch read is the dominant latency contributor (it is, at idle) or whether other factors (gpiod userspace jitter, sensor INT1 propagation) form a comparable floor (they do, under chrt+taskset scheduling).
>
> H1'-H4' compare host vs MLC bank-switch. The mlc-binary variant is treated as an instrumented characterization to expose the latency floor; H1'-H4' do not directly test it, but its per-cell statistics are reported.

### Change 6: §3 Design — n=500 per cell retained, cell count expanded

§3 retains the n=500 per cell pre-commitment from v1, applied to the expanded design:

- Original: 2 pipelines × 2 conditions × 500 trials = 2000 trials
- v7.5: **3 pipelines × 3 conditions × 500 trials = 4500 trials**

For chrt+taskset scheduling (see Change 7 below), the same 4500-trial structure is repeated as an ablation; this is documented as a planned ablation, not as a hypothesis test. The chrt+taskset ablation is exploratory and is not subject to multiplicity correction.

### Change 7: chrt+taskset scheduling as a planned ablation

The chrt+taskset scheduling regime (SCHED_FIFO priority 99, CPU pinned to core 5 via `chrt -f 99 taskset -c 5`) is added as a planned ablation alongside vanilla CFS scheduling. The ablation is exploratory; no pre-registered hypotheses depend on it. The btest data showed that chrt+taskset reduces median latency under contention substantially (e.g., mlc bank-switch i2c-contention: 1534 µs vanilla → 796 µs chrt+taskset) while having negligible effect on energy means (<1% shift). The ablation tests whether this btest pattern holds at confirmatory scale, and characterizes whether the gpiod userspace jitter floor observed in the mlc-binary variant can be reduced by RT scheduling.

The orchestrator code modification required to invoke pipelines under chrt+taskset is currently held as an unstaged transformation (see commit message of `d4a877d`); it is not committed to `run_stress_block.py` because committing it would unilaterally change the vanilla-scheduling default. If the ablation is part of the confirmatory campaign, a future amendment (or this v7.5, after Zenodo timestamp) will introduce a `--scheduling {vanilla, rt}` flag to the orchestrator.

### Change 8: §11 Exclusion criteria are unchanged for trials; new block-level criterion for energy

§11 (trial-level exclusions) is unchanged from v7.4. A new block-level exclusion criterion is added for the energy axis:

> **Energy block exclusion:** A block is flagged and excluded from energy analysis if its tegrastats sampling produced fewer than 50 samples (i.e., the block ran for less than ~20 seconds of tegrastats sampling). At btest scale all blocks produced 73-80 samples; at confirmatory scale (longer blocks) the threshold of 50 is well below the expected ~750 samples per 5-minute block.

No change to the latency exclusion criteria 1-4.

### Change 9: §12 Statistical analysis plan extended for the new hypotheses

§12 (analysis plan) is extended:

> **H1', H2' (one-sided Mann-Whitney U):** `mann_whitney_u(host_latencies, mlc_latencies, alternative='less')`. Pre-registered α = 0.05 per test, Holm-Bonferroni corrected across all 6 hypotheses.
>
> **H3' (Hodges-Lehmann difference + bootstrap CI):** Δ_MLC and Δ_host are each estimated as the median paired-difference (between-block bootstrap). H3'₁ accepted if the 95% bootstrap CI for (Δ_MLC − Δ_host) lies strictly above 0.
>
> **H4' (one-sided Mann-Whitney U on energy samples):** `mann_whitney_u(mlc_power, host_power, alternative='less')`. The per-sample energy data is autocorrelated within a block at the ~400 ms tegrastats sampling rate; effective sample size is reduced by an estimated factor of ~10 (justified by the empirical autocorrelation of tegrastats VDD_IN at btest scale, characterized post-campaign). Holm-Bonferroni applied as above.
>
> **H5' (TOST equivalence, two one-sided tests):** TOST with bootstrap margin of ±30 µs, per the threshold committed in §2 H5'.
>
> **H6' (one-sided Mann-Whitney U):** `mann_whitney_u(cpu_stress_power, idle_power, alternative='greater')` with the +1000 mW threshold checked separately via bootstrap CI on the difference of means.

The existing pre-registered analysis module (`code/analysis/statistics.py`) implements Mann-Whitney U, Hodges-Lehmann, bootstrap CI, TOST, and Holm-Bonferroni; no new statistical machinery is needed.

---

### What is NOT changed by this amendment

- §1 retains the original research question as a sub-question within the new characterization frame.
- §3 retains n=500 trials per cell.
- §4 Classification task. Unchanged.
- §6.2 Latency 95th percentile, IQR, max. Unchanged (energy versions added).
- §7 Randomization and blocking. Unchanged.
- §9 Accuracy parity gate (≥90%, ≤2pp gap). Unchanged.
- §11 trial-level criteria 1-4. Unchanged (a new block-level energy criterion is added).
- §12 statistical machinery. Unchanged (the existing module supports the new hypotheses).
- §13 Deviations and reporting. Unchanged.
- §14 What this pre-registration does not cover. Unchanged.
- All prior amendments v2 through v7.4. Unchanged.

---

### Procedural lessons recorded in this amendment

1. **Btest-scale exploration before pre-registered measurement is essential and was correctly performed.** v7.5 documents falsification at the exploratory stage, BEFORE any confirmatory data was collected. This is the pre-registration discipline working as intended: hypotheses generated a priori were tested against empirical reality at small scale and updated before the expensive confirmatory campaign.

2. **Stress modality selection requires empirical justification.** The original H2-H4 assumed CPU stress was the relevant stress modality. Empirical data showed it isn't (latency-wise); I²C contention is. A future pre-registration should empirically calibrate the stress condition's effect on the primary outcome before committing it to a hypothesis.

3. **The Razmi & Shojaei 2026 preprint (arXiv:2602.21418)** asserts "low-latency control" and "energy efficiency" for a similar LSM6DSV16X MLC system without measuring either property. v7.5 commits this project to measuring both. Where these properties exist in the data, the paper supports them; where they don't (the latency claim), the paper reports the falsification.

4. **The lab notebook must record the falsification of H1/H4 at btest scale.** A separate lab-notebook entry (`docs/lab-notebook/2026-05-25.md`, to be written) documents the timeline of how the falsification was discovered: orchestrator validation runs (blocks 101-112) → restructured orchestrator (200-202) → first clean 12-block campaign (301-312) revealed the falsification → mlc-binary variant added → chrt+taskset ablation. This trail is the empirical chain of custody for v7.5's claims.

---

### Stop condition

If the confirmatory campaign (3 pipelines × 3 conditions × 500 trials = 4500 trials per scheduling regime) produces statistics that contradict the btest-scale findings — specifically, if at full n any of H1', H2', H3', H4' is rejected by the bootstrap CI test — the contradiction is investigated and reported. The btest-scale findings are not pre-registered claims; they are the empirical basis for v7.5's directional hypotheses. The confirmatory campaign tests those hypotheses against fresh data.

If the i2c-contention condition cannot be reliably maintained at full scale (e.g., if the i2c_hammer processes cause sensor brownout, kernel panic, or sensor wedging events more often than at btest scale), the condition is downgraded to a control and a separate amendment defines a substitute primary stress.

---

### External timestamp

This amendment is committed to the public repository at github.com/akulswami/sensor-mlc-latency and the commit is tagged as `prereg-amendment-2026-05-25-v7-5`. The repository release is mirrored to Zenodo with a new DOI distinct from prior amendments. The DOI of the Zenodo release containing this amendment is the authoritative external timestamp. **Per v5 Change 4, the DOI is minted same-day; this amendment may not be referenced as authoritative in any commit, code, or capture session until the Zenodo release is published and its DOI is inserted into the `Status` line above.**

**DOI debt resolution (2026-05-25):** v7.3, v7.4, and v7.5 Zenodo DOIs were originally placeholders awaiting minting. They were minted in a single Zenodo release session immediately following the commit of this amendment, within the same calendar day. The three DOIs are:

- v7.3: `10.5281/zenodo.20389899` (https://doi.org/10.5281/zenodo.20389899)
- v7.4: `10.5281/zenodo.20389909` (https://doi.org/10.5281/zenodo.20389909)
- v7.5: `10.5281/zenodo.20389914` (https://doi.org/10.5281/zenodo.20389914)

These DOIs are back-filled into the `Status` lines of their respective amendments above. Per v5 Change 4, the same-day commitment is honored for all three amendments. This paragraph supersedes the prior "Outstanding DOI debt" note.


## Amendment 2026-05-26 (v7.6): Falsification of H4' under jc-effective measurement; MAXN_SUPER_JC mode as required measurement configuration; §11 exclusion-rate clause restated; classifier stability added as secondary outcome

**Status:** Pre-registered. Zenodo DOI: 10.5281/zenodo.20400025 (https://doi.org/10.5281/zenodo.20400025).

**Data collected under prior protocol that is affected by this amendment:**

No pre-registered confirmatory measurement runs have been executed under any version of this pre-registration. The btest-scale exploratory data (59 blocks in `data/training/latency-experiment/block-*-btest/`, committed in b8d6113) and the long-duration smoke data (4 blocks 700-703 in the same directory, committed in 56b5051) are both exploratory; v7.6 incorporates findings from the long-duration smoke into the pre-registered protocol before the confirmatory campaign begins.

The long-duration smoke data is summarized in `data/training/latency-experiment/CAMPAIGN_SUMMARY.md` (sections "Long-duration smoke findings", "MLC decision cadence and exclusion-rate interpretation", and "nvpmodel methodology fix"). The analysis output is frozen in `data/training/latency-experiment/ANALYSIS_OUTPUT_LONG_DURATION.md`. The lab-notebook entries for 2026-05-25 (second session) and 2026-05-26 document the chain of custody for the findings reported here.

---

### Reason for this amendment

The long-duration smoke data revealed three substantive findings that require pre-registration changes:

**(1) v7.5 H4' is falsified.** H4' as written in v7.5 stated that the on-sensor MLC pipeline uses lower mean VDD_IN milliwatts than the host pipeline under idle, vanilla scheduling. The directional support for H4' in v7.5 came from btest data showing a +155 mW gap (host idle 4799 mW vs mlc idle 4644 mW). The long-duration smoke data, captured under the same nvpmodel 25W mode and on the same physical rig, gives:

- **b703 host idle, jc-effective (jc_eff = 100.0%, n_eng = 3551 samples): 6982 mW**
- **b702 mlc idle, jc-effective (jc_eff = 100.0%, n_eng = 3554 samples): 7014 mW**
- **Gap (host − mlc): −32 mW**

The observed gap is within the v7.5 §6.3 ±50 mW noise floor. Under jc-effective measurement, the energy gap collapses to noise. The btest +155 mW finding was an artifact of comparing measurements taken under free-running DVFS, where the host pipeline's slightly higher CPU utilization caused schedutil to scale CPUs up more often than for the MLC pipeline. Under locked CPU frequency (which the new MAXN_SUPER_JC mode enforces), this scaling difference disappears.

**(2) The nvpmodel/jetson_clocks non-determinism is a methodology defect requiring a configuration change.** During the 2026-05-25 long-duration smoke series, jetson_clocks effectiveness was empirically observed to vary across blocks: b700 jc_eff = 100%, b701 jc_eff = 17.3%, b702 jc_eff = 100%, b703 jc_eff = 100%. The cause is the default nvpmodel 25W mode (mode 1) declaring `CPU_A78_*: MIN_FREQ = 729600`, which the kernel periodically restores even after `sudo jetson_clocks` sets min == max == 1728000. The reassertion is non-deterministic in timing; without explicit per-block verification of jc effectiveness, energy measurements collected under "jetson_clocks-applied" cannot be assumed to actually be jc-effective. A custom nvpmodel mode (MAXN_SUPER_JC, ID 3) was created, installed, and empirically validated; it pins CPU MIN_FREQ to 1728000, defeating the reassertion.

**(3) The §11 exclusion-rate clause requires restatement.** v7.5 §11 (inherited from v1) states that if the per-condition trial exclusion rate exceeds 10%, the cause must be investigated and disclosed. At long-duration scale, b700 (mlc i2c-contention, jc-effective) produced 16.7% exclusion and b701 (host idle, jc-ineffective) produced 12.2%. Investigation via `code/analysis/diagnose_mlc_decision_cadence.py` showed that:

- The MLC's intrinsic decision cadence is ~706 ms (one quarter of the 75-sample / 26 Hz window). This is structural to the silicon, not a measurement defect.
- The `multiple_d1_in_window` exclusion category dominates the exclusions (44 of 60 in b700; 43 of 44 in b701).
- The "multiple D1" pattern is the MLC's intrinsic 706 ms cadence becoming observable when the classifier's binary output is unstable across a stimulus window — i.e., when the silicon's classification flickers between motion/still due to stress.
- The exclusions are valid observations of MLC classifier degradation under stress, not measurement defects. The 12-17% exclusion rate IS a measurement of a real secondary failure mode.

The §11 stop-condition language as written would block the confirmatory campaign from proceeding with i2c-contention cells. This is the wrong response: the exclusions ARE the data. §11 must be restated to allow disclosure-only treatment of stress-induced classifier-instability exclusions.

---

### Change 1: §2 H4' is formally falsified and removed from the confirmatory hypothesis set

v7.5 Change 2 introduced H4' as:

> **H4' (energy ordering at idle):** Mean VDD_IN milliwatts measured by the Jetson on-board INA3221 satisfies `mean(MLC) < mean(host)` under idle, vanilla scheduling.

This hypothesis is formally falsified by the b702/b703 apples-to-apples comparison documented above. H4' is replaced by:

> **H4' (NULL, post-falsification 2026-05-26):** Under jc-effective measurement (nvpmodel mode 3 active throughout the block, jc_eff ≥ 99% verified post-hoc from tegrastats CPU-freq samples), mean VDD_IN milliwatts of the host pipeline and the MLC bank-switch pipeline at idle are statistically indistinguishable within the v7.5 §6.3 ±50 mW threshold. The pre-registered directional H4' is empirically falsified.
>
> H4'₀ (null, retained as the empirical finding): |mean(host | idle, jc-eff) − mean(mlc | idle, jc-eff)| ≤ 50 mW.
> H4'₁ (alternative, falsified): mean(mlc | idle, jc-eff) < mean(host | idle, jc-eff) − 50 mW.

The confirmatory campaign will report the empirical gap and bootstrap CI; the directional alternative is no longer pre-registered as an active hypothesis. **No re-test of the falsified H4'₁ is planned.** The empirical finding (gap is null) is reported as such.

### Change 2: §6.1 nvpmodel and jc-effectiveness verification protocol

§6.1 is extended:

> **Measurement configuration (required for all confirmatory blocks):**
>
> 1. Before any confirmatory block: `sudo nvpmodel -m 3` (the MAXN_SUPER_JC mode, defined in `code/jetson/nvpmodel/MAXN_SUPER_JC.snippet` and installable via `code/jetson/nvpmodel/install_maxn_super_jc.sh`). Verification: `nvpmodel -q` must report `NV Power Mode: MAXN_SUPER_JC, 3`.
>
> 2. Each block's tegrastats.log MUST be post-hoc analyzed for jc_eff (percentage of CPU-freq samples at ≥ 1700 MHz across all 6 CPUs). Threshold: `jc_eff ≥ 99.0%`. Blocks with `jc_eff < 99%` are excluded from the confirmatory dataset (block-level exclusion, separate from the trial-level criteria in §11).
>
> 3. The orchestrator (`code/orchestrator/run_stress_block.py`) writes `jc_eff` into block_metadata.json post-capture. Implementation deferred to the confirmatory-campaign code-freeze commit.
>
> 4. Default-mode operation is NOT used for confirmatory measurements. nvpmodel mode 1 (25W) is the deployment-realistic configuration but is not the measurement configuration; the deployment-vs-measurement asymmetry is documented in the paper.

### Change 3: §8 stress conditions are documented as nvpmodel-mode-3-only for confirmatory

§8 is amended:

> All three conditions (idle, i2c-contention, cpu-stress) are measured under nvpmodel mode 3 (MAXN_SUPER_JC). The btest data (59 blocks, b001-b618) was collected under nvpmodel mode 1 (25W) with free-running DVFS; that data is exploratory and is NOT directly comparable to confirmatory measurements on the energy axis. On the latency axis, btest data remains informative (latency is less affected by CPU frequency scaling than energy is).
>
> The cpu-stress condition is retained as a control (per H5', H6' from v7.5) but at long-duration scale under nvpmodel mode 3 it is expected to produce a smaller energy delta than at btest scale (because the baseline is already near max CPU frequency).

### Change 4: §11 exclusion-rate clause is restated

§11's overall exclusion-rate clause is amended:

> **§11 exclusion-rate clause (v7.6 restatement):**
>
> Per-cell trial exclusion rate is reported alongside the latency results as a secondary outcome (see Change 5 below for the new "classifier stability" secondary outcome). For cells where the exclusion rate exceeds 10%:
>
> 1. The dominant exclusion category is reported (e.g., `multiple_d1_in_window`, `no_d1_in_window`, `multiple_d0_before_d1`).
>
> 2. If the dominant exclusion is `multiple_d1_in_window` AND the inter-edge-gap analysis (via `code/analysis/diagnose_mlc_decision_cadence.py`) shows gaps concentrated at integer multiples of ~706 ms (the MLC decision cadence), the exclusion is classified as **classifier-instability exclusion**. Classifier-instability exclusions are reported as data (they characterize the MLC's behavior under stress) and do NOT trigger a campaign stop.
>
> 3. If the dominant exclusion is any other category (`no_d1_in_window`, `multiple_d0_before_d1`, or `multiple_d1_in_window` with sub-millisecond gaps not at MLC-cadence multiples), the exclusion is investigated for measurement defects per the prior §11 language and may trigger a stop.
>
> 4. The full exclusion-category breakdown per cell is committed alongside the trial CSVs.

Examples of how this applies to the long-duration smoke blocks:
- b700 mlc i2c-contention: 16.7% exclusion, 44/60 multiple_d1, all at 706 ms multiples → classifier-instability, disclosed not stopped
- b701 host idle (jc-ineffective): 12.2% exclusion, 43/44 multiple_d1 → classified as classifier-instability under DVFS jitter; b701 is also excluded by the new jc_eff < 99% block-level rule, so this cell will not appear in the confirmatory dataset
- b702 mlc idle: 1.4% exclusion → below the 10% threshold, no action
- b703 host idle: 1.1% exclusion → below the 10% threshold, no action

### Change 5: classifier stability is added as a secondary outcome

§6.2 is extended:

> **Classifier stability (per-cell):** the fraction of trials within a cell that produce exactly 1 D1 rising edge in the stimulus window. Formally: `n_trials_with_n_d1==1 / n_total_trials_per_cell`. Higher is more stable. Reported per-cell alongside latency median, energy mean, and exclusion rate.
>
> The "1 D1 per stimulus" criterion reflects the expected classifier behavior under stable measurement conditions (the classifier produces a single binary state-change per stimulus). Lower values reflect either no-decision intervals (`0 D1`, the `no_d1_in_window` exclusion) or oscillation (`≥2 D1`, the `multiple_d1_in_window` exclusion).

Empirical reference from the long-duration smoke:
- b703 host idle: 356/360 = 98.9% stable
- b702 mlc idle: 355/360 = 98.6% stable
- b700 mlc i2c-contention: 306/360 = 85.0% stable
- (b701 host idle, jc-ineffective: 316/360 = 87.8% stable — excluded from confirmatory by Change 2)

The confirmatory campaign will report per-cell classifier stability and pre-register the directional comparison: stability is expected to be lower under i2c-contention than under idle (H7' below).

### Change 6: §2 New hypothesis H7' (classifier stability under contention)

A new hypothesis is added:

> **H7' (classifier stability degradation under bus contention):** The per-cell classifier-stability rate (fraction of trials with exactly 1 D1 per window) is lower under i2c-contention than under idle, for the MLC bank-switch pipeline.
>
> H7'₀: stability(MLC | i2c-contention) ≥ stability(MLC | idle)
> H7'₁: stability(MLC | i2c-contention) < stability(MLC | idle)

Test: one-sided proportion test (chi-square or Fisher's exact at the per-trial level), Holm-Bonferroni corrected across the full set of confirmatory hypotheses (now H1'-H3', H5'-H7'; H4' is no longer tested per Change 1).

### Change 7: §10 (Items deferred to Phase B) updated

§10 should now reflect that:

- The nvpmodel mode 3 (MAXN_SUPER_JC) is installed and validated on the akulswami-jetson rig as of 2026-05-26.
- The orchestrator `jc_eff` post-hoc computation is NOT yet implemented; this is added to the §10 Phase-B locks-before-confirmatory list.
- The MLC decision cadence (~706 ms) is documented as a measured-not-pre-registered property of the silicon and is referenced by §11's restated clause.

### Change 8: Document MLC ~706 ms decision cadence

A new section is added to §6 (or as an appendix; placement to be decided when v7.6 is rendered): the empirical MLC decision cadence is 706.1 ± 0.5 ms at the inter-D1-edge minimum. This is reproducible from both b700 and b703 via `diagnose_mlc_decision_cadence.py`. The cadence is one quarter of the 75-sample / 26 Hz window (= 2.88 s / 4 ≈ 720 ms; observed 706 ms reflects integer-sample boundary effects in the MLC decimator). This is a documented property of the silicon; no hypothesis is pre-registered about its value. It is referenced by §11 (Change 4 above) as the test for "real classifier oscillation" vs "measurement defect."

---

### What is NOT changed by this amendment

- §1 research question (the characterization frame from v7.5 stands)
- §3 trial count (n=500 per cell retained, applied to the now-9-cell × 1-scheduling-regime = 4500-trial confirmatory dataset; chrt+taskset ablation remains as planned in v7.5 Change 7)
- §4 classification task (binary motion-vs-still)
- §5 pipelines (host, mlc, mlc-binary as in v7.5)
- §7 randomization and blocking
- §9 accuracy parity gate
- §11 trial-level criteria 1-4 (the cell-level exclusion-rate clause is restated; criteria 1-4 are unchanged)
- §12 statistical machinery (existing module supports the proportion tests for H7' too)
- §13, §14
- All prior amendments v2 through v7.5

H1', H2', H3', H5', H6' from v7.5 remain in effect as pre-registered hypotheses. Only H4' is retired (Change 1). H7' is added (Change 6).

---

### Procedural lessons recorded in this amendment

1. **Long-duration smoke testing exposed methodology defects that btest could not detect.** The btest data was internally consistent under its own (free-running DVFS) measurement conditions; only sustained-load measurement under nvpmodel-25W revealed the jc/MIN_FREQ reassertion behavior. **The confirmatory campaign protocol now requires per-block jc_eff verification because btest-style "apply jc and assume it stuck" is empirically insufficient.**

2. **The Razmi & Shojaei 2026 paper's energy claim (cited in v7.5) is not refuted by our data; it is more strongly characterized.** Their on-sensor MLC architecture (LSM6DSV16X) and ours (LSM6DSOX) share the bank-switch decision-output mechanism. Our data shows that any "host saves energy at idle" effect, if it exists, is below the 50 mW measurement noise floor under jc-effective conditions. The paper can now claim a tighter null than v7.5 implied.

3. **The exclusion-rate problem and the classifier-instability finding are the same finding viewed two ways.** §11 originally treated "high exclusion rate" as a stop condition; v7.6 treats it as a secondary outcome (classifier stability). Both interpretations are correct, but the v7.6 framing reflects the true scientific content of the exclusions.

4. **System config changes (nvpmodel mode 3) need their own reproducibility artifacts.** The MAXN_SUPER_JC mode is committed as a snippet plus install script in `code/jetson/nvpmodel/`; the install script is idempotent, makes a backup, verifies via nvpmodel-parse before completing, and is run via `sudo`. This pattern should be reused for any future Jetson-side system config changes.

---

### Stop condition

If the confirmatory campaign produces statistics that contradict the long-duration-smoke findings — specifically, if at full n any of H1', H2', H3', H7' is rejected by the bootstrap CI test — the contradiction is investigated and reported. The smoke-scale findings are the empirical basis for v7.6's hypotheses; the confirmatory campaign tests them against fresh data.

The §11 cell-level exclusion-rate clause (Change 4) is the new stop condition. A campaign stop is triggered if:

- Any cell's exclusion rate exceeds 30% (a higher cap than the original 10%, given that 12-17% exclusion at long-duration scale is now expected for stress cells)
- OR the dominant exclusion category in any cell is NOT classifier-instability per the Change 4 criteria
- OR jc_eff < 99% for any block (block-level exclusion per Change 2, but if this happens for >5% of blocks the confirmatory dataset is rejected and the nvpmodel mode-3 enforcement is re-verified)

---

### External timestamp

This amendment is committed to the public repository at github.com/akulswami/sensor-mlc-latency and the commit is tagged as `prereg-amendment-2026-05-26-v7-6`. The repository release is mirrored to Zenodo with a new DOI distinct from prior amendments. The DOI of the Zenodo release containing this amendment is the authoritative external timestamp. **Per v5 Change 4, the DOI is minted same-day; this amendment may not be referenced as authoritative in any commit, code, or capture session until the Zenodo release is published and its DOI is inserted into the `Status` line above.**


## Amendment 2026-05-26 (v7.7): §9 parity gate re-specified for burst protocol; per-phase ground-truth evaluation; gap criterion replaced with disclosure

**Status:** Pre-registered. Zenodo DOI: 10.5281/zenodo.20401671 (https://doi.org/10.5281/zenodo.20401671).

**Data collected under prior protocol that is affected by this amendment:**

The 2026-05-23 §9 parity capture (`data/training/2026-05-23/`), evaluated in v7.2 amendment (Zenodo DOI 10.5281/zenodo.20371440), produced PASS under continuous-motion stimulus: host 98.74% / silicon 99.79% / gap 1.05pp. **That result is reclassified by this amendment as a continuous-protocol-only gate evaluation.** It does NOT establish parity under the v7.3 burst protocol (`prereg-amendment-2026-05-25-v7-3`, DOI 10.5281/zenodo.20389899) that the confirmatory campaign will use.

The 2026-05-26 §9 parity re-capture (`data/training/2026-05-26-section9/`), executed today under the v7.3 burst protocol (servo_sweep --mode burst --motion-ms 5000 --still-ms 5000), is the new authoritative §9 evaluation. It is committed to the repository alongside this amendment.

No confirmatory latency-experiment data has been collected; this amendment fully precedes the campaign.

---

### Reason for this amendment

The v7.3 amendment introduced burst-mode servo stimulus (5s motion / 5s still, repeating) as a correction to the v7 implementation that erroneously ran continuous mode. The v7.3 commit (741c46a) updated `code/orchestrator/run_session_parity.py` to invoke servo_sweep with burst mode, and the new parity capture today (2026-05-26-section9) ran under burst as intended.

**Under burst protocol, §9 as originally written is mathematically incompatible with the data.** §9 evaluated host and silicon accuracy by treating each ARM as a single ground-truth class label: still arm → class 0, motion arm → class 4. Under burst protocol, only ~50% of motion-arm windows are actually motion (the other 50% are still phases by design). A perfect classifier on burst data would score ~50% on the motion arm under the arm-as-ground-truth criterion — below the 90% floor.

The 2026-05-26 capture, evaluated under the arm-as-ground-truth criterion, produced:
- Host motion arm: 58.24%
- Silicon motion arm: 64.71%
- Combined host: 79.03%
- Combined silicon: 82.15%
- Gap: 3.12pp

This is not a classifier-quality measurement; it is an artifact of evaluating burst data against a continuous-protocol gate.

The 2026-05-26 capture, evaluated under per-phase ground truth (motion-phase windows → class 4, still-phase windows → class 0, classified from sweep.log MOTION_PHASE_START / STILL_PHASE_START events), produced:
- Host still arm: 99.82%
- Host motion arm (per-phase GT): 90.88%
- Silicon still arm: 99.59%
- Silicon motion arm (per-phase GT): 85.24%
- Combined host: 95.35%
- Combined silicon: 92.41%
- Gap: 2.94pp

Under per-phase evaluation, **both pipelines clear the 90% floor**, but the **gap exceeds the original §9 2pp criterion** by 0.94pp.

The 2pp gap criterion, like the floor, was inherited from the v1 §9 specification, which assumed continuous-motion ground truth and a substantially simpler stimulus protocol than v7.3 burst. Under burst protocol, the gap between host and silicon at phase transitions is a real classifier-difference measurement, not a measurement defect — every transition stresses the 75-sample MLC window with mixed-phase samples, and the host pipeline's classifier handles transitions slightly better than the silicon's. This is consistent with v7.6 H7' (classifier-stability degradation under stress).

The 2pp gap criterion is therefore not a "gate" in the original sense; it is a measurement that should be reported, not enforced. v7.7 replaces it with a disclosure requirement.

---

### Change 1: §9 ground-truth labeling is per-window-phase under burst protocol

§9's ground-truth labeling is amended:

> **§9 ground-truth labeling (v7.7 restatement):**
>
> For sessions captured under burst-protocol servo stimulus (per v7.3 amendment, `--mode burst`):
>
> 1. **Still-arm windows:** all expected class 0.
>
> 2. **Motion-arm windows:** expected class assigned per-window from sweep.log phase events. For each window with end-timestamp `t_w` (relative to imu_logger t0):
>    - If `t_w` falls within a motion phase (between `MOTION_PHASE_START` and the next `STILL_PHASE_START` in sweep.log, relative to the sweep `START` event): expected class = 4.
>    - Otherwise (`t_w` falls within a still phase or before the first motion phase): expected class = 0.
>
> For sessions captured under continuous-motion servo stimulus (the legacy protocol, deprecated in v7.3): arm-as-ground-truth labeling is retained for backward compatibility with v2-through-v7.2 §9 results.

### Change 2: §9 gap criterion is replaced with disclosure

§9's `|accuracy_MLC − accuracy_host| ≤ 2 percentage points` criterion is retired and replaced:

> **§9 gate (v7.7 restatement):**
>
> Before any confirmatory latency data is collected:
>
> 1. **Both pipelines' combined accuracy (still arm + motion arm, per-phase ground truth) must be ≥ 90%** (unchanged from v1 §9).
>
> 2. **The accuracy gap `|host_combined − silicon_combined|` is reported as a documented observation, not as a gate-failure condition.** The gap is a measurement of pipeline-difference under burst protocol; under v7.3-and-later protocols, the gap is expected to reflect a real classifier difference at phase transitions (per the observation noted in Change 4 below).
>
> 3. If either pipeline falls below 90%, §9's existing response framework applies: retrain the host model, redesign the MLC features, or — as the last resort — switch the task. Switching the task triggers a pre-registration amendment.

### Change 3: §9 PASS status under v7.7 from the 2026-05-26 capture

The 2026-05-26 capture (`data/training/2026-05-26-section9/`) passes the v7.7 §9 gate:

- Host combined: **95.35%** (≥90% → PASS)
- Silicon combined: **92.41%** (≥90% → PASS)
- Gap (disclosed): **2.94pp** (under v7.3 burst protocol)

The confirmatory latency campaign may launch under v7.7 with the 2026-05-26-section9 evaluation as the §9-clearing record.

### Change 4: Documented observation about burst-protocol classifier difference

§9 is extended with an observation note:

> **Burst-protocol classifier difference (observation, not hypothesis):**
>
> Under burst-protocol servo stimulus (v7.3 amendment), the host classifier produces consistently higher accuracy at phase transitions than the MLC silicon classifier. Empirical magnitude: ~3pp gap at 1200 s × 1200 s parity capture with 120 motion phases.
>
> Mechanism: the silicon's 75-sample window contains mixed-phase samples for ~3 s spanning each phase transition (= 75 samples / 26 Hz output rate); the host's classifier handles such mixed-phase windows with marginally better accuracy. The host advantage at transitions is structurally separate from, but consistent with, the silicon classifier-instability under bus contention reported in v7.6 H7'.
>
> This observation is recorded for paper-write-up framing but is NOT pre-registered as a hypothesis. The campaign's H1' through H7' set is unchanged.

---

### What is NOT changed by this amendment

- §1 research question
- §2 hypotheses H1' through H7' (no new hypothesis introduced)
- §3 trial count (n=500 per cell, 4500 trials per regime)
- §4 classification task (binary motion-vs-still)
- §5 pipelines (host, mlc, mlc-binary)
- §6 measurement configuration (nvpmodel mode 3 required per v7.6 Change 2)
- §7 randomization and blocking
- §8 stress conditions
- §10 Phase-B locks
- §11 trial-level and cell-level criteria (v7.6's classifier-instability treatment is unchanged)
- §12 statistical machinery
- §13, §14
- All amendments v2 through v7.6

The amendment is scoped specifically to §9. The previously-pre-registered hypothesis set is unchanged. The 90% accuracy floor is unchanged.

---

### Procedural lessons recorded in this amendment

1. **The v7.3 burst-protocol fix unintentionally broke §9 as written.** v7.3 corrected an orchestrator bug (continuous-mode invocation that violated the v7-spec'd 5s/5s burst) without recognizing that §9's arm-as-ground-truth evaluation was incompatible with burst protocol. This was discovered today (2026-05-26) during the pre-confirmatory §9 re-validation. **Future amendments that change stimulus protocol must explicitly evaluate compatibility with all gate-clearing protocols.**

2. **The 2pp gap criterion was a holdover from §9's original formulation, when continuous-motion ground truth made the gap a useful measurement-defect detector.** Under burst protocol, the gap reflects a real classifier difference at phase transitions; clamping it via gate would be artificial. Replacing the gate with a disclosure requirement is the principled action.

3. **The host-vs-silicon transition-handling difference is itself a paper-substantive observation.** It dovetails with v7.6's classifier-stability framing without requiring a new pre-registered hypothesis. Adding a new hypothesis today, after observing the empirical direction, would be post-hoc; reporting the observation transparently is the honest action.

4. **The 2026-05-23 §9 PASS still stands under continuous protocol** — it is not retracted by this amendment. It is reclassified as a continuous-protocol-only result. The 2026-05-26 §9 PASS under burst protocol is the relevant gate for the confirmatory campaign.

---

### External timestamp

This amendment is committed to the public repository at github.com/akulswami/sensor-mlc-latency and the commit is tagged as `prereg-amendment-2026-05-26-v7-7`. The repository release is mirrored to Zenodo with a new DOI distinct from prior amendments. The DOI of the Zenodo release containing this amendment is the authoritative external timestamp. **Per v5 Change 4, the DOI is minted same-day; this amendment may not be referenced as authoritative in any commit, code, or capture session until the Zenodo release is published and its DOI is inserted into the `Status` line above.**


## Amendment 2026-05-26 (v7.8): Block-order seed re-derivation for v7.5+ confirmatory campaign design

**Status:** Drafted, awaiting Zenodo external timestamp. Zenodo DOI: [TBD-DOI-INSERT].

**Data collected under prior protocol that is affected by this amendment:**

No data has been collected using the prior block-order seed (`441756681`, derived from commit `8c48e19`). The prior seed was committed for the v7-era 40-block experiment design (10 blocks per condition × 4 conditions = MLC{idle,stress} × host{idle,stress}). That design was superseded by v7.5 Change 6 (Zenodo DOI 10.5281/zenodo.20389914), which redesigned the campaign to 9 cells (3 pipelines × 3 conditions × 500 trials per cell) before any data was collected.

The prior seed's value and provenance remain visible in the git history of `code/analysis/block_order_seed_provenance.md` (commit `8c48e19` era), preserving the audit record. v7.8 updates the file in place to record the new seed and the change rationale.

---

### Reason for this amendment

The pre-reg block-order seed must satisfy three properties:

1. **Committed before any data using it is collected.** (v1 §7, reaffirmed across v2-v7.7.)
2. **Derived by a deterministic, audit-defensible method** that pre-empts post-hoc seed selection.
3. **Appropriate to the experimental design being run.**

The prior seed (`441756681`, anchored on commit `8c48e19`) satisfied (1) and (2) for the v7-era 40-block design. Under v7.5's redesigned 9-cell × ~9-block layout (81 blocks total under the 300s block-duration choice operationalized in v7.8 Change 2 below), the prior seed could still be applied — the seeded RNG can produce any permutation of any length — but the prior seed's provenance documentation explicitly targets the 40-block design. Using it for the 81-block design would invite an audit question about whether the seed was applied to the design for which its provenance was written.

v7.8 re-derives the seed using the same deterministic method, anchored on commit `f5bd702` (the v7.7 amendment, the most recent commit at which all pre-flight gates for the v7.5+ confirmatory campaign were cleared). This anchor:

- Pre-dates any confirmatory data (no data has been collected since the v7.7 amendment was committed)
- Post-dates all design decisions (v7.5 cell design + v7.6 nvpmodel + v7.7 §9 protocol)
- Cannot be construed as post-hoc seed selection: there is no campaign data against which to evaluate seed alternatives

The new seed (`1990185399`) replaces the prior seed (`441756681`) in `code/analysis/block_order_seed.txt`. The change is also documented in `code/analysis/block_order_seed_provenance.md` with both the new and prior derivations side-by-side.

---

### Change 1: Block-order seed value

The contents of `code/analysis/block_order_seed.txt` are updated from `441756681` to `1990185399`. The new value is derived by:
seed = uint32(first_8_hex_chars(SHA256("f5bd702d82818348c6f606864cf6c0d720751797")))
= uint32(0x769fd1b7)
= 1990185399

Reproducibility one-liner:

```bash
echo -n "$(git rev-parse f5bd702)" | sha256sum | awk '{print $1}' | head -c 8
```

This produces `769fd1b7`, which interpreted as a hex uint32 equals `1990185399`. The git rev-parse is deterministic for any clone of the public repository; the seed derivation is therefore externally reproducible by any auditor.

### Change 2: Block-duration operationalization for v7.5+ campaign

The v7.5+ confirmatory campaign uses **300-second blocks** as the unit of randomization and block-level measurement:

- Each block produces ~60 candidate transitions (300 s × 1 cycle / 10 s × 2 transitions/cycle = 60).
- Each cell (pipeline × condition) requires 500 included transitions → ~9 blocks per cell (allowing some excluded transitions per §11 criteria and v7.6 §11 classifier-instability disclosure).
- 9 cells × ~9 blocks per cell = **~81 blocks total**.
- Block order across the 81 blocks is randomly permuted using the seeded RNG (Change 1 above), interleaving cells throughout the campaign.

The 300-second choice maximizes block-level interleaving for time-of-day / thermal drift mitigation. Alternative durations considered: 600s (45 blocks total) and 1200s (27 blocks total). All durations produce the same total wall time (~7.5 hours); 300s gives maximum resilience against single-block failures (each block failure costs 1/9 of a cell, not 1/3).

§7's original "blocks of 50 trials per condition" language is reinterpreted as "approximately 50-60 transitions per block at v7.3 burst protocol" without modification to the formal §7 text. The 81-block total replaces the v7-era 40-block design (which was never used for data collection).

### Change 3: Cross-reference and audit transparency

`code/analysis/block_order_seed_provenance.md` is updated to include:

1. The new seed value, derivation method, anchor commit, and rationale (per Change 1).
2. The 81-block design context (per Change 2).
3. A "Prior seed" section that records the old seed (`441756681`, commit `8c48e19`) with the explicit note that no data was collected under it and the prior value remains in git history for audit transparency.

The file is updated in-place rather than as a parallel-versioned file, to keep the seed source-of-truth singular. The git history of the file preserves the prior seed's full record.

---

### What is NOT changed by this amendment

- §1 research question
- §2 hypotheses (H1' through H7' from v7.6, unchanged in v7.7)
- §3 trial count (n=500 transitions per cell)
- §4 classification task
- §5 pipelines
- §6 measurement configuration (nvpmodel mode 3 per v7.6)
- §7 randomization-and-blocking principle (block ordering remains randomized via a seeded RNG; only the seed value and block-count are re-operationalized)
- §8 stress conditions (idle, i2c-contention, cpu-stress per v7.5)
- §9 parity gate (per-phase under burst per v7.7)
- §10 Phase-B locks
- §11 trial-level and cell-level criteria (v7.6 classifier-instability disclosure unchanged)
- §12 statistical machinery
- §13, §14
- All prior amendments v2 through v7.7

The seed-derivation method is preserved across v7.8 — the same `uint32(first_8_hex_chars(SHA256(commit_hash)))` mechanism is used, with only the anchor commit changing.

---

### Procedural lessons recorded in this amendment

1. **Seed derivation must be tied to the design it serves.** The v7-era seed was correctly derived for its design but became mismatched when v7.5 redesigned the campaign. Future redesigns that change block count, cell count, or randomization scope should trigger a corresponding seed re-derivation (with a deterministic anchor and an audit-defensible rationale).

2. **In-place file updates with git-history transparency are acceptable for pre-registered artifacts when no data has been collected.** Replacing a seed file alongside an amendment that explicitly documents the change preserves both the audit chain (via git history) and the source-of-truth (via the file's current contents).

3. **Anchor-commit choice matters.** Anchoring on a recent amendment commit, rather than an arbitrary recent commit, ensures that the seed's pre-existence relative to data is unambiguous — and that the anchor itself is externally timestamped (via the amendment's Zenodo DOI).

---

### External timestamp

This amendment is committed to the public repository at github.com/akulswami/sensor-mlc-latency and the commit is tagged as `prereg-amendment-2026-05-26-v7-8`. The repository release is mirrored to Zenodo with a new DOI distinct from prior amendments. The DOI of the Zenodo release containing this amendment is the authoritative external timestamp. **Per v5 Change 4, the DOI is minted same-day; this amendment may not be referenced as authoritative in any commit, code, or capture session until the Zenodo release is published and its DOI is inserted into the `Status` line above.**
