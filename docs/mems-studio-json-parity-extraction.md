# MEMS Studio JSON Export — Parity Extraction Checklist

**Status:** Draft, pre-training
**Last updated:** 2026-05-21
**Purpose:** Capture exactly what fields to extract from the MEMS Studio
MLC JSON export so the host parity classifier can be constructed
deterministically. This is a future-self checklist, written before
training has occurred. Update with concrete field names once the first
real export is in hand.

## Why this document exists

The MLC byte-level config in `.ucf` / `.h` is not human-decodable: ST
explicitly does not support hand-writing or hand-reverse-engineering MLC
configs (per ST community thread, 2024). The supported way to extract a
trained tree is the MEMS Studio JSON export, which contains the
classifier as structured data by design (introduced in MEMS Studio 2.0).

Source: https://blog.st.com/mems-studio/ — "support for JSON format for
MLC configuration files, allowing developers to read, edit, and port
them more rapidly from one project to the next."

The host parity classifier reads from this JSON, never from `.ucf` bytes.

## When to populate the unknowns

Run MEMS Studio training on at least session 1 (sessions 2 + 3 may not
yet be collected at first inspection — that's fine, we're characterizing
the export schema, not making a final tree). Open the resulting JSON in
a text editor and fill in the right-hand column below.

## Fields the host parity port needs

The host port (`host_pipeline_parity.c` and `replay_parity.c`) needs to
reproduce the MLC's classification bit-identically. That requires
exactly the following information. Names below are guesses pending
real-export inspection.

### 1. Window length
- **What:** number of input samples per feature computation.
- **Spec candidates:** {25, 75, 200} at 208 Hz accel ODR.
- **Where in JSON (TBD):** look for `window_length` / `WL` / `samples_per_window` keys.
- **Used by host:** `WINDOW_LEN` macro in `host_pipeline_parity.c`,
  `--window` CLI arg in `replay_parity.c`.

### 2. MLC ODR
- **What:** the rate at which the MLC consumes (decimated) samples.
- **AN5259 constraint:** ∈ {12.5, 26, 52, 104} Hz. Sensor ODR (208 Hz)
  must be ≥ MLC ODR; AN5259 recommends sensor ODR == MLC ODR.
- **Implication for our spec:** if MLC_ODR=104 Hz with sensor at
  208 Hz, MLC decimates by 2 internally without filtering. The host
  port must mirror this decimation exactly, OR we set MLC_ODR=208 Hz
  (impossible — out of range) OR we lower sensor ODR to match MLC ODR.
  **This is a real spec gap; flag as v4 amendment question.**
- **Where in JSON (TBD):** `MLC_ODR` / `output_data_rate`.

### 3. Filter chain
- **What:** the HP filter (and any others) applied before feature
  extraction. AN5259 specifies a 2nd-order IIR with coefficients
  `b1, b2, b3, a2, a3, gain` in half-precision float.
- **Spec candidates:** HP IIR1, f_cut ≈ 1 Hz. AN5259 Table 3 gives the
  reference values for 26 Hz ODR: b1=0.891725, b2=−0.891725,
  a2=−0.783450. **At other MLC_ODR, coefficients must be recomputed**
  via `scipy.signal.butter(1, fc/(ODR/2), 'high')` and quantized to
  half-precision float.
- **Where in JSON (TBD):** `filters` array. Each filter entry has type
  (IIR1/IIR2/HP/BP), coefficients, and which input it operates on
  (Acc_X/Y/Z/V/V², etc.).
- **Used by host:** feature pipeline in `host_pipeline_parity.c`. The
  HP filter must be implemented in half-precision float OR confirmed
  that float32 produces bit-identical class labels on all training
  windows (decision parity, not feature parity, is the gate).

### 4. Feature definitions
- **What:** which features compute on which input. Per spec:
  VARIANCE_NORM and PEAK_TO_PEAK_NORM where NORM is `√(x² + y² + z²)`.
- **Where in JSON (TBD):** `features` array. Each entry: feature type
  (MEAN / VARIANCE / PEAK_TO_PEAK / ZERO_CROSSING / …), source signal
  (raw axis / norm / squared norm / filtered output), feature ID
  (small integer; tree references features by this ID).
- **Trap to verify:** AN5259 defines VARIANCE without specifying
  biased vs unbiased estimator. Confirm by computing both on a known
  window from training data and seeing which matches the MLC's
  internal output (if readable; if not, treat as a parameter to
  match by trial against training-set classifications).

