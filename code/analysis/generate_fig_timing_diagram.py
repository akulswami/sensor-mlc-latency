#!/usr/bin/env python3
"""generate_fig_timing_diagram.py
==================================

R1 pt.3 timing diagram: a single representative trial's D0/D1(/D2)
wire-level edges, plus a schematic (not measured) callout for the
three-transaction I2C bank-switch read that happens inside the D0->D1
gap.

GUARDRAIL (see docs/DECISIONS.md): the source block
(block-affinity-2026-09-21-mlc001-mlc-idle) is pinned-affinity data
with no unpinned control. It is FIGURE-SOURCE ONLY and must never be
used as quantitative latency evidence -- this figure shows one
illustrative trial's wire-level timing, not a campaign statistic. Do
not caption or label any value here as "typical" or "median trial".

Investigated and confirmed before writing this script (see chat
history / lab notebook, 2026-09-23):
  - The .sal capture for this block contains exactly 3 digital
    channels (D0/D1/D2) and 0 analog channels -- confirmed by loading
    the capture via the Logic 2 automation API and exporting with no
    channel filter (which exports everything present). SDA/SCL were
    never wired to the Saleae in this session.
  - Consequently, the three I2C transactions inside the D0->D1 gap
    (write FUNC_CFG_ACCESS, read MLC0_SRC, write FUNC_CFG_ACCESS back)
    cannot be shown as measured data -- there is no captured signal
    for the I2C bus at all. That structure is drawn here as a labeled
    SCHEMATIC, explicitly marked as such, grounded in:
      - code/jetson/mlc_pipeline/latency_test_mlc.c:124-134
        (read_mlc_src(), the actual as-built register sequence)
      - AN5259 (LSM6DSOX MLC application note), cited as [2] in the
        manuscript bibliography, for the mandatory bank-switch
        protocol this sequence implements.
  - The measured panel uses the real edges from
    data/training/latency-experiment/block-affinity-2026-09-21-mlc001-
    mlc-idle/digital.csv for trial_id=43 (t_d0_s=219.95138138,
    latency_us=481.8, matching trials.csv exactly), computed
    programmatically from the CSV, not hardcoded.

Design: two panels, deliberately NOT sharing a time axis or visual
style, so measured and schematic content cannot be mistaken for one
continuous trace:
  (a) top panel: real measured D0/D1/D2 step-plot over ~13 ms around
      trial 43, in milliseconds relative to the D0 rising edge, with
      the D0->D1 gap and D1 pulse width annotated from the computed
      (not hardcoded) edge times. A zoomed inset shows the D1 pulse
      (3.24 us; invisible at the panel's native ms scale).
  (b) bottom panel: a schematic block diagram (no numeric time axis,
      explicit "SCHEMATIC -- NOT TO SCALE" label, hatched fill,
      dashed border) showing the three named I2C transactions that
      occur somewhere inside the D0->D1 interval, with a citation to
      the code and AN5259.

Outputs:
  paper/figures/figure_timing_diagram.png  (raster, 300 DPI)
  paper/figures/figure_timing_diagram.svg  (vector)
"""

import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.ticker import AutoMinorLocator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BLOCK_DIR = (REPO_ROOT / "data" / "training" / "latency-experiment"
             / "block-affinity-2026-09-21-mlc001-mlc-idle")
OUT_DIR = REPO_ROOT / "paper" / "figures"
TRIAL_ID = "43"

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

CHANNEL_COLORS = {
    "D0": "#648FFF",   # blue, matches fig1/fig2 idle color
    "D1": "#FE6100",   # orange, matches fig1/fig2 contention color
    "D2": "#785EF0",   # purple, matches fig1/fig2 stress color
}


def load_trial_d0_time():
    """Return t_d0_s for TRIAL_ID from trials.csv (used only to locate
    the display window; all plotted/annotated values come from digital.csv
    edges, not from this file)."""
    with open(BLOCK_DIR / "trials.csv") as f:
        for row in csv.DictReader(f):
            if row["trial_id"] == TRIAL_ID:
                return float(row["t_d0_s"]), float(row["latency_us"])
    raise ValueError(f"trial_id {TRIAL_ID} not found in trials.csv")


def load_edges_in_window(t_start, t_end):
    """Return {channel: [(time_s, level), ...]} of transitions within
    [t_start, t_end], plus the initial level of each channel at t_start."""
    edges = {0: [], 1: [], 2: []}
    prev = None
    initial = None
    with open(BLOCK_DIR / "digital.csv") as f:
        reader = csv.reader(f)
        next(reader)  # header
        for row in reader:
            t = float(row[0])
            levels = (int(row[1]), int(row[2]), int(row[3]))
            if t < t_start:
                prev = levels
                continue
            if initial is None:
                initial = prev if prev is not None else levels
            if t > t_end:
                break
            if prev is not None and levels != prev:
                for ch in range(3):
                    if levels[ch] != prev[ch]:
                        edges[ch].append((t, levels[ch]))
            prev = levels
    return edges, (initial or (0, 0, 0))


