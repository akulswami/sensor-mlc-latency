# Session 4 parity gate — analysis artifacts

This directory contains the per-window decision artifacts and intermediate
analysis outputs for the §9 parity gate run on session 4. All files
here are derived from `data/training/2026-05-23/` + the tools in
`code/analysis/` + `code/jetson/host_inference/replay_parity`; they are
regeneratable bit-identically from those inputs and the commands below.

The files are committed because the §9 parity gate is a methodologically
gating step in the pre-registration. The result of this run (gate
PASSES at host=98.74%, silicon=99.79%, gap=1.05 pp) is referenced in
`docs/lab-notebook/2026-05-23.md` and will be cited in the paper.

## Input artifacts (with sha256)

These are NOT in this directory; they are inputs from elsewhere in the
repo. Listed here so any audit can confirm the regeneration is
deterministic against the same inputs.

| Input | Path | sha256 |
|---|---|---|
| Host accel (still) | data/training/2026-05-23/still/accel.csv | 37a78848216357e4aab9c9ea4140d23a7020e3a72878a31e735f2d0dbff5e888 |
| Host accel (motion) | data/training/2026-05-23/motion/accel.csv | 0a6e69a32a730651e85ea9395948d898d79e2452ac2bd34d0effcefabf879a20 |
| Silicon raw (still) | data/training/2026-05-23/still/silicon_raw.csv | d88da77c71e8cd8165faba8d8de97f918afeb6f9eefda018472c07970044ea87 |
| Silicon raw (motion) | data/training/2026-05-23/motion/silicon_raw.csv | 0e5bb17504509a9a80f9ec8532450a1fe3fac6819a6ee6530d1a7d38758cf6d2 |
| Session metadata | data/training/2026-05-23/session.json | (regenerate to verify) |
| Trained tree | data/mems-studio/2026-05-22-w75/tree.json | (regenerate to verify) |
| replay_parity binary | code/jetson/host_inference/replay_parity | (rebuild — Asus x86_64 build) |

## Per-file description

### host_decisions_{still,motion}.csv

Output of `replay_parity` running the trained w=75 classifier on the
session 4 host-side accel.csv streams. One row per MLC window.
Schema: `window_idx,t_window_end_s,var_norm,p2p_norm,class`. 1698
windows per arm.

### silicon_aligned_{still,motion}.csv

Output of `silicon_align.py`. Silicon's 50 Hz MLC0_SRC polls binned
into host's window boundaries via session.json's `imu_t0_monotonic_s`.
One row per host window; class = mlc_src of last silicon poll within
the window's `(t_prev_window_end_s, t_window_end_s]` interval.
`var_norm` and `p2p_norm` columns are 0.0 (silicon does not expose
feature values; compare_decisions reads only the class column).

### fp16_emulate_fp32_motion.csv

Output of `fp16_emulate.py --mode fp32` on motion arm. Verified
bit-identical to `host_decisions_motion.csv` on all 1698 windows
(within float32 ULP; one window has a 2e-7 absolute p2p delta from
variance-computation ordering). This file is the cross-check artifact
that establishes `fp16_emulate.py` as a faithful Python reimplementation
of parity_core before drawing any conclusions from `--mode fp16`.

### fp16_emulate_fp16_motion.csv

