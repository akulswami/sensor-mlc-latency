#!/usr/bin/env python3
"""
accel_gap_audit.py

Tests the sample-gap hypothesis: were the 40 motion-arm host-silicon
disagreement windows correlated with irregular accel.csv sample-to-sample
timestamps (e.g. from imu_logger blocking on the bus lock during MLC
bank-switches)?

If gaps inside disagreement windows are systematically larger / more
variable than gaps inside a control set of agreement windows, that's
evidence the host's accel.csv was reconstructing a slightly different
sample stream than silicon's internal pipeline saw — explaining the
~0.005 g p2p discrepancies.

If gap distributions are statistically indistinguishable, the hypothesis
is falsified and we move on.

Inputs:
  --accel-csv     data/training/2026-05-23/motion/accel.csv
  --tree-json     data/mems-studio/2026-05-22-w75/tree.json (for win=75, decim=2)
  --disagree      comma-separated disagreement window indices
  --quiet

Output: summary stats on stderr; per-window detail on stdout (CSV).
"""

from __future__ import annotations
import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WindowGapStats:
    window_idx: int
    is_disagreement: bool
    n_samples: int
    expected_interval_ms: float
    mean_gap_ms: float
    max_gap_ms: float
    min_gap_ms: float
    stdev_gap_ms: float
    n_gaps_above_2x: int  # samples where gap > 2 * expected
    n_gaps_above_3x: int
    largest_gap_ms: float


def load_accel_timestamps(path: str) -> list[float]:
    """Return list of timestamps (relative to imu_t0, seconds) from accel.csv."""
    timestamps: list[float] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                t = float(parts[0])
            except ValueError:
                continue  # header
            timestamps.append(t)
    return timestamps


def compute_window_gaps(
    timestamps: list[float],
    window_idx: int,
    samples_per_window: int,
    is_disagreement: bool,
    expected_interval_ms: float,
) -> WindowGapStats | None:
    """For host window N, the contributing sensor samples are indices
    in [N*150, (N+1)*150 - 1] (0-indexed). 150 = decim_ratio * window_length.

    NOTE: this assumes decim=2, win=75. Adjust samples_per_window if
    those change.
    """
    start = window_idx * samples_per_window
    end = start + samples_per_window
    if end > len(timestamps):
        return None
    ts = timestamps[start:end]
    gaps_ms = [(ts[i] - ts[i-1]) * 1000.0 for i in range(1, len(ts))]
    if not gaps_ms:
        return None
    return WindowGapStats(
        window_idx=window_idx,
        is_disagreement=is_disagreement,
        n_samples=len(ts),
        expected_interval_ms=expected_interval_ms,
        mean_gap_ms=statistics.mean(gaps_ms),
        max_gap_ms=max(gaps_ms),
        min_gap_ms=min(gaps_ms),
        stdev_gap_ms=statistics.stdev(gaps_ms) if len(gaps_ms) > 1 else 0.0,
        n_gaps_above_2x=sum(1 for g in gaps_ms if g > 2 * expected_interval_ms),
        n_gaps_above_3x=sum(1 for g in gaps_ms if g > 3 * expected_interval_ms),
        largest_gap_ms=max(gaps_ms),
    )


