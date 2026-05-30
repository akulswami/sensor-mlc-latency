# sensor-mlc-latency

Wire-level latency comparison of on-sensor Machine Learning Core (MLC) inference vs. on-host inference for IMU-based edge AI pipelines under system stress.

**Target venue:** IEEE Sensors Letters (4-page format)

**Status:** Confirmatory campaign complete; manuscript finalized and submitted to arXiv. Targeting IEEE Sensors Letters (May 2026).

## Overview

This work compares two inference pipelines for IMU-based classification on an NVIDIA Jetson Orin Nano:

1. **On-sensor MLC pipeline:** classification performed by the LSM6DSOX's embedded Machine Learning Core, with class label read by the host
2. **On-host pipeline:** raw IMU samples streamed to the Jetson, classification performed in software

Wire-level latency for both pipelines is measured externally via Saleae Logic Pro 8 capture of the sensor data-ready interrupt and post-decision GPIO actuation edge.

## Hardware

- NVIDIA Jetson Orin Nano Developer Kit
- Adafruit LSM6DSOX 6-DoF IMU breakout (PID 4438)
- Saleae Logic Pro 8

## Repository structure

- `paper/` — manuscript source and figures
- `code/` — measurement harness, MLC configurations, analysis notebooks
- `data/` — captured measurements and processed outputs
- `docs/` — hardware setup, measurement protocol, pre-registration, lab notebook
- `env/` — environment versions for reproducibility

## Reproducibility

All experimental decisions are logged in `DECISIONS.md`. Daily progress is logged in `docs/lab-notebook/`. Pre-registration of the experimental design is in `docs/pre-registration.md` and timestamped via the Git commit history.
