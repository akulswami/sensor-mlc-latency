#!/usr/bin/env python3
"""generate_fig1_latency_boxplot_logscale.py
==============================================

Log/common-axis variant of Figure 1, addressing R2's comment that the
original's per-panel independent y-axis caps (900/2200/750 µs) give
each pipeline its own scale, so a box's vertical position is not
comparable across panels. This variant does NOT modify or replace
the original (paper/figures/figure_1_latency_boxplot.png); it writes
a separate figure_1_latency_boxplot_logscale.png for review.

Design:
- 3 side-by-side panels, one per pipeline (unchanged from the original).
- Each panel has 3 boxplots (one per condition, unchanged).
- ONE shared log-scale y-axis across all three panels (sharey=True),
  spanning the full data range (~34 to ~3,900 µs, about 2 orders of
  magnitude across all 9 cells) with no per-panel capping and no
  outliers hidden or annotated away — everything is visible in-frame.
  Log scale was chosen over a shared LINEAR axis because the data
  spans ~112x range: a shared linear axis would crush the low-latency
  cells (mlc-binary, ~34-724 µs) into a sliver near zero while the
  mlc/idle upper tail (~2,600-3,900 µs) dominates the height, making
  the low-latency boxes' internal structure (median, IQR, whiskers)
  illegible. Log scale keeps every cell's box structure readable while
  still putting all three panels on one directly comparable scale.
- Single-line panel titles (unchanged).
- Sample sizes integrated into condition tick labels (unchanged).
- Tukey boxplot conventions: box = IQR, whiskers = 1.5×IQR, outliers as
  points, mean as triangle (unchanged).
- y-axis tick labels shown only on the leftmost panel (ax.label_outer())
  to make the shared-axis visually explicit rather than repeating the
  same scale three times.

Outputs:
  paper/figures/figure_1_latency_boxplot_logscale.png  (raster, 300 DPI)
  paper/figures/figure_1_latency_boxplot_logscale.svg  (vector)
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BLOCKS_DIR = REPO_ROOT / "data" / "training" / "latency-experiment"
CAMPAIGN_ID = "confirmatory-2026-05-26"
OUT_DIR = REPO_ROOT / "paper" / "figures"

PIPELINES = ["host", "mlc", "mlc-binary"]
CONDITIONS = ["idle", "i2c-contention", "stress"]

plt.rcParams.update({
    "font.size": 9,
    "font.family": "sans-serif",
    "axes.linewidth": 0.8,
    "axes.labelsize": 10,
    "axes.titlesize": 11,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})

CONDITION_LABELS = {
    "idle": "idle",
    "i2c-contention": "I²C\ncont.",   # shortened to fit
    "stress": "CPU\nstress",
}

CONDITION_COLORS = {
    "idle": "#648FFF",          # blue
    "i2c-contention": "#FE6100", # orange
    "stress": "#785EF0",         # purple
}

# Single-line panel titles
PIPELINE_TITLES = {
    "host": "(a) host",
    "mlc": "(b) mlc (bank-switch)",
    "mlc-binary": "(c) mlc-binary (no I²C)",
}

# Shared log-scale y-limits across all three panels, covering the full
# observed range (global min ~34.4 µs, global max ~3868.2 µs) with a
# small multiplicative margin. No per-panel cap: nothing is clipped or
# annotated as "above cap" in this variant.
SHARED_YLIM = (25, 5500)


def load_latencies():
    by_cell = defaultdict(list)
    for bdir in sorted(BLOCKS_DIR.glob(f"block-{CAMPAIGN_ID}-b*")):
        meta = json.loads((bdir / "block_metadata.json").read_text())
        cell = (meta["pipeline"], meta["condition"])
        with open(bdir / "trials.csv") as f:
            for row in csv.DictReader(f):
                if row["included"].lower() == "true" and row["latency_us"]:
                    by_cell[cell].append(float(row["latency_us"]))
    return by_cell


def main():
    print(f"[fig1] Loading {CAMPAIGN_ID}...")
    by_cell = load_latencies()
    for cell in sorted(by_cell.keys()):
        print(f"  {cell[0]:12s} {cell[1]:18s}: n={len(by_cell[cell])}")

    fig, axes = plt.subplots(1, 3, figsize=(7.16, 3.6), sharey=True,
                              gridspec_kw={"wspace": 0.12})

    for ax, pipeline in zip(axes, PIPELINES):
        data = [by_cell[(pipeline, c)] for c in CONDITIONS]
        positions = list(range(len(CONDITIONS)))
        colors = [CONDITION_COLORS[c] for c in CONDITIONS]

        bp = ax.boxplot(
            data,
            positions=positions,
            widths=0.55,
            patch_artist=True,
            showmeans=True,
            meanprops={"marker": "^", "markerfacecolor": "white",
                       "markeredgecolor": "black", "markersize": 4, "markeredgewidth": 0.8},
            medianprops={"color": "black", "linewidth": 1.4},
            boxprops={"linewidth": 0.8},
            whiskerprops={"linewidth": 0.8},
            capprops={"linewidth": 0.8},
            flierprops={"marker": "o", "markerfacecolor": "black",
                        "markeredgecolor": "none", "markersize": 1.5, "alpha": 0.35},
        )
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.45)

        # Two-line tick labels: condition + n=...
        tick_labels = []
        for c in CONDITIONS:
            n = len(by_cell[(pipeline, c)])
            tick_labels.append(f"{CONDITION_LABELS[c]}\nn={n}")
        ax.set_xticks(positions)
        ax.set_xticklabels(tick_labels)

        ax.set_yscale("log")
        ax.set_ylim(*SHARED_YLIM)

        ax.set_title(PIPELINE_TITLES[pipeline], fontsize=10, pad=8)
        ax.set_ylabel("Latency (µs, log scale)", fontsize=9)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.yaxis.grid(True, which="major", linestyle="--", alpha=0.4)
        ax.yaxis.grid(True, which="minor", linestyle=":", alpha=0.15)
        ax.set_axisbelow(True)
        ax.label_outer()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png_path = OUT_DIR / "figure_1_latency_boxplot_logscale.png"
    svg_path = OUT_DIR / "figure_1_latency_boxplot_logscale.svg"
    fig.savefig(png_path, dpi=300, bbox_inches="tight", pad_inches=0.15)
    fig.savefig(svg_path, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"[fig1] Wrote {png_path} ({png_path.stat().st_size} bytes)")
    print(f"[fig1] Wrote {svg_path} ({svg_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
