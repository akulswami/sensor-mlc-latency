# §III. Experimental Setup

## III.A Hardware Platform

The edge platform is an NVIDIA Jetson Orin Nano Developer Kit running JetPack 6.2.2 (Ubuntu 22.04, kernel 5.15.148-tegra) on a 6-core ARM Cortex-A78AE complex. All measurements were collected under a custom `MAXN_SUPER_JC` nvpmodel (ID 3, defined and installed per pre-registration v7.6 [REF-PREREG]), which pins all six CPUs at min == max == 1728 MHz. Per-block jc-effectiveness (`jc_eff`, the fraction of `tegrastats` CPU-frequency samples at ≥ 1700 MHz across all six cores) was verified post-hoc against a 99.0% threshold; all 81 confirmatory blocks achieved 100% jc-effectiveness.

The sensor is an STMicroelectronics LSM6DSOX 6-axis IMU evaluation breakout (STEVAL-MKI197V1), connected via I²C bus 7 (pins 3 and 5 on the 40-pin header, address 0x6A). All three pipelines configure the accelerometer identically: `CTRL1_XL = 0x50` (ODR_XL = 208 Hz, FS_XL = ±2 g, LPF2 disabled). The Machine Learning Core (MLC) is enabled at 26 Hz with a custom 2-class motion/still classifier trained in STMicroelectronics MEMS Studio (75-sample windows; MLC config header `mlc_motion_w75.h`, auto-generated from the MEMS Studio JSON export). MLC output is routed to INT1.

Two GPIO lines on the Jetson 40-pin header are instrumented with a Saleae Logic Pro 8 (250 MS/s digital sampling): **D0** on pin 15 (INT1 input from the LSM6DSOX, `gpiochip0` line 85) and **D1** on pin 11 (decision-edge output written by the pipeline under test, `gpiochip0` line 112). The Saleae captures both channels into a single `.sal` per block, providing nanosecond-resolution wire-level timestamps independent of the Jetson's own clock.

Motion stimulus is delivered by an SG90 hobby servo driven by a PCA9685 PWM controller (I²C bus 1, address 0x41; the address-1 strap is set by a solder bridge on the A0 pad to avoid conflict with the on-board INA3221 at 0x40). The orchestrator commands the servo through `i2cset` over SSH and records stimulus-edge timestamps to the Jetson's monotonic clock for post-hoc alignment with the Saleae capture.

## III.B Pipelines Under Test

Three pipelines are compared end-to-end:

**(a) host:** software classifier on the Jetson (`host_pipeline_parity`). Polls the LSM6DSOX accelerometer FIFO over I²C at the configured 208 Hz, assembles a 75-sample sliding window, and applies a decision-tree classifier (variance of accelerometer L2-norm against a calibrated threshold) to produce a motion/still verdict. The decision GPIO (D1) is toggled on every state change of the classifier output.

**(b) mlc:** standard MLC bank-switch read protocol (`latency_test_mlc_w75`). On every INT1 rising edge (D0), the host performs the three I²C transactions required to read `MLC0_SRC` (write `FUNC_CFG_ACCESS = 0x80` to enter the embedded-function bank, read `MLC0_SRC = 0x70`, write `FUNC_CFG_ACCESS = 0x00` to return to the user bank), and writes D1 if the binary classifier output has changed since the previous read.

**(c) mlc-binary:** zero-I²C-transaction variant (`latency_test_mlc_binary_w75`). On every INT1 rising edge, the host unconditionally toggles D1 without reading `MLC0_SRC`. This is valid for the 2-class case where every interrupt represents a binary state change, and provides a kernel/gpiod-only latency floor against which the I²C-read overhead in (b) can be measured.

All three binaries share the same I²C bus arbitration, the same gpiod GPIO write path, and the same accelerometer configuration; they differ only in what happens after an interrupt arrives.

## III.C Stress Conditions

Three operating conditions are tested:

- **idle:** no background load. CPUs are pinned by `MAXN_SUPER_JC` but otherwise unoccupied by the test workload.
- **i2c-contention:** three concurrent background processes (`i2c_hammer`) continuously read non-MLC registers from the LSM6DSOX (WHO_AM_I, CTRL1_XL, OUTX_L_A) on bus 7, contending with the test pipeline's bus access. Hammer-process count is verified at block start.
- **stress:** `stress-ng` (pinned version 0.13.12) saturates all six CPUs via `--cpu 6 --cpu-method matrixprod`, which performs sustained 3×3 matrix-product arithmetic. Per-CPU `tegrastats` confirms saturation at block start.

## III.D Measurement and Statistical Protocol

Each (pipeline, condition) cell consists of 9 blocks of 300 s each. Block order across the 81-block campaign is randomized via a pre-registered, deterministic shuffle seeded by 1990185399 (derived as `uint32(first_8_hex_chars(SHA256(git_rev_parse_full_sha(v7.7_anchor_commit))))`, with the v7.7 anchor commit being `f5bd702`, recorded in pre-registration v7.8 [REF-PREREG]). Within each block, the stimulus orchestrator delivers 60 candidate transitions; each transition is paired with the next rising edge on D0 (interrupt arrival) and D1 (decision write), and latency is computed as t(D1) − t(D0).

Trial-level inclusion criteria (pre-registered in v7.4 [REF-PREREG]) require exactly one D1 rising edge within the (t_stim, t_next_stim] window. Trials violating this criterion are categorized by `exclusion_reason` and reported separately as a classifier-stability outcome (§V.D). Across the campaign, **4,770 of 4,860 candidate trials (98.15%) were included** for latency analysis. No cell exceeded the pre-registered 10% per-cell exclusion ceiling; the highest exclusion was mlc/idle at 2.78%.

Statistical tests are described in §IV; all tests were specified in advance in the pre-registration with multiplicity-correction strategy (Holm-Bonferroni across the confirmatory hypothesis family, TOST equivalence reported separately). Confidence intervals on the Hodges-Lehmann shift estimator are computed by 10,000-iteration percentile bootstrap.
