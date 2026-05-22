#!/usr/bin/env bash
# test_replay_parity.sh
#
# Unit test for replay_parity. Creates a toy tree.json and a synthetic
# accel.csv with a known motion-vs-still pattern, then asserts the
# emitted per-window classes match the ground truth.
#
# Design of the synthetic test signal:
#   - 208 Hz sample rate, no decimation (decimation_ratio=1, MLC_ODR=208
#     for this test — we're testing harness logic, not spec compliance).
#   - Window length = 25 samples (small for fast test, 120 ms at 208 Hz).
#   - 12 windows total (300 samples):
#       windows 0..3   : still (gravity on Z, no motion)        -> class 0
#       windows 4..7   : motion (1 Hz sinusoid on X, 0.5 g amp) -> class 4
#       windows 8..11  : still again                             -> class 0
#
# Toy tree (depth 1):
#   if p2p_norm > 0.005 -> class 4 (motion)
#   else                 -> class 0 (still)
#
# Note on threshold choice: a 25-sample (120 ms) window at 208 Hz only
# covers ~12% of a 1 Hz cycle, so peak-to-peak captured varies strongly
# with phase alignment (windows 4 and 6 land on near-flat portions of
# the sinusoid). Still windows yield p2p=0 exactly. We pick a threshold
# (0.005) well above 0 but below the smallest motion p2p (~0.03), since
# the goal is to verify the harness machinery, not to test a realistic
# classifier.
#
# The HP filter is configured to bypass (b1=1, b2=0, a2=0): we want to
# test tree-walk + feature math, not filter coefficient extraction.
#
# This test exists to catch breakage in: JSON parsing, window
# accumulation, feature math, tree walk, CSV ingestion, unit inference.
#
# Run from the repo root:
#   bash code/jetson/host_inference/test_replay_parity.sh
# or with a custom binary:
#   REPLAY_PARITY=/tmp/replay_parity bash test_replay_parity.sh

set -euo pipefail

BIN="${REPLAY_PARITY:-/tmp/replay_parity}"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

if [[ ! -x "$BIN" ]]; then
    echo "FAIL: $BIN not found or not executable. Build with:"
    echo "  gcc -O2 -Wall -o /tmp/replay_parity code/jetson/host_inference/replay_parity.c -lm"
    exit 2
fi

# --- 1. Write the toy tree.json ---
# Bypass HP filter (b1=1, b2=0, a2=0 => y[n]=x[n]). Single threshold on p2p.
cat > "$TMPDIR/tree.json" <<'JSON'
{
  "window_length": 25,
  "sensor_odr_hz": 208,
  "mlc_odr_hz": 208,
  "decimation_ratio": 1,
  "filters": [
    {"id": 0, "type": "iir1_hp", "b1": 1.0, "b2": 0.0, "a2": 0.0, "gain": 1.0}
  ],
  "features": [
    {"id": 0, "type": "variance",     "input_filter_id": 0, "estimator": "biased"},
    {"id": 1, "type": "peak_to_peak", "input_filter_id": 0}
  ],
  "tree": [
    {"node_id": 0, "feature_id": 1, "threshold": 0.005, "comparison": "gt",
     "left": 1, "right": 2},
    {"node_id": 1, "leaf": true, "class": 4},
    {"node_id": 2, "leaf": true, "class": 0}
  ],
  "class_codes": {"still": 0, "motion": 4}
}
JSON

# --- 2. Generate synthetic accel.csv ---
# Python is cleaner than bash awk for sinusoids.
python3 - "$TMPDIR/accel.csv" <<'PY'
import sys, math
out = sys.argv[1]
fs = 208.0
window = 25
total_windows = 12
n = window * total_windows  # 300

with open(out, "w") as f:
    f.write("timestamp,ax_g,ay_g,az_g\n")  # MEMS Studio-ish header
    for i in range(n):
        t = i / fs
        win_idx = i // window
        if win_idx < 4 or win_idx >= 8:
            # still: gravity on Z, tiny noise
            ax, ay, az = 0.0, 0.0, 1.0
        else:
            # motion: 1 Hz, 0.5 g amplitude on X
            ax = 0.5 * math.sin(2 * math.pi * 1.0 * t)
            ay = 0.0
            az = 1.0
        f.write(f"{t:.6f},{ax:.6f},{ay:.6f},{az:.6f}\n")
PY

# --- 3. Run replay_parity ---
OUT="$TMPDIR/out.csv"
"$BIN" --tree "$TMPDIR/tree.json" --csv "$TMPDIR/accel.csv" --header --quiet > "$OUT"

# --- 4. Assert: 12 windows, classes match the pattern ---
EXPECTED_CLASSES=(0 0 0 0 4 4 4 4 0 0 0 0)

# Skip header row, extract class column (5th col).
mapfile -t actual_classes < <(tail -n +2 "$OUT" | cut -d, -f5)

if [[ "${#actual_classes[@]}" -ne 12 ]]; then
    echo "FAIL: expected 12 windows, got ${#actual_classes[@]}"
    echo "--- output ---"
    cat "$OUT"
    exit 1
fi

fail=0
for i in "${!EXPECTED_CLASSES[@]}"; do
    if [[ "${actual_classes[$i]}" != "${EXPECTED_CLASSES[$i]}" ]]; then
        echo "MISMATCH window $i: expected ${EXPECTED_CLASSES[$i]} got ${actual_classes[$i]}"
        fail=1
    fi
done

if [[ $fail -ne 0 ]]; then
    echo "--- full output ---"
    cat "$OUT"
    exit 1
fi

echo "PASS: 12/12 windows classified correctly"
echo
echo "--- output for inspection ---"
cat "$OUT"