def build_steps(edges_ch, initial_level, t_start, t_end):
    """Turn a list of (time, level) transitions into step-plot x/y arrays
    spanning [t_start, t_end]."""
    xs = [t_start]
    ys = [initial_level]
    for t, lvl in edges_ch:
        xs.append(t)
        ys.append(ys[-1])
        xs.append(t)
        ys.append(lvl)
    xs.append(t_end)
    ys.append(ys[-1])
    return xs, ys


def main():
    print("[timing_diagram] Loading trial metadata...")
    t_d0_trials, latency_us_trials = load_trial_d0_time()
    print(f"[timing_diagram] trial_id={TRIAL_ID}: t_d0_s={t_d0_trials}, "
          f"latency_us(trials.csv)={latency_us_trials}")

    # Window: ~1 ms lead-in before D0 rise, ~2 ms tail after D0 falls.
    # D0's pulse is ~9 ms, so this gives a ~12-13 ms total window.
    t_start = t_d0_trials - 0.0010
    t_end = t_d0_trials + 0.0120

    edges, initial = load_edges_in_window(t_start, t_end)
    print(f"[timing_diagram] Window [{t_start:.6f}, {t_end:.6f}] s, "
          f"initial levels D0/D1/D2 = {initial}")
    for ch, name in ((0, "D0"), (1, "D1"), (2, "D2")):
        print(f"  {name} edges: {edges[ch]}")

    # Extract the specific edges we need for annotation, computed from
    # the data (not hardcoded), matching what the trials.csv row implies.
    d0_rises = [t for t, lvl in edges[0] if lvl == 1]
    d0_falls = [t for t, lvl in edges[0] if lvl == 0]
    d1_rises = [t for t, lvl in edges[1] if lvl == 1]
    d1_falls = [t for t, lvl in edges[1] if lvl == 0]
    assert len(d0_rises) == 1 and len(d0_falls) == 1, "expected exactly one D0 pulse in window"
    assert len(d1_rises) == 1 and len(d1_falls) == 1, "expected exactly one D1 pulse in window"
    t_d0_rise, t_d0_fall = d0_rises[0], d0_falls[0]
    t_d1_rise, t_d1_fall = d1_rises[0], d1_falls[0]

    gap_us = (t_d1_rise - t_d0_rise) * 1e6
    d0_width_ms = (t_d0_fall - t_d0_rise) * 1e3
    d1_width_us = (t_d1_fall - t_d1_rise) * 1e6
    print(f"[timing_diagram] Computed: D0->D1 gap = {gap_us:.2f} us, "
          f"D0 pulse width = {d0_width_ms:.3f} ms, D1 pulse width = {d1_width_us:.2f} us")

    # Time axis in ms relative to the D0 rising edge.
    t0 = t_d0_rise

    fig, (ax_meas, ax_schem) = plt.subplots(
        2, 1, figsize=(7.16, 6.4),
        gridspec_kw={"height_ratios": [1.15, 1.0], "hspace": 0.55},
    )

    # ---------------- Panel (a): measured D0/D1/D2 ----------------
    lanes = [("D2", 2, 0.0), ("D1", 1, 1.4), ("D0", 0, 2.8)]
    for name, ch_idx, y_base in lanes:
        xs, ys = build_steps(edges[ch_idx], initial[ch_idx], t_start, t_end)
        xs_ms = [(x - t0) * 1e3 for x in xs]
        ys_shifted = [y_base + 0.9 * y for y in ys]
        ax_meas.step(xs_ms, ys_shifted, where="post",
                     color=CHANNEL_COLORS[name], linewidth=1.6)
        ax_meas.text(-1.35, y_base + 0.45, name, ha="right", va="center",
                     fontsize=9, fontweight="bold", color=CHANNEL_COLORS[name])

    # D0->D1 gap annotation (upper area, clear of all three lanes)
    gap_y = 4.15
    ax_meas.annotate(
        "", xy=((t_d1_rise - t0) * 1e3, gap_y), xytext=((t_d0_rise - t0) * 1e3, gap_y),
        arrowprops=dict(arrowstyle="<->", color="black", linewidth=0.9),
    )
    ax_meas.text((t_d0_rise + t_d1_rise) / 2 * 1e3 - t0 * 1e3, gap_y + 0.12,
                 f"D0→D1 gap: {gap_us:.1f} µs\n(measured, trial {TRIAL_ID}, illustrative single-trial timing)",
                 ha="center", va="bottom", fontsize=7.5, style="italic")

    # D0 pulse width annotation: short leader confined to the gap between
    # the D0 lane (bottom at y=2.8) and the D1 lane (top at y=2.3).
    d0_mid_ms = (t_d0_rise - t0) * 1e3 + d0_width_ms / 2
    ax_meas.plot([d0_mid_ms, d0_mid_ms], [2.42, 2.78], color="gray", linewidth=0.7)
    ax_meas.text(d0_mid_ms, 2.36, f"D0 (INT1) pulse: {d0_width_ms:.2f} ms",
                 ha="center", va="top", fontsize=7.5, color="#1a1a1a")

    # D1 pulse width annotation: short leader confined to the gap between
    # the D1 lane (bottom at y=1.4) and the D2 lane (top at y=0.9), pointing
    # up at the (visually thin, ~3 us wide) spike from below.
    d1_mid_ms = (t_d1_rise - t0) * 1e3 + d1_width_us * 1e-3 / 2
    ax_meas.annotate(
        f"D1 pulse width: {d1_width_us:.2f} µs (measured;\nvisually a single line at this ms scale)",
        xy=(d1_mid_ms, 1.42), xytext=(d1_mid_ms + 2.6, 1.05),
        ha="left", va="center", fontsize=7.5, color="#1a1a1a",
        arrowprops=dict(arrowstyle="->", color="gray", linewidth=0.7),
    )

    ax_meas.set_xlim((t_start - t0) * 1e3, (t_end - t0) * 1e3)
    ax_meas.set_ylim(-0.3, 4.9)
    ax_meas.set_yticks([])
    ax_meas.set_xlabel("Time relative to D0 rising edge (ms)", fontsize=9)
    ax_meas.spines["top"].set_visible(False)
    ax_meas.spines["right"].set_visible(False)
    ax_meas.spines["left"].set_visible(False)
    ax_meas.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax_meas.set_title(
        f"(a) Measured wire-level edges — one representative trial "
        f"(trial {TRIAL_ID}, block mlc001, illustrative only)",
        fontsize=9.5, pad=8,
    )

    # ---------------- Panel (b): schematic I2C structure ----------------
    ax_schem.set_xlim(0, 10)
    ax_schem.set_ylim(0, 3)
    ax_schem.axis("off")

    # Overall bordered box marking this whole panel as schematic
    outer = mpatches.FancyBboxPatch(
        (0.15, 0.15), 9.7, 2.7, boxstyle="round,pad=0.05,rounding_size=0.08",
        linewidth=1.2, linestyle="--", edgecolor="#444444", facecolor="#f7f7f7",
    )
    ax_schem.add_patch(outer)

    ax_schem.text(5.0, 2.55, "SCHEMATIC — NOT TO SCALE — NOT INDEPENDENTLY MEASURED",
                  ha="center", va="center", fontsize=8.5, fontweight="bold", color="#8a2f00")

    steps = [
        ("write\nFUNC_CFG_ACCESS\n(bank → embedded)", "#648FFF"),
        ("read\nMLC0_SRC", "#FE6100"),
        ("write\nFUNC_CFG_ACCESS\n(bank → user)", "#648FFF"),
    ]
    box_w, gap = 2.7, 0.55
    x0 = (10 - (3 * box_w + 2 * gap)) / 2
    for i, (label, color) in enumerate(steps):
        x = x0 + i * (box_w + gap)
        box = mpatches.FancyBboxPatch(
            (x, 1.05), box_w, 1.05, boxstyle="round,pad=0.04",
            linewidth=1.0, edgecolor="black", facecolor=color, alpha=0.45,
            hatch="//",
        )
        ax_schem.add_patch(box)
        ax_schem.text(x + box_w / 2, 1.575, label, ha="center", va="center", fontsize=7.8)
        if i < 2:
            ax_schem.annotate("", xy=(x + box_w + gap * 0.15, 1.575),
                               xytext=(x + box_w, 1.575),
                               arrowprops=dict(arrowstyle="->", color="black", linewidth=0.9))

    ax_schem.annotate(
        "", xy=(x0 + 3 * box_w + 2 * gap, 0.55), xytext=(x0, 0.55),
        arrowprops=dict(arrowstyle="<->", color="#444444", linewidth=0.8),
    )
    ax_schem.text(5.0, 0.30,
                  "occurs somewhere inside the measured D0→D1 gap above "
                  "(no SDA/SCL capture exists for this trial; sequence per "
                  "read_mlc_src(), latency_test_mlc.c:124–134, and AN5259 [2])",
                  ha="center", va="center", fontsize=7, style="italic", color="#333333")

    ax_schem.set_title("(b) I²C bank-switch read sequence (schematic)", fontsize=9.5, pad=8)

    fig.suptitle(
        "R1 pt.3: wire-level timing for one representative trial (D0/D1/D2 measured; "
        "I²C transaction structure schematic, not captured)",
        fontsize=9.5, y=0.995,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png_path = OUT_DIR / "figure_timing_diagram.png"
    svg_path = OUT_DIR / "figure_timing_diagram.svg"
    fig.savefig(png_path, dpi=300, bbox_inches="tight", pad_inches=0.15)
    fig.savefig(svg_path, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"[timing_diagram] Wrote {png_path} ({png_path.stat().st_size} bytes)")
    print(f"[timing_diagram] Wrote {svg_path} ({svg_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
