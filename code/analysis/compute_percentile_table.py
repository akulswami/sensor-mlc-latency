#!/usr/bin/env python3
"""compute_percentile_table.py
===============================

Canonical p95/p99/max latency table for the confirmatory-2026-05-26
campaign, for all 9 pipeline x condition cells. This table was
previously claimed as "computed" in docs/lab-notebook/2026-09-21-
session-summary.md but was never backed by any committed script or
data artifact -- this script fills that gap.

Source data: the per-trial `trials.csv` files under
data/training/latency-experiment/block-confirmatory-2026-05-26-b*-
<pipeline>-<condition>/, i.e. the same 81 blocks (9 per cell) used by
code/analysis/run_confirmatory_stats.py and every other confirmatory-
campaign analysis in this repo. Confirmed via campaign_manifest.json
at data/training/confirmatory-2026-05-26/campaign_manifest.json
(81/81 blocks) before computing.

Quantile method: numpy's default linear-interpolation quantile
(np.percentile(..., method="linear"), which is also numpy's default
method), matching the convention already confirmed in the mlc-binary/
i2c-contention verification (median 49.4 / p95 246.7 us). No new
percentile method is introduced here.

Only trials with included == "true" are counted, matching every other
confirmatory-campaign analysis script in this repo (run_confirmatory_
stats.py, analyze_energy_and_latency.py, generate_fig1_latency_
boxplot.py).

Outputs:
  data/processed/confirmatory-2026-05-26/percentile_table.csv
  data/processed/confirmatory-2026-05-26/percentile_table.md
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BLOCKS_DIR = REPO_ROOT / "data" / "training" / "latency-experiment"
CAMPAIGN_ID = "confirmatory-2026-05-26"
OUT_DIR = REPO_ROOT / "data" / "processed" / CAMPAIGN_ID

PIPELINES = ["host", "mlc", "mlc-binary"]
CONDITIONS = ["idle", "i2c-contention", "stress"]


def load_latencies():
    """Load included per-trial latencies grouped by (pipeline, condition)."""
    by_cell = defaultdict(list)
    for bdir in sorted(BLOCKS_DIR.glob(f"block-{CAMPAIGN_ID}-b*")):
        meta = json.loads((bdir / "block_metadata.json").read_text())
        cell = (meta["pipeline"], meta["condition"])
        with open(bdir / "trials.csv") as f:
            for row in csv.DictReader(f):
                if row.get("included", "").strip().lower() == "true" and row.get("latency_us"):
                    by_cell[cell].append(float(row["latency_us"]))
    return by_cell


def main():
    print(f"[percentile_table] Loading {CAMPAIGN_ID}...")
    block_dirs = sorted(BLOCKS_DIR.glob(f"block-{CAMPAIGN_ID}-b*"))
    print(f"[percentile_table] Found {len(block_dirs)} blocks under {BLOCKS_DIR}")

    by_cell = load_latencies()

    rows = []
    for pipeline in PIPELINES:
        for condition in CONDITIONS:
            lats = np.array(by_cell[(pipeline, condition)])
            n = len(lats)
            p25 = float(np.percentile(lats, 25))
            median = float(np.percentile(lats, 50))
            p75 = float(np.percentile(lats, 75))
            p95 = float(np.percentile(lats, 95))
            p99 = float(np.percentile(lats, 99))
            mx = float(lats.max())
            mean = float(lats.mean())
            stdev = float(lats.std(ddof=1))
            rows.append({
                "pipeline": pipeline,
                "condition": condition,
                "n": n,
                "p25_us": round(p25, 4),
                "median_us": round(median, 4),
                "p75_us": round(p75, 4),
                "p95_us": round(p95, 4),
                "p99_us": round(p99, 4),
                "max_us": round(mx, 4),
                "mean_us": round(mean, 4),
                "stdev_us": round(stdev, 4),
            })
            print(f"  {pipeline:12s} {condition:18s} n={n:4d} "
                  f"p25={p25:9.4f} median={median:9.4f} p75={p75:9.4f} "
                  f"p95={p95:9.4f} p99={p99:9.4f} max={mx:9.4f} "
                  f"mean={mean:9.4f} stdev={stdev:9.4f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    fieldnames = ["pipeline", "condition", "n", "p25_us", "median_us", "p75_us",
                  "p95_us", "p99_us", "max_us", "mean_us", "stdev_us"]

    csv_path = OUT_DIR / "percentile_table.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[percentile_table] Wrote {csv_path}")

    md_path = OUT_DIR / "percentile_table.md"
    with open(md_path, "w") as f:
        f.write("# Canonical latency summary table (confirmatory-2026-05-26)\n\n")
        f.write("Source: `data/training/latency-experiment/block-confirmatory-2026-05-26-"
                "b*-<pipeline>-<condition>/trials.csv` (81 blocks, 9 per cell). "
                "Quantiles: `np.percentile` default linear interpolation. "
                "stdev: sample stdev (`ddof=1`). "
                "Only `included == true` trials counted.\n\n")
        f.write("| pipeline | condition | n | p25 (µs) | median (µs) | p75 (µs) | "
                "p95 (µs) | p99 (µs) | max (µs) | mean (µs) | stdev (µs) |\n")
        f.write("|----------|-----------|---:|---------:|------------:|---------:|"
                "---------:|---------:|---------:|----------:|-----------:|\n")
        for r in rows:
            f.write(f"| {r['pipeline']} | {r['condition']} | {r['n']} | "
                     f"{r['p25_us']:.1f} | {r['median_us']:.1f} | {r['p75_us']:.1f} | "
                     f"{r['p95_us']:.1f} | {r['p99_us']:.1f} | {r['max_us']:.1f} | "
                     f"{r['mean_us']:.1f} | {r['stdev_us']:.1f} |\n")
    print(f"[percentile_table] Wrote {md_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
