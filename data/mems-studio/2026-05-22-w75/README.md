# MEMS Studio artifacts — 2026-05-22, window=75

This directory captures the artifacts MEMS Studio 2.3.1 produced
during the first decision-tree training run.

**Hyperparameters in this run** (see mlc_settings.json for full
config):

- Window length: **75 samples** (one of the {25, 75, 200}
  pre-registered candidates)
- MLC ODR: **104 Hz** (cap per AN5259; pending v4 amendment)
- Accel ODR: 208 Hz, full scale 2 g
- Filter: IIR1_Acc_V, HP at fc=1 Hz / fs=104 Hz
  (b1=0.970669, b2=-0.970669, a2=+0.941339, MEMS Studio's
  Convention B sign for a2)
- Features: VARIANCE and PEAK_TO_PEAK on Acc_V_filter_1
- Training data: sessions 1 (2026-05-20) + 2 (2026-05-21) only
  (session 3 held out per docs/train-test-split-decision.md)
- Tree algo: new train, max_depth=2047, min_leaf=30, holdout=0.20
- Class codes: still=0, motion=4 (set in Config generation tab)

## Files

| File | What it is | Source |
|---|---|---|
| `mlc_settings.json` | High-level MEMS Studio config: sensor ODR, filters, features, datalog list, decision tree hyperparameters | MEMS Studio MLC → all tabs |
| `features.arff` | Per-window VARIANCE/PEAK_TO_PEAK features for all 4 training files, used as decision tree training input | MEMS Studio ARFF generation |
| `ST_decision_tree_20260522_215504_030.txt` | Plain-text decision tree dump with thresholds and class labels | MEMS Studio Decision tree generation → Inspect tree info |
| `mlc.json` | Low-level register-write sequence for flashing the trained classifier to the LSM6DSOX (.ucf-equivalent in JSON form) | MEMS Studio Config generation |

## Trained tree (see ST_decision_tree_*.txt)

```
F2_ABS_PEAK_TO_PEAK_ACC_V_FILTER_1 <= 0.049316 : still (2718)
F2_ABS_PEAK_TO_PEAK_ACC_V_FILTER_1  > 0.049316 : motion (2669)
```

Single split on p2p_norm. The variance feature was offered but
the tree never picked it because p2p alone gave perfect
separation on the training data.

Training-set accuracy is 100% (Cohen's kappa 100%). This is not
yet a generalization claim — the parity gate runs against
session 3 (held out) data; see docs/train-test-split-decision.md.

## How mlc_json_to_parity.py consumes these

`code/analysis/mlc_json_to_parity.py` (skeleton at commit 43b8163)
needs to extract:

- Window length, MLC ODR, decimation ratio → from `mlc_settings.json`
  (`window_length`, `mlc_odr`, derived as 208/104=2)
- Filter coefficients → from `mlc_settings.json` (`filters` array)
- Feature definitions → from `mlc_settings.json` (`features` array)
- Tree structure with thresholds → from `ST_decision_tree_*.txt`
  (plain-text parsing)
- Class codes → NOT in any file; must be hardcoded for now
  (still=0, motion=4 from MEMS Studio Config generation tab)

The combined output is a single `tree.json` consumable by
`replay_parity.c --tree`.

## MEMS Studio quirks discovered during this run

1. **Convention B for filter coefficients.** MEMS Studio's UI uses
   H(z) = (b1 + b2 z^-1) / (1 - a2 z^-1), opposite sign on a2 vs
   AN5259's notation H(z) = (...) / (1 + a2 z^-1). parity_core.c
   implements AN5259 convention; the extractor must negate the
   sign of a2 when converting from this JSON to tree.json.
   (Or fix parity_core.c to use Convention B.)
2. **CRLF line endings in features.arff.** The Python extractor and
   any shell tools processing the ARFF must handle \r\n line
   endings, not just \n.
3. **In-memory class list staleness.** MEMS Studio's class list is
   held in memory and doesn't auto-update when data patterns are
   loaded — first ARFF generation attempt failed with "classes do
   not match configuration" until we restarted MEMS Studio,
   forcing a reload from disk.
4. **"Percentage of data to use for training" — actual behavior
   unclear.** Help text describes the parameter but doesn't specify
   whether reported accuracy is on the 80% training set, the 20%
   holdout, or the full corpus. Empirically: "Instances: 6734" in
   the report equals the full corpus size, suggesting accuracy is
   computed over all samples. 100% training-set accuracy on a
   linearly-separable problem is unsurprising and doesn't prove
   generalization on its own. Only the session-3 parity test
   provides a real generalization signal.
