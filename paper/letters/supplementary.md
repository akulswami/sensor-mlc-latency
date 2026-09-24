# Supplementary Material

*Wire-Level Interrupt-to-Decision Latency of On-Sensor MLC versus Host Inference on the NVIDIA Jetson Orin Nano: A Pre-Registered Measurement Study*

Not part of the 4-page Letters build (`build_tex.py` does not read this file). Referenced from the main text by short pointer sentences in §V.B and §VI.B.

---

## S1. Full percentile table (extends Table I)

Table I in the main text reports only median and IQR per pipeline×condition cell, to fit the page budget. The full table, including p95, p99, max, and mean, is reproduced here.

**Wire-Level Latency per Pipeline × Condition (µs)**

Latency = t(D1 rising) − t(D0 rising). Each cell aggregates 9 blocks of 300 s. n = included trials (4,770 of 4,860 candidates, 98.15%). IQR = interquartile range (p25–p75). All values µs except n. p95/p99/max computed via linear interpolation (numpy default); see `code/analysis/compute_percentile_table.py` and `data/processed/confirmatory-2026-05-26/percentile_table.csv`.

| Pipeline | Condition | n | Median | IQR | p95 | p99 | Max | Mean |
|----------|-----------|---:|------:|----:|----:|----:|----:|-----:|
| host | idle | 536 | 321.7 | 319.7–326.3 | 347.3 | 506.3 | 642.9 | 328.8 |
| host | i2c-cont. | 529 | 574.5 | 547.8–599.0 | 639.5 | 662.3 | 854.1 | 570.4 |
| host | stress | 532 | 345.0 | 342.0–348.9 | 361.2 | 400.6 | 3504.8 | 351.3 |
| mlc | idle | 525 | 681.5 | 505.4–1086.8 | 1779.7 | 2120.6 | 2604.5 | 866.6 |
| mlc | i2c-cont. | 532 | 1325.4 | 1283.7–1370.8 | 1536.2 | 1675.4 | 1904.8 | 1333.2 |
| mlc | stress | 527 | 546.1 | 535.9–557.0 | 579.5 | 879.1 | 3868.2 | 560.6 |
| mlc-binary | idle | 531 | 231.9 | 61.8–246.2 | 485.3 | 654.2 | 723.9 | 236.7 |
| mlc-binary | i2c-cont. | 527 | 49.4 | 46.9–53.1 | 246.7 | 272.1 | 289.3 | 64.5 |
| mlc-binary | stress | 531 | 70.2 | 66.9–73.0 | 78.4 | 197.5 | 253.7 | 72.0 |

*Note: The mlc/idle mean (866.6) exceeding its median (681.5), and the wide mlc/idle IQR, reflect the multimodal structure discussed in §V.B. The mlc-binary pipeline performs zero I²C transactions on the decision path, isolating the kernel/gpiod latency floor.*

---

## S2. Host vs. MLC platform power (post-hoc; referenced from §VI.B)

Jetson platform power (VDD_CPU_GPU_CV, INA3221) differs between host and MLC pipelines by +31.1 mW [27.8, 34.4] at idle (p ≈ 8.4×10⁻⁹²) and +7.3 mW under I²C contention (p ≈ 5.5×10⁻⁸). This comparison was added post-hoc in response to review; per the pre-registration's standing rule (v7.13), it is labeled as such rather than presented as part of the original confirmatory design. Under CPU stress, the 95% CI spans [−28.8, 14.6] mW and includes zero despite p ≈ 1.4×10⁻⁸ — expected at this sample size, where MWU is sensitive to distributional differences beyond central tendency; the CI, not the p-value, is the practically relevant statistic here. VDD_IN replicates the idle effect at +37.3 mW [33.2, 41.4]. These are whole-platform measurements, not an isolated host-classifier-vs-MLC comparison — the sensor's own power draw is not separately instrumented.

---

## S3. Candidate mechanisms for the idle multimodal distribution (referenced from §V.B)

We do not present a confirmed mechanism. Candidate explanations include: (a) idle-state I²C bus arbitration on the Jetson's `i2c-tegra194` driver having multiple equilibrium timings between conflicting wake-up paths, (b) the gpiod write path through `/dev/gpiochip0` traversing different kernel call sequences depending on whether the underlying chardev poll mechanism is in steady-state or recently-armed, or (c) some interaction between the MLC's 706.5 ms internal cadence (§V.C) and the kernel's microsecond-resolution interrupt-arrival timing. Distinguishing these requires ftrace instrumentation of the I²C driver and the gpiochip event flow at the kernel level, which lies outside the scope of this wire-level study.
