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
