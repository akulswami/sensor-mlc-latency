# Decision Log

Append-only record of significant project decisions. Entries are dated and not revised; corrections are added as new entries.

---

## 2026-04-29: Project scope frozen

Paper target: IEEE Sensors Letters, 4-page format.

Framing: On-sensor MLC vs. on-host inference, wire-level latency comparison under CPU stress.

Single platform (Jetson Orin Nano), single sensor (LSM6DSOX), single stress dimension (CPU contention via stress-ng). Statistical analysis to be pre-registered before any experiment runs.

Sequential strategy: this Letter first; full cross-tier study targeted to IEEE Access in subsequent paper.

## 2026-04-29: Sensor selected — Adafruit LSM6DSOX (PID 4438)

Original target was the LSM6DSV16X but it was out of stock at all major distributors at the time of order.

LSM6DSOX selected because:
- In stock at DigiKey, ships immediately
- Has full Machine Learning Core (MLC) and Finite State Machine (FSM)
- Supported in ST MEMS Studio for MLC programming
- Adafruit and ST publish well-documented driver libraries

Tradeoff accepted: older chip, no Sensor Fusion Low Power (SFLP) on-chip output. The MLC vs. host comparison is unaffected by this tradeoff.

## 2026-04-29: Repository initialized

Private GitHub repository created. Will remain private until submission to IEEE Sensors Letters.
