#!/usr/bin/env python3
"""generate_fig1_latency_boxplot.py
=====================================

Generate Figure 1: Per-cell latency distribution boxplot for the IEEE
Sensors Letters paper.

Design:
- 3 side-by-side panels, one per pipeline.
- Each panel has 3 boxplots (one per condition).
- Independent y-axes per panel, CAPPED at p99 + buffer to keep box structure
  visible; outliers above the cap are noted textually rather than allowed
  to dominate the y-axis.
- Single-line panel titles (descriptions move to caption).
- Sample sizes integrated into condition tick labels (no separate row).
- Tukey boxplot conventions: box = IQR, whiskers = 1.5×IQR, outliers as
  points, mean as triangle.

Outputs:
  paper/figures/figure_1_latency_boxplot.png  (raster, 300 DPI)
  paper/figures/figure_1_latency_boxplot.svg  (vector)
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

# Y-axis cap per panel: at p99 + headroom for whisker. Outliers above the
# cap are noted in text rather than letting them dominate auto-scaling.
# Values derived from inspection of the data distribution.
PANEL_Y_CAP = {
    "host": 900,        # captures most up to ~p98 of host/stress; one outlier ~3505 µs above
    "mlc": 2200,        # captures mlc/idle p95 of 1781 + headroom
    "mlc-binary": 750,  # mlc-binary max is 724, full range visible
}


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

    fig, axes = plt.subplots(1, 3, figsize=(7.16, 3.6), gridspec_kw={"wspace": 0.30})

    # Track outliers-above-cap per cell for annotation
    above_cap_info = {}

    for ax, pipeline in zip(axes, PIPELINES):
        data = [by_cell[(pipeline, c)] for c in CONDITIONS]
        positions = list(range(len(CONDITIONS)))
        colors = [CONDITION_COLORS[c] for c in CONDITIONS]

        # Count outliers above cap for footnote
        y_cap = PANEL_Y_CAP[pipeline]
        n_above_cap = sum(1 for cell_data in data for v in cell_data if v > y_cap)
        max_val = max((max(cell_data) for cell_data in data if cell_data), default=0)
        if n_above_cap > 0:
            above_cap_info[pipeline] = (n_above_cap, max_val)

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

        ax.set_ylim(0, y_cap)

        # Annotation in upper-right if we capped outliers
        if pipeline in above_cap_info:
            n_above, max_val = above_cap_info[pipeline]
            ax.text(
                0.97, 0.97,
                f"{n_above} outlier{'s' if n_above != 1 else ''}\nabove (max {max_val:.0f} µs)",
                transform=ax.transAxes,
                ha="right", va="top",
                fontsize=7, color="dimgray", style="italic",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor="lightgray", linewidth=0.5, alpha=0.85),
            )

        ax.set_title(PIPELINE_TITLES[pipeline], fontsize=10, pad=8)
        ax.set_ylabel("Latency (µs)", fontsize=9)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.yaxis.grid(True, linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)

    # Footnote: explains boxplot conventions
    fig.text(
        0.5, -0.04,
        "Box = IQR (Q1–Q3); whiskers = 1.5×IQR; △ = mean; ● = outlier. "
        "Y-axes are capped per panel to preserve box-structure visibility; outliers above each cap are noted in-panel.",
        ha="center", va="top", fontsize=7, color="dimgray", style="italic",
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png_path = OUT_DIR / "figure_1_latency_boxplot.png"
    svg_path = OUT_DIR / "figure_1_latency_boxplot.svg"
    fig.savefig(png_path, dpi=300, bbox_inches="tight", pad_inches=0.15)
    fig.savefig(svg_path, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"[fig1] Wrote {png_path} ({png_path.stat().st_size} bytes)")
    print(f"[fig1] Wrote {svg_path} ({svg_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
