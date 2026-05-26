#!/usr/bin/env python3
"""section9_perphase_eval.py

Per-phase §9 evaluation under v7.3 burst protocol (per v7.7 amendment,
Zenodo DOI [TBD]).

For motion-arm windows, the expected class is determined per-window from
sweep.log MOTION_PHASE_START / STILL_PHASE_START events:
  - Windows during a motion phase -> expected class 4
  - Windows during a still phase -> expected class 0
  - Still-arm windows (entire arm) -> expected class 0

§9 gate (v7.7):
  - Both pipelines combined accuracy >= 90%
  - Gap = |host - silicon| is REPORTED, not gated

Run:
    python3 code/analysis/section9_perphase_eval.py \
        --session-dir data/training/2026-05-26-section9 \
        --processed-dir data/processed/2026-05-26-section9

The processed-dir must contain host_still.csv, host_motion.csv,
silicon_still.csv, silicon_motion.csv produced by replay_parity +
silicon_align (see section9_revalidate_w75.sh for the upstream pipeline).
"""

import argparse
import csv
import json
import sys
from pathlib import Path


def parse_sweep_log(sweep_log_path):
    """Return list of (motion_start_rel_s, motion_end_rel_s) intervals."""
    phase_events = []
    with open(sweep_log_path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.strip().split(",")
            if len(parts) < 3:
                continue
            try:
                ts_us = int(parts[0])
                event = parts[1]
            except ValueError:
                continue
            if event in ("START", "END", "MOTION_PHASE_START", "STILL_PHASE_START"):
                phase_events.append((ts_us, event))

    start_event = next(e for e in phase_events if e[1] == "START")
    sweep_start_us = start_event[0]

    motion_intervals = []
    current_motion_start = None
    for ts_us, event in phase_events:
        rel_s = (ts_us - sweep_start_us) / 1e6
        if event == "MOTION_PHASE_START":
            current_motion_start = rel_s
        elif event in ("STILL_PHASE_START", "END") and current_motion_start is not None:
            motion_intervals.append((current_motion_start, rel_s))
            current_motion_start = None

    sweep_duration_s = (phase_events[-1][0] - sweep_start_us) / 1e6
    return motion_intervals, sweep_duration_s


def load_classes(csv_path):
    rows = []
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            rows.append((float(r["t_window_end_s"]), int(r["class"])))
    return rows


def is_motion(t_s, motion_intervals):
    for s, e in motion_intervals:
        if s <= t_s < e:
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--session-dir", required=True, type=Path,
                    help="Path to the capture session directory")
    ap.add_argument("--processed-dir", required=True, type=Path,
                    help="Path to the directory with host/silicon_*.csv")
    args = ap.parse_args()

    sweep_log = args.session_dir / "motion" / "sweep.log"
    if not sweep_log.exists():
        sys.exit(f"sweep.log not found: {sweep_log}")

    motion_intervals, sweep_duration_s = parse_sweep_log(sweep_log)
    print(f"Sweep duration: {sweep_duration_s:.1f}s")
    print(f"Motion phases: {len(motion_intervals)} "
          f"(total motion time: {sum(e-s for s,e in motion_intervals):.1f}s, "
          f"{100*sum(e-s for s,e in motion_intervals)/sweep_duration_s:.1f}%)")
    print()

    host_still = load_classes(args.processed_dir / "host_still.csv")
    host_motion = load_classes(args.processed_dir / "host_motion.csv")
    silicon_still = load_classes(args.processed_dir / "silicon_still.csv")
    silicon_motion = load_classes(args.processed_dir / "silicon_motion.csv")

    h_still_corr = sum(1 for _, c in host_still if c == 0)
    s_still_corr = sum(1 for _, c in silicon_still if c == 0)

    def motion_arm_acc(preds):
        corr = 0
        for t, c in preds:
            expected = 4 if is_motion(t, motion_intervals) else 0
            if c == expected:
                corr += 1
        return corr

    h_mot_corr = motion_arm_acc(host_motion)
    s_mot_corr = motion_arm_acc(silicon_motion)

    h_still_n = len(host_still)
    h_mot_n = len(host_motion)
    s_still_n = len(silicon_still)
    s_mot_n = len(silicon_motion)

    h_comb = 100 * (h_still_corr + h_mot_corr) / (h_still_n + h_mot_n)
    s_comb = 100 * (s_still_corr + s_mot_corr) / (s_still_n + s_mot_n)
    gap = abs(h_comb - s_comb)

    print("=== Per-pipeline accuracy (per-phase ground truth) ===")
    print(f"  HOST still:    {100*h_still_corr/h_still_n:.4f}% ({h_still_corr}/{h_still_n})")
    print(f"  HOST motion:   {100*h_mot_corr/h_mot_n:.4f}% ({h_mot_corr}/{h_mot_n})")
    print(f"  SILICON still: {100*s_still_corr/s_still_n:.4f}% ({s_still_corr}/{s_still_n})")
    print(f"  SILICON motion:{100*s_mot_corr/s_mot_n:.4f}% ({s_mot_corr}/{s_mot_n})")
    print()
    print(f"=== Combined ===")
    print(f"  HOST:    {h_comb:.4f}%")
    print(f"  SILICON: {s_comb:.4f}%")
    print(f"  Gap:     {gap:.4f}pp (reported, not gated per v7.7 Change 2)")
    print()
    print(f"=== §9 v7.7 gate ===")
    h_verdict = "PASS" if h_comb >= 90 else "FAIL"
    s_verdict = "PASS" if s_comb >= 90 else "FAIL"
    print(f"  HOST >= 90%:    {h_comb:.2f}% -> {h_verdict}")
    print(f"  SILICON >= 90%: {s_comb:.2f}% -> {s_verdict}")
    if h_comb >= 90 and s_comb >= 90:
        print()
        print("  RESULT: PASS")
    else:
        print()
        print("  RESULT: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
