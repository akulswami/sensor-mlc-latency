#!/usr/bin/env python3
"""
fig_wire_timing.py — Render the wire-level timing figure (INT1, SDA, SCL, D1)
for one decision window of a captured block (manuscript SENSL-26-06-RL-0906,
Reviewer 1 Point 3).

Reads a block's Saleae digital CSV export (50 MS/s; channels 0=INT1, 1=decision
GPIO, 2=servo PWM, 3=SDA, 4=SCL), verifies the three-transaction bank-switch
triple in the chosen window via i2c_window_decode.py, and annotates the figure
with the measured decomposition (sched / bus triple / strobe / D0->D1).

Usage:
  python3 fig_wire_timing.py <block_dir> [--window-t SECONDS] [--out prefix]

  <block_dir>   directory containing digital.csv (e.g. data/block-b005-mlc-idle)
  --window-t    pick the first INT1 window after this time in seconds (default 20)
  --out         output prefix (default fig_wire_timing); writes .png and .pdf

Requires: matplotlib. i2c_window_decode.py must be in the same directory.
Figure used in the revision-1 response: block b005 window at t=22.906 s
(D0->D1 = 468 us, MLC0_SRC=0x04). Raw capture archived at
Zenodo DOI 10.5281/zenodo.22950121.
"""
import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i2c_window_decode as iwd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("block_dir")
    ap.add_argument("--window-t", type=float, default=20.0)
    ap.add_argument("--out", default="fig_wire_timing")
    args = ap.parse_args()

    rows = iwd.load_csv(os.path.join(args.block_dir, "digital.csv"))
    wins = iwd.build_windows(rows)
    cand = [w for w in wins if w[2] > args.window_t]
    if not cand:
        sys.exit(f"no INT1 window after t={args.window_t}s")
    lo, hi, d0 = cand[0]
    wr = [r for r in rows if lo <= r[0] <= hi]
    v = iwd.verify_window(wr, d0)
    if not v["triple_ok"]:
        sys.exit(f"window at t={d0:.3f}s failed verification: {v}")
    frames_w = iwd.decode_i2c(wr)
    trip = [f for f in frames_w if f["addr"] == iwd.SENSOR_ADDR]
    if len(trip) != 4:
        sys.exit(f"expected 4 wire frames (T1, T2 ptr, T2 read, T3), got {len(trip)}")

    t_sched, t_trip_end, t_d1 = v["sched_ms"], v["sched_ms"] + v["triple_ms"], v["d0_d1_ms"]
    span = [r for r in rows if d0 - 0.00005 <= r[0] <= d0 + 0.00056]

    fig, axes = plt.subplots(4, 1, figsize=(7.16, 3.4), sharex=True,
                             gridspec_kw=dict(hspace=0.55, left=0.115, right=0.985,
                                              top=0.86, bottom=0.13))
    lanes = [(0, "INT1\n(D0)"), (3, "SDA"), (4, "SCL"), (1, "D1\nstrobe")]
    ylims = [(-0.7, 3.1), (-0.7, 1.7), (-0.7, 2.9), (-1.15, 1.7)]
    for ax, (ch, name), yl in zip(axes, lanes, ylims):
        t = [(r[0] - d0) * 1e3 for r in span]
        y = [r[1 + ch] for r in span]
        ax.step(t, y, where="post", color="black", lw=1.1)
        ax.set_ylim(*yl); ax.set_yticks([0, 1]); ax.set_yticklabels(["0", "1"], fontsize=7)
        ax.set_ylabel(name, fontsize=8, rotation=0, ha="right", va="center", labelpad=6)
        for s in ("top", "right", "left"): ax.spines[s].set_visible(False)
        ax.tick_params(axis="x", labelsize=7.5)

    for x in (0, t_sched, t_trip_end, t_d1):
        for ax in axes:
            ax.axvline(x, color="0.6", lw=0.6, ls=(0, (3, 2)), zorder=0)

    for (x0, x1, lab) in [(0, t_sched, f"sched {v['sched_ms']*1e3:.0f} µs"),
                          (t_sched, t_trip_end, f"bus triple {v['triple_ms']*1e3:.0f} µs"),
                          (t_trip_end, t_d1, f"strobe {v['strobe_ms']*1e3:.0f} µs")]:
        axes[0].axvspan(x0, x1, color="0.90", zorder=0)
        axes[0].text((x0 + x1) / 2, 2.15, lab, ha="center", va="center", fontsize=7.2)
    axes[0].text(0.553, 0.5, "9.01 ms pulse\n(shown in part)", ha="right", va="center",
                 fontsize=6.4, style="italic")

    fT1, fT2a, fT2b, fT3 = trip
    src = v["mlc0_src"]
    cls = {"0x04": "motion", "0x00": "still"}.get(src, src)
    t2c = ((fT2a["start_t"] + (fT2b["stop_t"] or fT2b["start_t"])) / 2 - d0) * 1e3
    for xc, lab in [(((fT1["start_t"] + fT1["stop_t"]) / 2 - d0) * 1e3, "T1: W[01,80]\nbank ON"),
                    (t2c, f"T2: W[70]+Sr → R\nMLC0_SRC = {src} ({cls})"),
                    (((fT3["start_t"] + fT3["stop_t"]) / 2 - d0) * 1e3, "T3: W[01,00]\nbank OFF")]:
        axes[2].text(xc, 1.95, lab, ha="center", va="center", fontsize=6.8,
                     bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="0.55", lw=0.5))

    axes[3].annotate("", xy=(t_d1, -0.85), xytext=(0, -0.85),
                     arrowprops=dict(arrowstyle="<->", color="black", lw=0.9))
    axes[3].text(t_d1 / 2, -1.05, f"D0→D1 = {v['d0_d1_ms']*1e3:.0f} µs",
                 ha="center", va="top", fontsize=7.6)

    block = os.path.basename(os.path.normpath(args.block_dir))
    fig.suptitle(f"Wire-level decision window — {block}: INT1, I²C triple, decision strobe",
                 fontsize=8.8, x=0.115, ha="left", y=0.965)
    axes[-1].set_xlabel("time relative to INT1 rising edge (ms)", fontsize=8)
    axes[-1].set_xlim(-0.03, 0.56)
    fig.align_ylabels(axes)
    fig.savefig(args.out + ".png", dpi=300)
    fig.savefig(args.out + ".pdf")
    print(f"window t={d0:.3f}s  {v}  ->  {args.out}.png/.pdf")


if __name__ == "__main__":
    main()
