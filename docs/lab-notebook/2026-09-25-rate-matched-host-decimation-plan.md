# Pre-registration amendment v7.14 (2026-09-25): rate-matched host-decimation cells (Reviewer 1, Point 1)

**Status of this document.** Committed to the sensor-mlc-latency repository and
Zenodo-timestamped BEFORE any host-decimation data is collected, per the standing
rule established in amendment v7.13 (2026-09-22). All analysis criteria, success
thresholds, and interpretation branches below are pre-registered in the strict
sense for the new cells defined here. Nothing in this amendment re-labels any
previously collected data or previously written working note.

**Trigger.** Reviewer 1, Point 1 on manuscript SENSL-26-06-RL-0906 (Revision 1):
the host pipeline consumes accelerometer data at 208 Hz (75-sample window = 360 ms)
while the MLC operates at 26 Hz (75-sample window = 2.88 s); the reviewer holds
that the 2.1–2.3× D0→D1 advantage is confounded by this mismatch and "requires a
re-run experiment with the host decimated to a 26 Hz equivalent."

## 1. New cells

Three new blocks, one per load condition, mirroring the existing Table 1 structure:

| cell | pipeline | load | condition reference |
|------|----------|------|---------------------|
| HD-idle | host-decimated | none | mirrors block-b005-mlc-idle |
| HD-i2c  | host-decimated | 3× i2c_hammer, bus 7, addr 0x6A | mirrors block-b006-mlc-i2c-contention |
| HD-stress | host-decimated | stress-ng --cpu 6 matrixprod | mirrors block-b007-mlc-stress |

Stimulus: the same servo_sweep script, 60 events per block (30 motion / 30 still).
Capture: same Saleae configuration as the 2026-09-24/25 campaign (50 MS/s,
threshold "3.3+ Volts", 200 ns glitch filters on SDA/SCL; ch0 = INT1, ch1 =
decision GPIO, ch2 = servo PWM, ch3 = SDA, ch4 = SCL), so that wire-level
decomposition is possible for the host-decimated pipeline exactly as for the
mlc pipeline.

**Measurement configuration.** nvpmodel mode 3 (MAXN_SUPER_JC) is required, per
amendment v7.6 Change 2. The jc_eff gate (≥99% of tegrastats CPU-frequency samples
≥1700 MHz) applies unchanged; blocks failing the gate are excluded from the
primary analysis and reported as such.

## 2. Decimation semantics (pre-committed, matching the reviewer's arithmetic)

The host pipeline reads the sensor FIFO at 208 Hz as before, but the inference
path processes **every 8th sample** (208/26 = 8), giving an effective decision
input rate of 26 Hz. A 75-sample decision window therefore fills in 2.88 s of
wall-clock time, matching the MLC's ODR and window length exactly. Sensor
configuration (ODR 208 Hz, FS, FIFO) is unchanged; only the host-side consumption
pattern changes. D0 and D1 semantics are unchanged from the registered protocol.

## 3. Comparison arm (already frozen)

The MLC reference arm is **not** re-collected. It consists of blocks b005/b006/b007
captured 2026-09-24/25 under mode 3, all passing the jc_eff gate at 100.00%, with
raw captures publicly archived at Zenodo DOI 10.5281/zenodo.22950121 — timestamped
and immutable BEFORE the first host-decimation capture. The comparison is therefore
immune to post-hoc selection on the MLC side by construction.

## 4. Hypotheses and success criteria (pre-committed)

- **H-rate-1 (primary, directional):** median D0→D1 of the host-decimated pipeline
  is lower than median D0→D1 of the MLC bank-switch pipeline in each of the three
  load conditions. The paper's rate-matched claim succeeds iff this ordering holds
  in all three cells. **No magnitude threshold is pre-committed**; the rate-matched
  speed ratio is reported descriptively, and it may be smaller than the
  unmatched-rate 2.1–2.3× figure. If the ordering fails in any cell, the manuscript
  claim is narrowed to the cells where it holds and the failure is reported.
- **H-rate-2 (secondary, descriptive):** the decomposition of host-decimated D0→D1
  (scheduling, bus transactions, strobe) is reported per window, using the same
  stdlib-only verification code (code/analysis/i2c_window_decode.py) archived at
  the DOI above.

## 5. Reporting (pre-committed)

Per cell: n, exclusions with reasons, median, IQR, p95, p99, max (folding in
Reviewer 2's tail-statistics request for these cells). Both the rate-matched
comparison and the original unmatched-rate comparison appear in the manuscript;
the headline number is the rate-matched one.

## 6. Known anomalies carried forward (logging obligations)

- b005 exhibited 62 INT1 events vs. 60 scripted (extra pulses <50 ms after scripted
  events, clean 9.007 ms widths) — stimulus CPU-frequency sensitivity. Event counts
  for the new blocks are logged and any deviation from 60 is reported, not silently
  filtered.
- INT1 glitch contamination near falling edges (probe-lead coupling) — the ≥5 ms
  pulse-width filter in the extraction pipeline applies unchanged.
- Any SWAP or memory-configuration drift on the bench host is logged.

## 7. Out of scope for this amendment

MCU-host replication (Reviewer 1, Point 5) and host-vs-MLC energy measurement are
not part of these cells. No energy-measurement plan is pre-registered for this
revision and none will be claimed; energy is addressed as an explicit scope
limitation and future work. MCU replication is likewise future work and will be
stated as such.
