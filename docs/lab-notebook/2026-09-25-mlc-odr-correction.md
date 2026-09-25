# Pre-registration amendment v7.15 (2026-09-25): correction to v7.14 — host-decimation cells withdrawn pre-collection; on-wire verification establishes MLC ODR = 104 Hz

**Status of this document.** Committed to the sensor-mlc-latency repository and
Zenodo-timestamped BEFORE any data collection under amendment v7.14. **No data was
collected under v7.14.** Per the standing rule of v7.13 (2026-09-22), this is a
pre-collection correction, recorded in the same manner as v7.13's correction to
v7.12. v7.14 remains in the chain unaltered as a record of what was planned and
why it was withdrawn.

## 1. What v7.14 assumed

v7.14 planned three "host-decimation" re-run cells on the premise — taken from the
manuscript text and repeated by Reviewer 1, Point 1 — that the host pipeline's
decision input is 208 Hz with a 75-sample (360 ms) window while the MLC operates
at 26 Hz with a 75-sample (2.88 s) window, making the headline D0→D1 comparison
rate-confounded.

## 2. What on-wire verification established (2026-09-25)

Init-phase I2C decode of the archived raw captures (blocks b005 mlc-idle and b008
mlc-binary, both in evidence package Zenodo DOI 10.5281/zenodo.22950121; decode
reproducible with the archived stdlib-only decoder applied to the first ~8 s of
each capture) shows the actual register writes that configured the sensor in both
pipelines, in both the 2026-09-24/25 campaign and, by identical init sequence, the
confirmatory campaign:

- **EMB_FUNC_ODR_CFG_C (60h) = 0x35.** Per the LSM6DSOX datasheet (Table 321),
  MLC_ODR[1:0] occupies bits [5:4]; 0x35 = 0b00110101 → MLC_ODR = 0b11 = **104 Hz**
  (AN5259 Table 1: 00 = 12.5, 01 = 26, 10 = 52, 11 = 104 Hz). The mandatory
  set-to-1 bits (2 and 0) are correctly preserved.
- **CTRL1_XL (10h) = 0x50** → sensor ODR **208 Hz** (previously verified).
- **MD1_CFG (5Eh) = 0x02** → INT1_MLC routing (previously verified).

The host parity core decimates the 208 Hz stream 2:1 (`pc_step()` in
code/jetson/host_inference/parity_core.c; tree_w75.json: `mlc_odr_hz: 104,
decimation_ratio: 2`), giving a host decision input of 104 Hz with a 75-sample
window.

**Consequence:** both pipelines decide on 75-sample windows at 104 Hz
(≈ 721.5 ms nominal). The comparison measured in the campaign was rate-matched
and window-matched by construction — this matching is the design purpose of the
parity core and the parity gate. v7.14's premise is false; its three cells are
withdrawn.

## 3. Correction of the cadence explanation

The measured MLC decision cadence (706.1 ± 0.5 ms, v7.6-era text) is the **full
75-sample window at the actual MLC ODR** (721.5 ms nominal at 104 Hz; observed
706.1 ms implies an effective ODR of ~106 Hz, within the silicon's ODR tolerance).
The explanation in the v7.6-era pre-registration text — "one quarter of the
75-sample / 26 Hz window (2.88 s / 4 ≈ 720 ms)" — is **retracted as erroneous**.
It survived detection because 2.88 s / 4 = 720 ms is numerically coincident with
75 / 104 Hz = 721.5 ms. Any manuscript text relying on the quarter-window
explanation must be corrected.

## 4. Origin of the 26 Hz claim (documentation genealogy)

The 26 Hz / 2.88 s figures in the manuscript derive from STMicroelectronics'
activity-recognition example documentation ("The MLC runs at 26 Hz, computing
features on windows of 75 samples") and from the pre-amendment project spec
(pre-registration line ~528). The deployed configuration was deliberately modified
from ST's original .ucf — EMB_FUNC_ODR_CFG_C 0x15 → 0x35 (26 → 104 Hz) and
CTRL1_XL 0x28 → 0x50 (52 → 208 Hz) — as recorded in the 2026-05-22 amendment
("MLC ODR specified at 104 Hz, sensor ODR remains 208 Hz"). The manuscript text
was never updated to match; the pre-registration itself remained internally
inconsistent (05-22 amendment vs. v7.6-era cadence text). Both defects are owned
and will be corrected in the revision.

## 5. Pre-committed response branch for Reviewer 1, Point 1

The response letter will: (a) report the verified configuration (sensor 208 Hz,
MLC 104 Hz, host decimation 2:1, matched 75-sample / ~721 ms windows) with the
on-wire register-write receipts and the archived evidence DOI; (b) explicitly own
the manuscript's configuration misstatements and their origin; (c) state that the
existing campaign data constitutes the rate-matched comparison the reviewer
requested, so no re-run was performed; (d) correct all affected manuscript text
(configuration, window durations, cadence explanation, graphical abstract). If
the reviewer requires new data in rebuttal, any such experiment will be
pre-registered in a new amendment BEFORE collection, per the standing rule.

## 6. Manuscript corrections owed (checklist)

- All occurrences of "26 Hz" and "2.88 s" describing the MLC → 104 Hz / ~721 ms.
- All occurrences implying a 208 Hz / 360 ms host decision window → 104 Hz
  (2:1 decimated) / ~721 ms.
- The 706.5 ms cadence explanation → full window at 104 Hz (§3 above).
- Graphical abstract and abstract wording checked for rate claims.
- INT1 pulse-width description (~9.01 ms) left as measured; no ODR attribution
  beyond what the datasheet supports.
