# 2026-09-21: R1 pt.2 affinity experiment

*Entry written from session artifacts (commits `8a3a03a`, `caae886`,
`eea5295`; block directories under
`data/training/latency-experiment/block-affinity-2026-09-21-*`;
`interrupts_before.txt` snapshots per block).*

## Goal

IEEE Sensors Letters decision SENSL-26-06-RL-0906 (2026-09-14, minor
revision) asked, as R1 pt.2, for a systematic investigation of the
block-sticky tri-modal latency distribution seen in the confirmatory
campaign's mlc-binary idle condition (modes at approximately
60/240/470 µs). This session investigates whether CPU core placement
of the pipeline process and/or IRQ routing for the sensor interrupt
is the cause.

All blocks below were run 2026-09-21 via
`code/orchestrator/run_stress_block.py --pipeline mlc-binary
--condition idle` (mlc001 used `--pipeline mlc`), against the Saleae
Logic Pro 8 (device `6F657C15C3EEE446`, automation port 10430).
jc_eff was 100.00% on every block.

## Pre-registration (both branches written before results)

- **Branch A**: if the pinned blocks (b001-b003) are unimodal AND the
  same-session unpinned control (ctrl001) is tri-modal, process/IRQ
  placement is confirmed as the cause of the campaign tri-modality.
- **Branch B**: if both pinned and unpinned blocks are unimodal,
  placement is excluded as the cause; report a systematic negative
  with remaining suspects.

**Branch B obtained.**

## Method

- Pinned condition (`--affinity-pin`, added in commit `8a3a03a`,
  default off): pipeline binary run under `taskset -c 2`; `servo_sweep`
  run under `taskset -c 0`; IRQ steering attempted by writing
  `smp_affinity` for every `i2c|gpio`-matching line in
  `/proc/interrupts` before the pipeline starts (documented outcome:
  writes to the Tegra GPIO-controller chained IRQs return `EIO`, i.e.
  non-steerable by design — see Verdict below).
- Three pinned mlc-binary/idle blocks (b001-b003, 300 s each) plus one
  same-session **unpinned** control (ctrl001, 300 s, mlc-binary/idle,
  no `--affinity-pin`) to isolate whether placement itself (not some
  other same-session difference) explains any change from the
  campaign's tri-modal pattern.
- One pinned mlc bank-switch trace block (mlc001, 300 s,
  `--pipeline mlc`) captured for the R1 pt.3 trace figure.
- One 60 s pinned smoke block (smoke3) run first as a quicker check
  before committing to the three full 300 s pinned blocks.

## Results

| Block | Duration | Condition | n | Median (µs) | IQR (µs) | frac_high |
|---|---|---|---|---|---|---|
| smoke3 (`--affinity-pin`) | 60 s | pinned | 10/12 included | 47.6 | — | — |
| b001 (`--affinity-pin`) | 300 s | pinned | 55 | 47.5 | (45.7, 50.6) | 0.000 |
| b002 (`--affinity-pin`) | 300 s | pinned | 60 | 46.9 | (45.2, 48.9) | 0.000 |
| b003 (`--affinity-pin`) | 300 s | pinned | 59 | 48.3 | (46.1, 50.1) | 0.000 |
| ctrl001 (unpinned, same session) | 300 s | unpinned | 58 | 48.3 | (44.9, 50.2) | 0.000 |
| mlc001 (`--pipeline mlc`, `--affinity-pin`) | 300 s | pinned | 59 | 481.8 | — | — (mlc trace block; R1 pt.3 figure source) |

Pooled across the four mlc-binary blocks (b001, b002, b003, ctrl001;
55+60+59+58=232 included trials): **232/232 trials < 150 µs.**

Campaign comparison (2026-05-26 unpinned mlc-binary idle, all 9
confirmatory blocks pooled): **159 low / 372 mid+high of 531 trials**.
Fisher exact test on pinned-vs-campaign high-latency-trial counts:
OR ≈ 0, p ≈ 1.3e-71.

## Verdict

**Process placement is EXCLUDED as the cause of the campaign
tri-modality.** The tri-modal pattern (modes ~60/240/470 µs) is
absent under both the pinned condition (b001-b003, mlc001's own
distribution aside) and the same-session unpinned control (ctrl001).
Since the unpinned same-session control also shows no tri-modality,
the difference between this session and the confirmatory campaign is
not explained by core/IRQ placement.

**IRQ placement is EXCLUDED as a variable.** All five matched IRQs
(numbers 228, 229, 230, 242/244, 278 — IRQ numbers vary between boots)
are Tegra GPIO-controller chained interrupts (`2200000.gpio` /
`c2f0000.gpio`), `smp_affinity_list` 0-5, and `smp_affinity` writes to
them return `EIO` (non-steerable by design). IRQ 278 = gpio line 85 =
the sensor INT1 handler; its counts land entirely on CPU 0 across
every block captured this session, i.e. routing was always CPU0
regardless of the `--affinity-pin` write attempt.

**Recorded environmental difference between sessions (low
confidence):** Pin 11's pinmux was found in SFIO mode on 2026-09-21
(see D1 root-cause below) and was reconfigured to GPIO mode for this
session. The May confirmatory-campaign session's pinmux state was not
recorded, but must have been GPIO-capable for the campaign's D1
measurements to have worked at all. Listed as a suspect for the
session-to-session difference; low confidence, unresolved.

## D1 channel root cause (resolved this session)

Early captures this session (`smoke`/`smoke2`, and the four
`block-affinity-btest-2026-09-21-*` pilot blocks) showed zero D1
activity — D1 held constant with no rising or falling edges at all.
Root cause: **pin 11 was in SFIO mode, not GPIO mode.** `gpiod` claims
on the line succeeded, but the pad never actually toggled — gpiod
success does not mean the pin is driving. After reconfiguring the
pinmux to GPIO and re-seating the probe, a square-wave gate test
(`code/analysis/sqw_gate.py`, driving `gpio_squarewave` on the
Jetson) passed: 989 edges and 500 level-holds at 5.06 ms in the 5 s
drive window. The floating-probe failure signature, for comparison,
was ~0.1 µs crosstalk glitches (2,296 of them in the failed `smoke2`
capture) — exactly what the gate's hold-duration criterion (requiring
holds in the 4.5-5.5 ms range) is designed to reject.

## Artifacts

- Orchestrator patch: commit `8a3a03a` (`--affinity-pin`, default off;
  `requirements.txt` logic2-automation entry).
- Block data (b001-b003, mlc001, incl. `saleae.sal`): commit `caae886`.
- ctrl001 extraction: commit `eea5295`.
- Block directories:
  `data/training/latency-experiment/block-affinity-2026-09-21-{smoke,smoke2,smoke3,b001,b002,b003,ctrl001,mlc001}-*`
- mlc001's `saleae.sal` is the source for the R1 pt.3 manuscript trace
  figure.

## Tooling notes from this session

- Logic 2 2.4.46 at `/opt/saleae/Logic2` on `akulswami-Asus`;
  automation via `logic2-automation==1.0.11` in `.venv` (now recorded
  in `requirements.txt`). All project Python must be invoked via
  `~/sensor-mlc-latency/.venv/bin/python3` — terminal pastes crossed
  windows repeatedly this session (fake `(.venv)` prompts, corrupted
  heredocs), which is what motivated the explicit-interpreter rule.
- `jetson_clocks` is volatile (per the 2026-05-25 finding); re-applied
  and verified per-block via the jc_eff ≥ 99% rule for every block
  this session (all blocks: jc_eff 100.00%).
- PCA9685 loses its configuration on every power cycle; re-initialized
  before this session per the runbook.
