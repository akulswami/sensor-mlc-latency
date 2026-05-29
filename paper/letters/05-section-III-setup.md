# §III. Experimental Setup

## III.A Hardware Platform

The edge platform is an NVIDIA Jetson Orin Nano Developer Kit (JetPack 6.2.2, kernel 5.15.148-tegra, 6-core ARM Cortex-A78AE). All measurements ran under a custom MAXN_SUPER_JC nvpmodel (v7.6 [4]) pinning all six CPUs at 1728 MHz; per-block jetson_clocks effectiveness (tegrastats samples ≥ 1700 MHz) was ≥ 99%, with all 81 blocks at 100%.

The sensor is an STMicroelectronics LSM6DSOX 6-axis IMU breakout (STEVAL-MKI197V1) on I²C bus 7 (pins 3/5, address 0x6A), the bus running at 400 kHz (Fast Mode, Jetson default). All three pipelines configure the accelerometer identically (CTRL1_XL = 0x50: 208 Hz, ±2 g, LPF2 off). The MLC runs at 26 Hz with a custom 2-class motion/still classifier (75-sample windows, config mlc_motion_w75.h) trained in ST MEMS Studio, with output routed to INT1.

Two Jetson GPIO lines are instrumented with a Saleae Logic Pro 8 (250 MS/s): **D0** on pin 15 (INT1 from the LSM6DSOX, gpiochip0 line 85) and **D1** on pin 11 (decision edge from the pipeline under test, line 112). This yields nanosecond-resolution wire-level timestamps independent of the Jetson clock and of SSH command jitter (both D0 and D1 are wire edges). Motion stimulus is an SG90 servo on a PCA9685 PWM controller (I²C bus 1, address 0x41 via an A0 solder bridge to avoid the on-board INA3221 at 0x40), commanded over SSH.

## III.B Pipelines Under Test

Three pipelines are compared end-to-end, sharing the same I²C arbitration, gpiod write path, and accelerometer configuration, and differing only in what happens after an interrupt arrives:

**(a) host** (host_pipeline_parity): polls the accelerometer at 208 Hz, assembles a 75-sample window, and applies a decision-tree classifier (variance of accelerometer L2-norm against a calibrated threshold), toggling D1 on every output state change.

**(b) mlc** (latency_test_mlc_w75): on each INT1 edge, performs the three I²C transactions of the bank-switch read (write FUNC_CFG_ACCESS = 0x80 to enter the embedded bank, read MLC0_SRC = 0x70, write FUNC_CFG_ACCESS = 0x00 to return), writing D1 if the output changed.

**(c) mlc-binary** (latency_test_mlc_binary_w75): on each INT1 edge, unconditionally toggles D1 without reading MLC0_SRC, valid for the 2-class case and providing a kernel/gpiod-only latency floor against which (b)'s I²C-read overhead is measured. Because this study measures decision-delivery latency rather than classification accuracy, parity is enforced at the level of identical accelerometer configuration, window length, and binary motion/still decision semantics; the mlc-binary condition isolates the non-classifier read path.

## III.C Stress Conditions

Three conditions are tested. **idle**: CPUs pinned but otherwise unloaded. **i2c-contention**: three concurrent i2c_hammer processes continuously read non-MLC registers from the LSM6DSOX on bus 7, contending for bus access. **stress**: stress-ng 0.13.12 saturates all six CPUs (--cpu 6 --cpu-method matrixprod). Hammer-process count and CPU saturation are verified at block start.

## III.D Measurement Protocol

Each (pipeline, condition) cell comprises 9 blocks of 300~s. Block order across the 81-block campaign follows a pre-registered deterministic shuffle (seed 1990185399 [4]). Within each block the orchestrator delivers 60 candidate transitions; latency is t(D1) − t(D0). Inclusion (pre-registered v7.4) requires exactly one D1 rising edge per stimulus window; violations are categorized and reported as a classifier-stability outcome (§V.D). Across the campaign, 4,770 of 4,860 trials (98.15%) were included, no cell exceeding the pre-registered 10% exclusion ceiling.
