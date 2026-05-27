# Section I: Introduction (final draft)

**Anchored to:** Variant C abstract above
**Target length:** ~0.5 page (~280 words including refs)

---

## I. Introduction

Inertial measurement units (IMUs) with embedded Machine Learning Cores (MLCs) are increasingly deployed in edge applications including wearables, industrial monitoring, and biomedical instrumentation [REF-ST-LSM6DSOX]. The MLC paradigm — running a decision-tree classifier inside the sensor and exposing only a binary or multi-class output register to the host — is consistently framed as a latency and energy advantage over host-side classification [REF-AN5259, REF-RAZMI-2026]. The implicit assumption is that on-sensor inference is unconditionally lower-latency than host-side inference because the host need only poll a single register; the sensor handles the classification work.

This assumption is rarely tested with wire-level instrumentation. Vendor application notes characterize the MLC's architecture and per-class accuracy but do not report end-to-end stimulus-to-decision latency [REF-AN5259]. Recent work using MLCs for safety-critical applications, such as exoskeleton control loops [REF-RAZMI-2026], cites on-sensor inference as a latency advantage without measuring wire-level latency. The gap between "the classification is correct" and "the classification reaches the host in time to be acted upon" is precisely the failure mode that conventional functional testing misses.

In this work, we measure wire-level stimulus-to-decision latency for three pipelines on a representative edge platform (NVIDIA Jetson Orin Nano + STMicroelectronics LSM6DSOX over I²C) using a Saleae Logic Pro 8 logic analyzer: (a) a host-side decision-tree classifier reading raw accelerometer data, (b) the standard MLC bank-switch read protocol, and (c) an MLC binary-fast variant that omits the I²C read entirely, toggling the decision GPIO unconditionally on every MLC interrupt event (valid for a 2-class configuration where every interrupt represents a binary state change). Measurements span three stress conditions: idle, I²C bus contention from N=3 concurrent register-read processes on bus 7, and CPU saturation via stress-ng. The full experimental protocol, including all measurement criteria, exclusion rules, and statistical tests, was pre-registered with eight externally-timestamped amendments on Zenodo prior to confirmatory data collection [REF-PREREG].

**The principal finding is that the host pipeline exhibits lower median wire-level latency than the standard MLC bank-switch pipeline under all tested conditions, with the three-transaction I²C read protocol — not the silicon's classification — being the dominant latency contributor.** We additionally document the MLC's previously-unreported 706.5 ms intrinsic decision cadence and identify multimodal latency distributions in both MLC pipelines whose origin warrants kernel-level investigation.

The contributions are:
1. The first pre-registered wire-level latency characterization of the LSM6DSOX MLC versus host-side inference on a representative edge platform, spanning 4,712 included trials across nine pipeline×condition cells.
2. Empirical identification of the I²C read-protocol overhead as the dominant latency contributor — a finding that generalizes to any platform using bank-switched register access for on-sensor ML output.
3. Documentation of the MLC's 706.5 ms intrinsic decision cadence (one quarter of the 75-sample × 26 Hz window), previously unreported in vendor literature.
4. A methodology contribution: pre-registration with externally-timestamped Zenodo DOIs as an audit-defensible framework for sensor-measurement claims, with implications for verification of safety-critical edge ML deployments where wire-level latency is a system-safety property.
