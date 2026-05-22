#!/usr/bin/env bash
# test_compare_decisions.sh
#
# Unit test for compare_decisions.py. Three scenarios:
#   1. Bit-identical files       -> PASS, exit 0
#   2. Same length, one mismatch -> FAIL, exit 1, first divergence reported
#   3. Different lengths         -> FAIL, exit 1, count mismatch reported
#
# Run from the repo root:
#   bash code/analysis/test_compare_decisions.sh

set -uo pipefail  # NOT -e because we need to inspect failing exit codes

SCRIPT="${COMPARE_DECISIONS:-code/analysis/compare_decisions.py}"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

if [[ ! -f "$SCRIPT" ]]; then
    echo "FAIL: $SCRIPT not found"
    exit 2
fi

# --- Fixture: a small valid decisions.csv ---
write_csv() {
    local path="$1"; shift
    {
        echo "window_idx,t_window_end_s,var_norm,p2p_norm,class"
        for line in "$@"; do
            echo "$line"
        done
    } > "$path"
}

# Three windows: still, motion, still.
write_csv "$TMPDIR/a.csv" \
    "0,0.115,0.0,0.0,0" \
    "1,0.235,1e-4,0.05,4" \
    "2,0.355,0.0,0.0,0"

# --- Test 1: identical files ---
cp "$TMPDIR/a.csv" "$TMPDIR/b_identical.csv"
out_1=$(python3 "$SCRIPT" "$TMPDIR/a.csv" "$TMPDIR/b_identical.csv" 2>&1)
ec_1=$?
if [[ $ec_1 -ne 0 ]]; then
    echo "FAIL test 1 (identical): expected exit 0, got $ec_1"
    echo "--- output ---"
    echo "$out_1"
    exit 1
fi
if ! echo "$out_1" | grep -q "PASS"; then
    echo "FAIL test 1 (identical): expected PASS in output"
    echo "--- output ---"
    echo "$out_1"
    exit 1
fi
echo "test 1 (identical):       PASS"

# --- Test 2: same length, one class disagrees ---
# Flip the middle class from 4 to 0; first divergence should be row index 1.
write_csv "$TMPDIR/b_one_mismatch.csv" \
    "0,0.115,0.0,0.0,0" \
    "1,0.235,1e-4,0.05,0" \
    "2,0.355,0.0,0.0,0"
out_2=$(python3 "$SCRIPT" "$TMPDIR/a.csv" "$TMPDIR/b_one_mismatch.csv" 2>&1)
ec_2=$?
if [[ $ec_2 -ne 1 ]]; then
    echo "FAIL test 2 (one mismatch): expected exit 1, got $ec_2"
    echo "--- output ---"
    echo "$out_2"
    exit 1
fi
if ! echo "$out_2" | grep -q "1/3 classes disagree"; then
    echo "FAIL test 2 (one mismatch): expected '1/3 classes disagree' in output"
    echo "--- output ---"
    echo "$out_2"
    exit 1
fi
if ! echo "$out_2" | grep -q "First divergence at row index 1"; then
    echo "FAIL test 2 (one mismatch): expected first divergence at row 1"
    echo "--- output ---"
    echo "$out_2"
    exit 1
fi
echo "test 2 (one mismatch):    PASS"

# --- Test 3: different lengths ---
write_csv "$TMPDIR/b_shorter.csv" \
    "0,0.115,0.0,0.0,0" \
    "1,0.235,1e-4,0.05,4"
out_3=$(python3 "$SCRIPT" "$TMPDIR/a.csv" "$TMPDIR/b_shorter.csv" 2>&1)
ec_3=$?
if [[ $ec_3 -ne 1 ]]; then
    echo "FAIL test 3 (length mismatch): expected exit 1, got $ec_3"
    echo "--- output ---"
    echo "$out_3"
    exit 1
fi
if ! echo "$out_3" | grep -q "window counts differ"; then
    echo "FAIL test 3 (length mismatch): expected 'window counts differ' message"
    echo "--- output ---"
    echo "$out_3"
    exit 1
fi
echo "test 3 (length mismatch): PASS"

# --- Test 4: malformed input (missing column) ---
echo "window_idx,foo,bar" > "$TMPDIR/bad.csv"
echo "0,1,2" >> "$TMPDIR/bad.csv"
out_4=$(python3 "$SCRIPT" "$TMPDIR/a.csv" "$TMPDIR/bad.csv" 2>&1)
ec_4=$?
if [[ $ec_4 -ne 2 ]]; then
    echo "FAIL test 4 (malformed): expected exit 2, got $ec_4"
    echo "--- output ---"
    echo "$out_4"
    exit 1
fi
echo "test 4 (malformed input): PASS"

echo
echo "all tests PASS"
