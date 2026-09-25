# S4 Evidence Summary — On-Wire I²C Verification and Latency Decomposition
Manuscript SENSL-26-06-RL-0906 — evidence blocks captured 2026-09-24/25 under nvpmodel
mode 3 (MAXN_SUPER_JC), the measurement configuration required by pre-registration v7.6
Change 2 (Zenodo DOI 10.5281/zenodo.20400025). All four blocks pass the jc_eff gate at
100.00% (threshold 99%). Block identity verified by Saleae trigger-sample fingerprinting
against capture-start order (40/40, 35/35, 31/31, 34/34, 9/9 matches).
Raw captures, logs, and verification code for every block cited here are archived at
Zenodo DOI 10.5281/zenodo.22950121 (evidence package v1.1.0-r1).

## Protocol verification (three-transaction bank-switch read)
Every decision window in every mlc block contains the complete sequence on the wire:
  W [0x01, 0x80]  (FUNC_CFG_ACCESS: embedded-functions bank ON)
  W [0x70] + Sr   (register pointer: MLC0_SRC; repeated-start combined read)
  R        ->     (MLC0_SRC value: 0x04 = motion, 0x00 = still)
  W [0x01, 0x00]  (bank OFF)

| block (regime)              | windows | triples verified | reads (0x04/0x00) |
|-----------------------------|---------|------------------|-------------------|
| b005 mlc-idle (pegged)      | 62      | 62/62            | 31 / 31           |
| b006 mlc-i2c-cont. (pegged) | 60      | 60/60            | 30 / 30           |
| b007 mlc-stress (pegged)    | 60      | 60/60            | 30 / 30           |
| b001 mlc-idle (dynamic)     | 60      | 60/60            | 30 / 30           |
| b002 mlc-i2c-cont. (dynamic)| 60      | 60/60            | 30 / 30           |
| b003 mlc-stress (dynamic)   | 60      | 60/60            | 30 / 30           |
| b004/b008 mlc-binary        | 12/14   | 0 (no per-decision bus traffic; negative control) | — |

Negative control: b004 and b008 show zero 0x6A frames inside decision windows; all bus
traffic is confined to the init/config phase (209 frames, 5 bank-switches, t <= ~6 s).

## Latency decomposition (medians, ms; D0 = INT1 rise, D1 = decision GPIO strobe)
| block              | sched (D0->1st byte) | bus triple | triple end->D1 | total D0->D1 |
|--------------------|----------------------|------------|----------------|--------------|
| b005 idle pegged   | 0.059                | 0.391      | 0.029          | 0.479        |
| b006 cont. pegged  | 0.290                | 0.952      | 0.031          | 1.285        |
| b007 stress pegged | 0.080                | 0.404      | 0.033          | 0.519        |
| b008 binary pegged | —                    | —          | —              | 0.046        |
| b001 idle dynamic  | 0.576                | 0.793      | 0.046          | 1.510        |
| b002 cont. dynamic | 0.326                | 1.070      | 0.049          | 1.434        |
| b003 stress dynamic| 0.094                | 0.420      | 0.037          | 0.551        |
| b004 binary dynamic| —                    | —          | —              | 0.700        |
| b018 May confirm.  | (3-channel capture)  | —          | —              | 0.848        |

Decomposition closes per block: sched + triple + strobe = total within ~0.02 ms.

## Contention findings
- Hammer = 3x i2c_hammer processes issuing WHO_AM_I (reg 0x0F -> 0x6C) reads against the
  sensor's own address 0x6A on bus 7; kernel serializes at transfer granularity.
- Exactly 6 hammer transfers interleave inside each pipeline triple (median 6, max 6)
  in BOTH one-hammer (b002) and three-hammer (b006) floods — interleaving is bounded by
  bus bandwidth, not queue depth.
- Contention cost at pegged clocks: bus phase 0.391 -> 0.952 ms (+0.56), sched 0.059 ->
  0.290 ms (+0.23); total +0.81 ms.

## Clock-regime findings (tegrastats-documented)
- Confirmatory campaign (2026-05-26): all cores pegged at 1728 MHz (jc_eff = 100%).
- 2026-09-24 blocks b001-b004: dynamic clocking (729 MHz idle); jc_eff 5.8-97.8% ->
  gate FAIL, retained as labeled dynamic regime only.
- 2026-09-24/25 blocks b005-b008: MAXN_SUPER_JC; jc_eff = 100%, included = true.
- Dynamic-idle penalty vs pegged-idle: +1.03 ms median (frequency ramp + wakeup),
  uncorrelated with idle-gap duration (r = 0.024) — scheduler/frequency jitter, not
  progressive C-state depth.

## Known anomalies logged
- b005: 62 verified events vs scripted 60 (31/31 read split); two extra motion/still pairs.
- Pegged blocks show 86-96 INT1 pulses vs 60 in dynamic/May blocks (extras <50 ms after a
  scripted event, clean 9.007 ms widths): stimulus (servo_sweep) is CPU-frequency-sensitive.
- b006/b002 windows lost to INT1 glitch contamination near pulse falls (probe-lead
  coupling; 5 ms pulse-width filter applied in analysis).