def summarize(stats: list[WindowGapStats], label: str) -> str:
    """Return a short summary string for either the disagreement or
    control set.
    """
    if not stats:
        return f"  {label}: no windows"
    max_gaps = [s.max_gap_ms for s in stats]
    mean_gaps = [s.mean_gap_ms for s in stats]
    stdevs = [s.stdev_gap_ms for s in stats]
    above_2x = sum(s.n_gaps_above_2x for s in stats)
    above_3x = sum(s.n_gaps_above_3x for s in stats)
    return (
        f"  {label} (n={len(stats)} windows):\n"
        f"    max_gap_ms:     min={min(max_gaps):.4f}  mean={statistics.mean(max_gaps):.4f}  "
        f"max={max(max_gaps):.4f}\n"
        f"    mean_gap_ms:    min={min(mean_gaps):.4f}  mean={statistics.mean(mean_gaps):.4f}  "
        f"max={max(mean_gaps):.4f}\n"
        f"    stdev_gap_ms:   min={min(stdevs):.4f}  mean={statistics.mean(stdevs):.4f}  "
        f"max={max(stdevs):.4f}\n"
        f"    total gaps >2x expected: {above_2x}\n"
        f"    total gaps >3x expected: {above_3x}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--accel-csv", required=True)
    ap.add_argument("--tree-json", required=True)
    ap.add_argument("--disagree", required=True,
                    help="comma-separated window indices of host-silicon disagreement")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cfg = json.loads(Path(args.tree_json).read_text())
    decim = int(cfg["decimation_ratio"])
    win_len = int(cfg["window_length"])
    sensor_odr = int(cfg["sensor_odr_hz"])
    samples_per_window = decim * win_len  # 150 for session 4
    expected_interval_ms = 1000.0 / sensor_odr  # 4.808 ms at 208 Hz

    print(f"# config: win={win_len} decim={decim} samples_per_window={samples_per_window} "
          f"sensor_odr={sensor_odr} Hz expected_interval={expected_interval_ms:.4f} ms",
          file=sys.stderr)

    disagree_set = set(int(w) for w in args.disagree.split(","))
    timestamps = load_accel_timestamps(args.accel_csv)
    print(f"# loaded {len(timestamps)} timestamps from {args.accel_csv}",
          file=sys.stderr)

    n_windows = len(timestamps) // samples_per_window
    print(f"# {n_windows} complete windows in this recording", file=sys.stderr)

    # Build control set: agreement windows (host=4, silicon=4). For
    # this analysis, "agreement window" = any window NOT in disagree_set.
    # We sample n=len(disagree_set) agreement windows uniformly to keep
    # sample sizes balanced. Use deterministic indices (every k-th).
    agreement_indices: list[int] = []
    k = n_windows // len(disagree_set)
    for i in range(len(disagree_set)):
        candidate = i * k
        while candidate in disagree_set and candidate < n_windows:
            candidate += 1
        if candidate < n_windows:
            agreement_indices.append(candidate)

    disagree_stats: list[WindowGapStats] = []
    agreement_stats: list[WindowGapStats] = []

    for w in sorted(disagree_set):
        s = compute_window_gaps(timestamps, w, samples_per_window,
                                is_disagreement=True,
                                expected_interval_ms=expected_interval_ms)
        if s is not None:
            disagree_stats.append(s)

    for w in agreement_indices:
        s = compute_window_gaps(timestamps, w, samples_per_window,
                                is_disagreement=False,
                                expected_interval_ms=expected_interval_ms)
        if s is not None:
            agreement_stats.append(s)

    # Detail rows on stdout.
    print("window_idx,is_disagreement,n_samples,mean_gap_ms,max_gap_ms,stdev_gap_ms,"
          "n_gaps_above_2x,n_gaps_above_3x,largest_gap_ms")
    for s in disagree_stats + agreement_stats:
        print(f"{s.window_idx},{int(s.is_disagreement)},{s.n_samples},"
              f"{s.mean_gap_ms:.6f},{s.max_gap_ms:.6f},{s.stdev_gap_ms:.6f},"
              f"{s.n_gaps_above_2x},{s.n_gaps_above_3x},{s.largest_gap_ms:.6f}")

    # Summary on stderr.
    print("", file=sys.stderr)
    print(summarize(disagree_stats, "DISAGREEMENT windows"), file=sys.stderr)
    print("", file=sys.stderr)
    print(summarize(agreement_stats, "CONTROL agreement windows"), file=sys.stderr)
    print("", file=sys.stderr)

    # Verdict heuristic.
    if disagree_stats and agreement_stats:
        d_max_max = max(s.max_gap_ms for s in disagree_stats)
        a_max_max = max(s.max_gap_ms for s in agreement_stats)
        d_above_3x = sum(s.n_gaps_above_3x for s in disagree_stats)
        a_above_3x = sum(s.n_gaps_above_3x for s in agreement_stats)
        print(f"# verdict: largest gap in disagreement set = {d_max_max:.4f} ms vs "
              f"control = {a_max_max:.4f} ms (expected = {expected_interval_ms:.4f} ms)",
              file=sys.stderr)
        print(f"# gaps >3x expected: disagree={d_above_3x}  control={a_above_3x}",
              file=sys.stderr)
        if d_above_3x > 5 * max(a_above_3x, 1):
            print("# >>> SUPPORTS hypothesis: disagreement windows have substantially "
                  "more sample-gap outliers", file=sys.stderr)
        elif d_above_3x == 0 and a_above_3x == 0:
            print("# >>> NO sample-gap outliers anywhere: hypothesis falsified, "
                  "accel.csv looks uniformly clean", file=sys.stderr)
        else:
            print("# >>> Indistinguishable: hypothesis likely falsified", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
