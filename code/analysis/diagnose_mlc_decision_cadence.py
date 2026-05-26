"""diagnose_mlc_decision_cadence.py
=====================================

Computes the empirical D1-edge inter-arrival distribution within a
block's digital.csv, identifying the MLC silicon's intrinsic decision
cadence (the periodicity at which MLC interrupts fire, regardless of
whether the binary state has changed).

Also computes the per-trial D1-edge count distribution to characterize
the "multiple_d1_in_window" exclusion mode introduced in v7.4.

Empirical finding from 2026-05-26 analysis of block-700:
- MLC decision cadence: ~706 ms (= 25% of the 75-sample, 26 Hz window).
- Under i2c-contention, the MLC's classifier output oscillates 2-4
  times within a 5-second stimulus window, with inter-edge gaps that
  are exact multiples of ~706 ms.
- This is NOT classifier bounce; it is the MLC firing genuine repeat
  decisions at its intrinsic cadence because contention destabilizes
  the underlying classification.

Run:
    python3 code/analysis/diagnose_mlc_decision_cadence.py \\
        --block data/training/latency-experiment/block-700-mlc-i2c-contention
"""

import argparse
import csv
import sys
from pathlib import Path


def load_rising_edges(digital_csv_path, channel):
    """Yield timestamps (in seconds) of all rising edges on the given channel.

    Saleae raw export format: header row, then rows of
    [Time [s], Channel 0, Channel 1, ...].
    """
    with open(digital_csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)
        last_val = None
        for row in reader:
            try:
                t = float(row[0])
                val = int(row[channel + 1])
            except (ValueError, IndexError):
                continue
            if last_val is not None and last_val != val and val == 1:
                yield t
            last_val = val


def hist_bins(values, bin_size_ms):
    """Return a {bin_center_ms -> count} dict."""
    from collections import Counter
    return Counter(round(v / bin_size_ms) * bin_size_ms for v in values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", required=True,
                        help="Path to a block directory (must contain digital.csv "
                             "and trials.csv)")
    parser.add_argument("--bin-ms", type=int, default=200,
                        help="Histogram bin size in milliseconds (default: 200)")
    args = parser.parse_args()

    block_dir = Path(args.block)
    digital = block_dir / "digital.csv"
    trials = block_dir / "trials.csv"

    if not digital.exists():
        sys.exit(f"digital.csv not found in {block_dir}")
    if not trials.exists():
        sys.exit(f"trials.csv not found in {block_dir}")

    # 1. All D1 rising edges across the entire block
    print(f"Block: {block_dir.name}")
    print(f"Loading D1 rising edges from {digital}...")
    d1_times = sorted(load_rising_edges(digital, channel=1))
    print(f"  found {len(d1_times)} D1 rising edges across full block")

    # Inter-edge gaps
    gaps_ms = [(d1_times[i] - d1_times[i-1]) * 1000 for i in range(1, len(d1_times))]
    if not gaps_ms:
        sys.exit("no inter-edge gaps to analyze")

    gaps_ms.sort()
    print()
    print(f"=== D1 inter-edge gap distribution (n={len(gaps_ms)}) ===")
    n = len(gaps_ms)
    print(f"  min:    {gaps_ms[0]:>8.1f} ms")
    print(f"  p10:    {gaps_ms[n//10]:>8.1f} ms")
    print(f"  p25:    {gaps_ms[n//4]:>8.1f} ms")
    print(f"  median: {gaps_ms[n//2]:>8.1f} ms")
    print(f"  p75:    {gaps_ms[3*n//4]:>8.1f} ms")
    print(f"  max:    {gaps_ms[-1]:>8.1f} ms")
    print()
    print(f"=== Histogram ({args.bin_ms}ms bins, showing bins with >= 5 occurrences) ===")
    hist = hist_bins(gaps_ms, args.bin_ms)
    for k in sorted(hist):
        if hist[k] >= 5:
            bar = "#" * min(hist[k], 60)
            print(f"  {k:>6} ms: {hist[k]:>4}  {bar}")

    # 2. Identify the dominant peak (intrinsic decision cadence)
    print()
    print("=== Intrinsic decision cadence detection ===")
    min_gap = gaps_ms[0]
    print(f"  minimum observed gap: {min_gap:.1f} ms (lower bound on decision cadence)")

    # The histogram modes should be at integer multiples of the intrinsic cadence
    # Find the mode of small gaps (< 2.5x the minimum)
    small_gaps = [g for g in gaps_ms if g < 2.5 * min_gap]
    if small_gaps:
        # NOTE: avoid `import statistics` here because code/analysis/statistics.py
        # is a project-specific module (pre-registered stats per pre-reg §12) that
        # shadows the stdlib when this script runs from code/analysis/.
        small_gaps_sorted = sorted(small_gaps)
        med = small_gaps_sorted[len(small_gaps_sorted) // 2]
        print(f"  median of small gaps (< {2.5*min_gap:.0f} ms): {med:.1f} ms")
        print(f"    (this is the empirical estimate of the MLC decision cadence)")

    # 3. Per-trial: distribution of D1 edges within each stimulus window
    print()
    print("=== Per-trial D1 edge counts (within stimulus window) ===")
    # Build stimulus times list
    stim_times = sorted(float(t["t_stim_s"]) for t in csv.DictReader(open(trials))
                       if t.get("t_stim_s"))
    if not stim_times:
        print("  (no stimulus times in trials.csv)")
        return

    from collections import Counter
    d1_per_trial = []
    for i, t_stim in enumerate(stim_times):
        t_next = stim_times[i+1] if i+1 < len(stim_times) else t_stim + 5.0
        n_d1 = sum(1 for te in d1_times if t_stim < te <= t_next)
        d1_per_trial.append(n_d1)

    dist = Counter(d1_per_trial)
    print(f"  total trial windows: {len(d1_per_trial)}")
    for k in sorted(dist):
        bar = "#" * min(dist[k], 60)
        print(f"    {k} D1 edges: {dist[k]:>4}  {bar}")


if __name__ == "__main__":
    main()
