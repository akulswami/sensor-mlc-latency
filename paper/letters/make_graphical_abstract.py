#!/usr/bin/env python3
"""Graphical abstract for IEEE Sensors Letters: host vs MLC latency, idle + contention."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

conditions = ["Idle", "I\u00b2C contention"]
host = [321.7, 574.5]
mlc  = [681.5, 1325.4]
speedup = ["2.1\u00d7", "2.3\u00d7"]

x = np.arange(len(conditions)); w = 0.34
fig, ax = plt.subplots(figsize=(6.5, 3.6), dpi=300)
b1 = ax.bar(x - w/2, host, w, label="Host inference", color="#2c7fb8", edgecolor="black", linewidth=0.6)
b2 = ax.bar(x + w/2, mlc,  w, label="On-sensor MLC", color="#d95f0e", edgecolor="black", linewidth=0.6)
for bars in (b1, b2):
    for r in bars:
        h = r.get_height()
        ax.annotate(f"{h:.1f}", xy=(r.get_x()+r.get_width()/2, h), xytext=(0,3),
                    textcoords="offset points", ha="center", va="bottom", fontsize=8.5)
ymax = max(mlc) * 1.18
for i, s in enumerate(speedup):
    pair_top = max(host[i], mlc[i])
    ax.annotate(f"host {s} faster", xy=(x[i], pair_top), xytext=(x[i], pair_top + ymax*0.06),
                ha="center", va="bottom", fontsize=9, fontweight="bold", color="#1a1a1a")
ax.set_ylabel("Median interrupt-to-decision\nlatency (\u00b5s)", fontsize=10)
ax.set_xticks(x); ax.set_xticklabels(conditions, fontsize=10); ax.set_ylim(0, ymax)
ax.legend(frameon=False, fontsize=9.5, loc="upper left")
ax.set_title("Host inference is 2.1\u20132.3\u00d7 faster than the on-sensor MLC;\n"
             "the I\u00b2C bank-switch read protocol, not classification, dominates",
             fontsize=10, fontweight="bold", pad=10)
ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
ax.tick_params(axis="both", labelsize=9)
fig.tight_layout()
fig.savefig("../figures/graphical_abstract.png", dpi=300, bbox_inches="tight", facecolor="white")
print("Wrote ../figures/graphical_abstract.png")
