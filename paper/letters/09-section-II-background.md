# §II. Background and Related Work

## II.A On-sensor inference in MEMS IMUs

Embedded machine learning in 6-axis microelectromechanical systems (MEMS) IMUs is now a standard product feature. STMicroelectronics introduced the MLC in the LSM6DSOX [2], a configurable decision-tree engine running at the accelerometer ODR (26 Hz in our deployment) that consumes features over sliding sample windows and emits class labels the host reads via I²C bank-switched registers. Successor parts (LSM6DSV16X, LSM6DSO32X) retain this architecture, and competing vendors offer analogues (Bosch BHI260AP, Analog Devices ADXL367). The consistent commercial messaging is that on-sensor inference reduces data-bus traffic, host CPU utilization, and end-to-end latency. The first two claims are testable from system-level metrics; the third is testable only with wire-level instrumentation, which is rarely performed.

## II.B Wire-level latency in safety-critical edge ML

A growing class of edge-AI applications depends on bounded stimulus-to-actuation latency: wearable exoskeleton control [3], industrial predictive-maintenance alarms, healthcare arrhythmia and fall detection. In each, "the classification is correct" is necessary but not sufficient; "the classification reaches the actuator in time" is the safety-relevant property. Yet vendor application notes report MLC architecture and accuracy without end-to-end latency [2], and independent characterizations measure host-side interrupt-to-action latency without measuring how the read protocol contributes to the wire-level delay. That gap, between functional and timing correctness, is the failure mode conventional functional testing misses.

## II.C Pre-registration in sensor measurement

Pre-registration, the externally-timestamped specification of hypotheses, exclusion criteria, tests, and multiplicity correction before data collection, is established in clinical trials and common in psychology and machine learning but rare in sensor measurement. We apply it here: externally-timestamped Zenodo DOIs provide a chain of custody distinguishing pre-specified hypotheses from post-hoc rationalization, with all methodology changes recorded as dated amendments against the public repository.