Output of `fp16_emulate.py --mode fp16` on motion arm. Aggressive FP16
emulation — every filter intermediate cast to numpy.float16. Variance
reduction remains in float64 (matching parity_core's `double`
accumulators). On the 40 motion-arm host-vs-silicon disagreement
windows: FP16 recovers 0 disagreements (none cross threshold to match
silicon's class=4), introduces 1 new disagreement (win 1173). See
notebook for the FP16 falsification result.

### gap_audit_motion.csv

Output of `accel_gap_audit.py`. Per-window sample-to-sample timestamp
statistics for the 40 disagreement windows and a control set of 40
agreement windows. Disagreement vs. control gap distributions are
indistinguishable (disagreement max-gap range 4.94–5.23 ms; control
4.92–26.77 ms with a single outlier in control set). See notebook
for the sample-gap falsification result.

## Regeneration commands

Run from repo root, in order. Output paths match this directory's
filenames; `/tmp/` paths are intermediate.

```bash
TREE=data/mems-studio/2026-05-22-w75/tree.json
RP=code/jetson/host_inference/replay_parity
DATA=data/training/2026-05-23
OUT=data/processed/2026-05-23-parity

# Rebuild replay_parity (Asus x86_64; Jetson aarch64 build will differ
# at the binary level but produce bit-identical CSV output).
cd code/jetson/host_inference && \
  gcc -O2 -Wall -Wextra -o replay_parity replay_parity.c parity_core.c -lm && \
  cd -

# Stage 1: host decisions.
$RP --tree $TREE --csv $DATA/still/accel.csv  --header \
    > $OUT/host_decisions_still.csv
$RP --tree $TREE --csv $DATA/motion/accel.csv --header \
    > $OUT/host_decisions_motion.csv

# Stage 2: silicon-aligned decisions.
python3 code/analysis/silicon_align.py \
    --host-decisions $OUT/host_decisions_still.csv \
    --silicon-raw    $DATA/still/silicon_raw.csv \
    --session-json   $DATA/session.json \
    --class-name     still \
    > $OUT/silicon_aligned_still.csv
python3 code/analysis/silicon_align.py \
    --host-decisions $OUT/host_decisions_motion.csv \
    --silicon-raw    $DATA/motion/silicon_raw.csv \
    --session-json   $DATA/session.json \
    --class-name     motion \
    > $OUT/silicon_aligned_motion.csv

# Stage 3: §9 gate accuracy computation (results in lab notebook).
# (no separate output file; computed inline:)
#   host    accuracy = (correct_still + correct_motion) / total
#   silicon accuracy = (correct_still + correct_motion) / total
# where correct = matches by-file ground truth.

# FP16-emulation experiment (Hypothesis 1).
python3 code/analysis/fp16_emulate.py \
    --accel-csv $DATA/motion/accel.csv --tree-json $TREE \
    --mode fp32 --windows all \
    > $OUT/fp16_emulate_fp32_motion.csv
python3 code/analysis/fp16_emulate.py \
    --accel-csv $DATA/motion/accel.csv --tree-json $TREE \
    --mode fp16 --windows all \
    > $OUT/fp16_emulate_fp16_motion.csv

# Sample-gap audit (Hypothesis 2).
DISAGREE="17,34,65,167,184,187,218,221,289,337,357,456,466,558,585,595,602,619,629,646,653,687,986,1040,1054,1071,1105,1190,1241,1258,1309,1461,1462,1513,1530,1547,1564,1581,1598,1666"
python3 code/analysis/accel_gap_audit.py \
    --accel-csv $DATA/motion/accel.csv --tree-json $TREE \
    --disagree $DISAGREE \
    > $OUT/gap_audit_motion.csv
```

## Verification

Two minimum-effort audits:

1. **Tool fidelity**: `diff host_decisions_motion.csv fp16_emulate_fp32_motion.csv`
   should differ only in: (a) header line label (`class` vs
   `classifier_class`); (b) at most one window with a 2e-7 absolute
   p2p delta from variance-reduction ordering; (c) zero class
   disagreements.

2. **Gate computation**:
   ```
   awk -F, 'NR>1 && $5 == 0' host_decisions_still.csv  | wc -l   # → 1694
   awk -F, 'NR>1 && $5 == 4' host_decisions_motion.csv | wc -l   # → 1659
   awk -F, 'NR>1 && $5 == 0' silicon_aligned_still.csv | wc -l   # → 1692
   awk -F, 'NR>1 && $5 == 4' silicon_aligned_motion.csv| wc -l   # → 1697
   ```
   Host: (1694+1659)/3396 = 0.98735... = 98.74%
   Silicon: (1692+1697)/3396 = 0.99794... = 99.79%
   Gap: 1.05 pp ≤ 2 pp; both ≥ 90%; §9 PASSES.
