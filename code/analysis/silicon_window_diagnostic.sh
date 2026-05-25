#!/usr/bin/env bash
# silicon_window_diagnostic.sh
#
# Quick diagnostic to verify which window length actually got flashed
# to silicon during a capture. Counts class transitions per second in
# the silicon_raw.csv log; transition density scales inversely with
# window length.
#
# Empirical baselines (motion arm, servo sweeping at 1 Hz):
#   w=25:  ~0.6 transitions/sec
#   w=75:  ~0.05-0.07 transitions/sec
#   w=200: even lower
#
# Usage:
#   silicon_window_diagnostic.sh <path-to-silicon_raw.csv>
#
# Established 2026-05-24 in v7.2's orchestrator-bug fix work.
# See Zenodo DOI 10.5281/zenodo.20371440.

set -e

if [ $# -ne 1 ]; then
    echo "Usage: $0 <path-to-silicon_raw.csv>" >&2
    exit 1
fi

CSV="$1"
if [ ! -f "$CSV" ]; then
    echo "Not a file: $CSV" >&2
    exit 1
fi

# Count transitions (class changes) in the silicon poll log.
# Skip the first 4 lines (3 comment headers + column header).
TRANSITIONS=$(awk -F, '
    NR>4 {
        gsub(/^ +/,"",$2);
        if (NR==5) { last=$2; trans=0 }
        else { if ($2 != last) trans++; last=$2 }
    }
    END { print trans+0 }
' "$CSV")

# Compute duration from first and last timestamps
DURATION=$(awk -F, '
    NR>4 {
        gsub(/^ +/,"",$1);
        if (NR==5) start=$1;
        end=$1;
    }
    END { printf "%.3f", end - start }
' "$CSV")

# Transitions per second
RATE=$(python3 -c "print(f'{$TRANSITIONS / $DURATION:.4f}' if $DURATION > 0 else '0.0')")

# Inference
INFER=$(python3 -c "
rate = $RATE
# The diagnostic reliably distinguishes w=25 from non-w=25 (w=25 has
# transition density ~10x higher than any longer window length at this
# rig's 1 Hz servo cycle). It does NOT reliably distinguish w=75 from
# w=200 — both have transition density in the 0.005-0.06 /sec range
# depending on capture duration, motion-arm fraction, and startup
# transients. To determine the specific window length when below the
# w=25 threshold, examine first-transition timing (~0.7s for w=75,
# ~1.9s for w=200) or read the actual MLC0_WIN register.
if rate > 0.3: print('w=25 (high transition density: > 0.3/sec)')
elif rate > 0.0: print('NOT w=25 (low density: <= 0.3/sec). Could be w=75, w=200, or sensor at rest.')
else: print('no transitions (sensor at rest, or readback issue)')
")

echo "File:        $CSV"
echo "Duration:    ${DURATION}s"
echo "Transitions: $TRANSITIONS"
echo "Rate:        ${RATE} transitions/sec"
echo "Inferred:    $INFER"
