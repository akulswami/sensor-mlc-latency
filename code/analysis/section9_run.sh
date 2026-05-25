#!/usr/bin/env bash
# Section 9 gate evaluation for S7-prime (w=25)
# Per pre-reg §9: |host_accuracy - silicon_accuracy| <= 2pp AND both >= 90%
#
# Three stages:
#   1. replay_parity: host classifier on accel.csv → per-window decisions
#   2. silicon_align: silicon polls → host-window-aligned decisions
#   3. compare_decisions: bit-exact-on-class comparison

set -e

SESSION_DIR="$HOME/sensor-mlc-latency/data/training/2026-05-24-S7-prime"
TREE="$HOME/sensor-mlc-latency/code/mlc_config/tree_w25.json"
REPLAY="$HOME/sensor-mlc-latency/code/jetson/host_inference/replay_parity"
SILICON_ALIGN="$HOME/sensor-mlc-latency/code/analysis/silicon_align.py"
COMPARE="$HOME/sensor-mlc-latency/code/analysis/compare_decisions.py"
OUT_DIR="$HOME/sensor-mlc-latency/data/processed/2026-05-24-S7-prime-section9"
mkdir -p "$OUT_DIR"

for CLASS in still motion; do
    echo ""
    echo "===================================================================="
    echo "Class: $CLASS"
    echo "===================================================================="
    
    ACCEL_CSV="$SESSION_DIR/$CLASS/accel.csv"
    SILICON_CSV="$SESSION_DIR/$CLASS/silicon_raw.csv"
    SESSION_JSON="$SESSION_DIR/session.json"
    HOST_OUT="$OUT_DIR/host_${CLASS}.csv"
    SILICON_OUT="$OUT_DIR/silicon_${CLASS}.csv"
    
    if [ ! -f "$ACCEL_CSV" ]; then
        echo "MISSING: $ACCEL_CSV — skipping $CLASS"
        continue
    fi
    
    echo "--- Stage 1: replay_parity (host classifier) ---"
    "$REPLAY" --tree "$TREE" --csv "$ACCEL_CSV" --header > "$HOST_OUT" 2> "${HOST_OUT}.stderr"
    echo "Host decisions: $(wc -l < "$HOST_OUT") rows"
    head -3 "$HOST_OUT"
    echo "..."
    
    echo ""
    echo "--- Stage 2: silicon_align ---"
    python3 "$SILICON_ALIGN" \
        --host-decisions "$HOST_OUT" \
        --silicon-raw "$SILICON_CSV" \
        --session-json "$SESSION_JSON" \
        --class-name "$CLASS" \
        --quiet > "$SILICON_OUT"
    echo "Silicon decisions: $(wc -l < "$SILICON_OUT") rows"
    head -3 "$SILICON_OUT"
    
    echo ""
    echo "--- Stage 3: compare_decisions ($CLASS arm) ---"
    python3 "$COMPARE" \
        --label-a host \
        --label-b silicon \
        "$HOST_OUT" "$SILICON_OUT" 2>&1 | tee "$OUT_DIR/compare_${CLASS}.txt"
done

echo ""
echo "===================================================================="
echo "Section 9 gate summary"
echo "===================================================================="
echo "Output files in: $OUT_DIR"
echo ""
echo "Gate criteria per pre-reg §9:"
echo "  - host_accuracy >= 90% AND silicon_accuracy >= 90%"
echo "  - |host_accuracy - silicon_accuracy| <= 2pp"
echo ""
echo "Inspect compare_${CLASS}.txt for per-class accuracy and gap"
