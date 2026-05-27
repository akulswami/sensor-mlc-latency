#!/usr/bin/env python3
"""sal_to_csv.py
==============

Batch-convert Saleae .sal capture files to digital.csv format using the
Logic 2 automation API.

Each .sal file lives in its own block directory (e.g.,
data/training/latency-experiment/block-confirmatory-2026-05-26-bNNN-*/saleae.sal).
This script loads each .sal, exports the digital channels to digital.csv
in the same directory, and closes the capture before moving on.

The CSV format matches what extract_latency_v7.py expects.

Usage:
    python3 code/analysis/sal_to_csv.py [BLOCK_DIR ...]
    python3 code/analysis/sal_to_csv.py --all-confirmatory

Prerequisites:
    - Logic 2 must be running on this host
    - logic2-automation package installed (saleae.automation)
"""

import argparse
import sys
import time
from pathlib import Path

from saleae import automation

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_BLOCKS_DIR = REPO_ROOT / "data" / "training" / "latency-experiment"
DIGITAL_CHANNELS = [0, 1, 2]  # D0 = INT1, D1 = decision GPIO, D2 = PCA9685 PWM


def convert_block(manager, block_dir):
    """Convert one block's saleae.sal -> digital.csv. Returns (ok, msg)."""
    # Resolve to absolute paths — Logic 2 runs in its own CWD and cannot
    # resolve relative paths the caller passed in.
    block_dir = block_dir.resolve()
    sal_path = (block_dir / "saleae.sal").resolve()
    if not sal_path.exists():
        return False, f"no saleae.sal in {block_dir.name}"
    csv_path = block_dir / "digital.csv"
    if csv_path.exists():
        return True, f"{block_dir.name}: digital.csv already exists (skipped)"

    t0 = time.monotonic()
    try:
        capture = manager.load_capture(str(sal_path))
        try:
            capture.export_raw_data_csv(
                directory=str(block_dir),
                digital_channels=DIGITAL_CHANNELS,
            )
        finally:
            capture.close()
    except Exception as e:
        return False, f"{block_dir.name}: {type(e).__name__}: {e}"

    dt = time.monotonic() - t0
    csv_size_kb = csv_path.stat().st_size / 1024
    return True, f"{block_dir.name}: digital.csv {csv_size_kb:.1f} KB in {dt:.1f}s"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("block_dirs", nargs="*", type=Path,
                    help="Block directories to convert (each must contain saleae.sal)")
    ap.add_argument("--all-confirmatory", action="store_true",
                    help="Process all data/training/latency-experiment/block-confirmatory-2026-05-26-*/ dirs")
    ap.add_argument("--port", type=int, default=10430,
                    help="Logic 2 automation port (default 10430)")
    args = ap.parse_args()

    if args.all_confirmatory:
        dirs = sorted(DEFAULT_BLOCKS_DIR.glob("block-confirmatory-2026-05-26-b*"))
    else:
        dirs = args.block_dirs

    if not dirs:
        print("No block directories specified. Use --all-confirmatory or pass paths.")
        return 1

    print(f"[sal_to_csv] Processing {len(dirs)} blocks via Logic 2 (port {args.port})")

    n_ok = 0
    n_fail = 0
    n_skip = 0
    failed = []
    t_start = time.monotonic()
    with automation.Manager.connect(port=args.port) as manager:
        for i, bdir in enumerate(dirs, start=1):
            ok, msg = convert_block(manager, bdir)
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
    print(f"[sal_to_csv] Summary: {n_ok} converted, {n_skip} skipped (already had csv), {n_fail} failed")
    print(f"[sal_to_csv] Wall time: {t_total:.1f}s")
    if failed:
        print(f"[sal_to_csv] Failed blocks:")
        for name in failed:
            print(f"  {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
