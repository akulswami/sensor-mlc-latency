# §II. Background and Related Work

## II.A On-sensor inference in MEMS IMUs

Embedded machine learning in 6-axis microelectromechanical systems (MEMS) IMUs is now a standard product feature. STMicroelectronics introduced the MLC in the LSM6DSOX [2], a configurable decision-tree engine running at the accelerometer ODR (26 Hz in our deployment) that consumes features over sliding sample windows and emits class labels the host reads via I²C bank-switched registers. Successor parts (LSM6DSV16X, LSM6DSO32X) retain this architecture, and competing vendors offer analogues (Bosch BHI260AP, Analog Devices ADXL367). The consistent commercial messaging is that on-sensor inference reduces data-bus traffic, host CPU utilization, and end-to-end latency. The first two claims are testable from system-level metrics; the third is testable only with wire-level instrumentation, which is rarely performed.

## II.B Wire-level latency in safety-critical edge ML

Safety-critical edge applications require bounded stimulus-to-actuation latency, not merely correct classification. Existing MLC documentation emphasizes architecture and accuracy [2], while independent characterizations rarely isolate the sensor read protocol's contribution to decision-delivery delay.

## II.C Pre-registration in sensor measurement

Pre-registration is used here to separate pre-specified sensor-measurement hypotheses from post-hoc interpretation.