### 5. Decision tree
- **What:** the trained binary classifier as a list of nodes. Each
  internal node compares one feature against one threshold; each leaf
  emits a class code.
- **Where in JSON (TBD):** `decision_tree` or `tree` key. Expected
  fields per node:
  - `node_id` (integer)
  - `feature_id` (which feature from §4)
  - `threshold` (float, compared against feature value)
  - `comparison` (likely `<` or `≤`; confirm)
  - `left_child` / `right_child` (node_id or leaf indicator)
  - For leaves: `class` (the value emitted in MLC0_SRC).
- **Trap:** the threshold's units. Variance is in (g)² but the MLC may
  internally scale. Peak-to-peak is in g. The JSON should preserve
  natural units; if not, document the scaling factor.

### 6. Class output codes
- **What:** the numeric values written to MLC0_SRC. Per spec: STILL=0,
  MOTION=something nonzero. The actual code for MOTION is assigned
  by Weka/MEMS Studio and may not be 1 — ST's examples often use 4 or
  8 for legacy historical reasons (see AN5259 §3.4: walking=1,
  jogging=4, biking=8 in activity recognition).
- **Where in JSON (TBD):** `class_codes` map or per-leaf `output_value`.
- **Used by host:** `CLASS_STILL` / `CLASS_MOTION` macros in
  `host_pipeline_parity.c`.

### 7. Meta-classifier (CONFIRM ABSENT)
- **What:** optional smoothing of decision tree outputs (AN5259 §1.5).
- **Spec says:** not used.
- **JSON field (TBD):** if a `meta_classifier` entry is present with
  any nonzero end-counter, the spec is violated. Either reconfigure
  in MEMS Studio to disable it, or formally amend the spec to v4.

## Extraction script: `mlc_json_to_parity.py` (to be written)

Once the real JSON schema is observed, write a Python script that:

1. Loads the JSON.
2. Validates fields 1–7 against this checklist (raising on any missing
   or inconsistent field).
3. Emits a compact `tree.json` in a stable schema we control:
   ```json
   {
     "window_length": 75,
     "mlc_odr_hz": 104,
     "sensor_odr_hz": 208,
     "decimation_ratio": 2,
     "filters": [
       {"id": 0, "type": "iir1_hp", "input": "norm",
        "b1": 0.891725, "b2": -0.891725, "a2": -0.783450, "gain": 1.0}
     ],
     "features": [
       {"id": 0, "type": "variance", "input_filter_id": 0,
        "estimator": "biased"},
       {"id": 1, "type": "peak_to_peak", "input_filter_id": 0}
     ],
     "tree": [
       {"node_id": 0, "feature_id": 0, "threshold": 1.23e-4,
        "comparison": "lte", "left": 1, "right": 2},
       {"node_id": 1, "leaf": true, "class": 0},
       {"node_id": 2, "leaf": true, "class": 4}
     ],
     "class_codes": {"still": 0, "motion": 4}
   }
   ```
4. The host parity binary (`replay_parity.c`, eventually
   `host_pipeline_parity.c`) consumes only this stable schema. The
   MEMS Studio JSON format can change between versions; our stable
   schema does not.

## Validation procedure (parity gate)

Once `tree.json` exists:

1. Run `replay_parity --tree tree.json --csv data/training/<date>/motion/accel.csv`.
   Output: per-window `(window_idx, class_code)`.
2. Load the same `.ucf` onto the LSM6DSOX, replay the same CSV via
   MEMS Studio's "Data analysis" replay function (if available) or by
   physically reproducing the input on the servo, log MLC0_SRC at
   every window boundary.
3. Diff the two label sequences. **Bit-identical = parity gate
   cleared.** Any mismatch → investigate which field (filter coef,
   feature estimator, tree comparison operator, decimation policy)
   was extracted wrong.

The parity gate is per pre-registration: both pipelines must achieve
≥90% accuracy on held-out session and the gap between them ≤2pp.
Bit-identical decisions on identical input is a stronger property; it
implies the accuracy gap is exactly zero on whatever input you choose.

## Things we will NOT do

- **We will not reverse-engineer the `.ucf` byte format.** ST has
  explicitly stated the binary configuration is not intended for
  manual interpretation. Going against that is a research project of
  its own, not a paper deliverable. The JSON path is sanctioned.
- **We will not assume the tree structure from screenshots.** Weka /
  MEMS Studio's graphical tree view is helpful for sanity but is not
  the ground truth. The JSON is.
- **We will not skip the parity validation step.** Even if the
  extraction looks clean, run the diff. The pre-registration's parity
  gate is what the paper rests on.
