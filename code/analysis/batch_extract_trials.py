#!/usr/bin/env python3
"""batch_extract_trials.py
========================

Run extract_latency_v7.py on all 81 confirmatory blocks. Each block has
its own digital.csv produced by sal_to_csv.py; this script invokes
extract_latency_v7.py per-block with the correct --pipeline argument
(derived from block_metadata.json) and --is-first-arm (every block
starts with a Pin 11 sync edge that must be skipped).

Output: a trials.csv in each block directory.

Usage:
    python3 code/analysis/batch_extract_trials.py [--campaign-id ID]
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXTRACTOR = REPO_ROOT / "code" / "analysis" / "extract_latency_v7.py"
BLOCKS_DIR = REPO_ROOT / "data" / "training" / "latency-experiment"


def extract_block(block_dir):
    """Run extract_latency_v7.py on one block. Returns (ok, msg)."""
    meta_path = block_dir / "block_metadata.json"
    if not meta_path.exists():
        return False, f"{block_dir.name}: no block_metadata.json"

    csv_path = block_dir / "digital.csv"
    if not csv_path.exists():
        return False, f"{block_dir.name}: no digital.csv (run sal_to_csv.py first)"

    out_path = block_dir / "trials.csv"
    if out_path.exists():
        return True, f"{block_dir.name}: trials.csv already exists (skipped)"

    meta = json.loads(meta_path.read_text())
    pipeline = meta.get("pipeline")
    if pipeline not in ("host", "mlc", "mlc-binary"):
        return False, f"{block_dir.name}: unknown pipeline {pipeline!r}"

    cmd = [
        sys.executable, str(EXTRACTOR),
        "--csv", str(csv_path),
        "--out", str(out_path),
        "--pipeline", pipeline,
        "--is-first-arm",  # every block starts with a Pin 11 sync edge
    ]

    t0 = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as e:
        return False, f"{block_dir.name}: subprocess error: {e}"
    dt = time.monotonic() - t0

    if result.returncode != 0:
        # Truncate stderr for log readability
        err = (result.stderr or "")[:200]
        return False, f"{block_dir.name}: extractor exit {result.returncode}: {err}"

    if not out_path.exists():
        return False, f"{block_dir.name}: extractor ran but no trials.csv"

    # Quick line count
    with open(out_path) as f:
        n_lines = sum(1 for _ in f) - 1  # minus header
    return True, f"{block_dir.name}: trials.csv {n_lines} trials in {dt:.1f}s"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign-id", default="confirmatory-2026-05-26",
                    help="Campaign ID (matches block dir prefix)")
    args = ap.parse_args()

    pattern = f"block-{args.campaign_id}-b*"
    dirs = sorted(BLOCKS_DIR.glob(pattern))
    if not dirs:
        print(f"No blocks matching pattern {pattern} in {BLOCKS_DIR}")
        return 1

    print(f"[batch-extract] Processing {len(dirs)} blocks")
    n_ok = 0
    n_skip = 0
    n_fail = 0
    failed = []
    t_start = time.monotonic()
    for i, bdir in enumerate(dirs, start=1):
        ok, msg = extract_block(bdir)
        tag = "OK" if ok else "FAIL"
        print(f"  [{i:3d}/{len(dirs)}] {tag}: {msg}")
        if ok:
            if "skipped" in msg:
                n_skip += 1
            else:
                n_ok += 1
        else:
            n_fail += 1
            failed.append(bdir.name)

    t_total = time.monotonic() - t_start
    print()
    print(f"[batch-extract] Summary: {n_ok} extracted, {n_skip} skipped, {n_fail} failed")
    print(f"[batch-extract] Wall time: {t_total:.1f}s")
    if failed:
        print("Failed blocks:")
        for n in failed:
            print(f"  {n}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
