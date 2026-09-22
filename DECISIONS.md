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

7559266 (HEAD -> main, origin/main) Add pre-registration document for MLC vs. host latency comparison

---

## 2026-09-21: R1 pt.2 affinity experiment — placement excluded

**(1) Affinity hypothesis falsified.** The R1 pt.2 investigation into whether CPU core placement or IRQ routing explains the confirmatory campaign's block-sticky tri-modal mlc-binary/idle latency distribution (modes ~60/240/470 µs) found placement excluded as the cause: the pinned blocks (b001-b003, `--affinity-pin`) and a same-session unpinned control (ctrl001) are both unimodal, with 232/232 trials under 150 µs. The pre-registered confirmatory campaign Table 1 is unchanged — this is a supplementary investigation on 2026-05-26 campaign data, not a re-run of the pre-registered measurements. See `docs/lab-notebook/2026-09-21-affinity-experiment.md` and pre-registration amendment v7.12.

**(2) Tegra GPIO chained IRQs are non-steerable.** All five matched IRQs (228, 229, 230, 242/244, 278 — numbers vary between boots) are Tegra GPIO-controller chained interrupts (`2200000.gpio` / `c2f0000.gpio`); `smp_affinity` writes to them return `EIO`. Never attempt `smp_affinity` steering on these lines in future session designs — it is a no-op by hardware/kernel design, not a configuration gap.

**(3) Pin 11 must be verified GPIO, not SFIO, every session.** The 2026-09-21 session's D1-channel failure (zero D1 edges captured) traced to pin 11 being in SFIO pinmux mode; `gpiod` claims on the line succeeded even though the pad never toggled. Verify pin 11's pinmux mode every session via `code/analysis/sqw_gate.py`.

**(4) Square-wave gate adopted as a mandatory pre-block D1 check.** `code/analysis/sqw_gate.py` drives a known 100 Hz square wave on D1 and requires ≥400 edges and ≥400 level-holds in the 4.5-5.5 ms range in a 5 s window to pass. This is now a mandatory pre-block check for the D1 channel, catching both the SFIO-pinmux failure mode and floating-probe crosstalk (which shows as ~0.1 µs glitches, rejected by the hold-duration criterion).

**(5) All orchestrator invocations use the explicit `.venv` interpreter.** `~/sensor-mlc-latency/.venv/bin/python3`, not a bare `python3` — terminal pastes crossed windows repeatedly in the 2026-09-21 session (fake `(.venv)` prompts, corrupted heredocs).
