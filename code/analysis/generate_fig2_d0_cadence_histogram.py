#!/usr/bin/env python3
"""generate_fig2_d0_cadence_histogram.py
==========================================

Generate Figure 2: Inter-trial D0 gap distribution showing the MLC's
706.5 ms intrinsic decision cadence quantization.

Design rationale
================

The MLC silicon fires INT1 (D0 rising edge) at a fixed intrinsic cadence
of ~706.5 ms — empirically the period at which the MLC reports
classification decisions, equal to one-quarter of the 75-sample × 26 Hz
window period (≈ 2.885 s / 4 ≈ 0.721 s; observed peak at 706.5 ms).

When we compute gaps between consecutive D0 events that were paired
with stimulus trials (from trials.csv `t_d0_s`), the resulting
distribution is QUANTIZED to integer multiples of 706.5 ms. This is
because the MLC fires only at its own 706.5 ms clock, regardless of
when the host or stimulus expects to read.

The figure pools D0 gaps across all MLC and MLC-binary blocks
(idle + i2c-contention + stress conditions, ~3,130 gaps total) and
shows the histogram with vertical reference lines at integer multiples
of 706.5 ms.

The stimulus protocol delivers transitions every ~5 s (10 s cycle,
two transitions per cycle), so the dominant peaks fall at:
  - n=5 quantum: 3532 ms (one cycle minus margin)
  - n=9 quantum: 6358 ms (two cycles minus margin)
  - n=6, 8, 10 quanta: surrounding "near-miss" gaps from cycle-to-cycle variation

The discreteness of the peaks — sharp accumulation at exact n × 706.5 ms,
empty bins between — is the visible signature of the silicon's
cadence quantization.

Note: this is inter-TRIAL D0 gap, not inter-EDGE D0 gap. Multiple D0
events that fire between trials are NOT visible in trials.csv. The
inter-EDGE analysis would require parsing digital.csv (gitignored,
reproducible from saleae.sal via sal_to_csv.py). Inter-trial gaps
demonstrate the cadence claim at the seconds timescale; they are
sufficient and use only committed data.

Outputs:
  paper/figures/figure_2_d0_cadence_histogram.png
  paper/figures/figure_2_d0_cadence_histogram.svg
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

MLC_PIPELINES = ("mlc", "mlc-binary")
CADENCE_MS = 706.5
MAX_QUANTUM = 12  # plot reference lines up to n=12 quanta (~8478 ms)

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


def load_inter_trial_gaps():
    """Returns list of inter-trial D0 gaps in ms, pooled across MLC pipelines."""
    gaps = []
    for bdir in sorted(BLOCKS_DIR.glob(f"block-{CAMPAIGN_ID}-b*")):
        meta = json.loads((bdir / "block_metadata.json").read_text())
        if meta["pipeline"] not in MLC_PIPELINES:
            continue
        d0s = []
        with open(bdir / "trials.csv") as f:
            for row in csv.DictReader(f):
                if row.get("t_d0_s"):
                    d0s.append(float(row["t_d0_s"]))
        d0s.sort()
        for i in range(1, len(d0s)):
            gaps.append((d0s[i] - d0s[i-1]) * 1000.0)  # convert to ms
    return gaps


def main():
    print(f"[fig2] Loading {CAMPAIGN_ID} MLC + MLC-binary blocks...")
    gaps = load_inter_trial_gaps()
    print(f"[fig2] Loaded {len(gaps)} inter-trial D0 gaps")
    print(f"[fig2] Range: {min(gaps):.1f} ms to {max(gaps):.1f} ms")

    # Clip extreme outliers for visualization (max plotted gap = 12 × 706.5 = ~8.5 s)
    plot_max_ms = (MAX_QUANTUM + 0.5) * CADENCE_MS  # ~8.83 s
    gaps_clipped = [g for g in gaps if g <= plot_max_ms]
    n_clipped = len(gaps) - len(gaps_clipped)
    print(f"[fig2] {n_clipped} gaps above {plot_max_ms:.0f} ms clipped from plot ({100*n_clipped/len(gaps):.1f}%)")

    fig, ax = plt.subplots(figsize=(7.16, 3.3))

    # Histogram: bin width ~50 ms (small enough to see quantization gaps between peaks)
    bin_width_ms = 50
    bins = np.arange(0, plot_max_ms + bin_width_ms, bin_width_ms)
    n, _, patches = ax.hist(gaps_clipped, bins=bins, color="#648FFF", alpha=0.85,
                            edgecolor="white", linewidth=0.3)

    # Vertical reference lines at integer multiples of 706.5 ms.
    # Lines are drawn at every quantum (visual reference), but labels appear
    # only where data is observable (5×T through 10×T). Labels in the
    # 1×T-4×T range are omitted because the stimulus protocol guarantees
    # gaps >= ~3.5 s and no data falls there; cluttering with empty labels
    # would mislead the reader. The absence is itself a meaningful
    # observation, called out in the annotation box.
    for q in range(1, MAX_QUANTUM + 1):
        x = q * CADENCE_MS
        ax.axvline(x, color="black", linestyle=":", linewidth=0.7, alpha=0.55, zorder=0)
        # Only label quanta where data exists in our distribution
        if 5 <= q <= 10:
            ax.text(x, max(n) * 1.04,
                    f"{q}×T", ha="center", va="bottom",
                    fontsize=8.5, color="black", style="italic", fontweight="medium")

    ax.set_xlabel("Inter-trial D0 gap (ms)", fontsize=10)
    ax.set_ylabel("Count", fontsize=10)
    ax.set_xlim(0, plot_max_ms)
    ax.set_ylim(0, max(n) * 1.18)  # extra headroom for the q-labels

    # Annotation explaining T and the stimulus-protocol filter
    ax.text(
        0.03, 0.96,
        ("T = 706.5 ms\n"
         "(MLC silicon's intrinsic\n"
         "decision cadence)\n\n"
         "Stimulus protocol delivers a\n"
         "transition every ~5 s, so\n"
         "inter-trial gaps cluster at\n"
         "5×T and 9×T (1 vs 2 cycles);\n"
         "smaller quanta (1×T–4×T)\n"
         "do not occur in this data."),
        transform=ax.transAxes, ha="left", va="top",
        fontsize=7.5, color="black",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                  edgecolor="lightgray", linewidth=0.6, alpha=0.95),
    )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)

    title_str = (
        f"Inter-trial D0 gap distribution (mlc + mlc-binary pipelines, "
        f"n = {len(gaps_clipped):,} gaps; pooled across conditions)"
    )
    ax.set_title(title_str, fontsize=9, pad=10)

    # Footnote
    fig.text(
        0.5, -0.05,
        f"Vertical dotted lines mark integer multiples of T = 706.5 ms. "
        f"Bin width = {bin_width_ms} ms. {n_clipped} gaps > {plot_max_ms:.0f} ms ({100*n_clipped/len(gaps):.1f}%) "
        f"not shown (truncation chosen for visibility; full distribution extends to {max(gaps):.0f} ms).",
        ha="center", va="top", fontsize=7, color="dimgray", style="italic", wrap=True,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png_path = OUT_DIR / "figure_2_d0_cadence_histogram.png"
    svg_path = OUT_DIR / "figure_2_d0_cadence_histogram.svg"
    fig.savefig(png_path, dpi=300, bbox_inches="tight", pad_inches=0.15)
    fig.savefig(svg_path, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"[fig2] Wrote {png_path} ({png_path.stat().st_size} bytes)")
    print(f"[fig2] Wrote {svg_path} ({svg_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
