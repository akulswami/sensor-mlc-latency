#!/usr/bin/env python3
"""
demo_live_plot.py — live plot of CSV streamed from mlc_poll_probe_v3.

Reads CSV lines from stdin (or --file PATH for testing) and updates a
3-panel matplotlib plot in real time:
  1. Accelerometer Z (g) — last N seconds
  2. MLC decision state — rolling color strip
  3. (Optional) Servo phase, if a separate servo-log path is given via
     --servo-log; that needs the file to be appended to live.

Usage on Asus, connected to running Jetson capture:

  ssh akulswami-jetson 'sudo /path/to/servo_sweep ... & \\
                        sudo /path/to/mlc_poll_probe3_motion --stdout ...' \\
    | python3 demo_live_plot.py

Data format expected on stdin (one row per poll, ~500 Hz):
  elapsed_ms,mlc_src,ax_g,ay_g,az_g
The first line is a header; subsequent lines are data. The reader is
forgiving — non-CSV lines (e.g. stray stderr that leaked into stdout)
are skipped silently.

The plot shows a rolling window (default 15 seconds) so older data
scrolls off the left. This keeps it responsive even if the capture
runs for minutes.

Ctrl+C in the terminal kills the plot AND, if connected via ssh-pipe,
SIGPIPE'ed the remote processes — they exit cleanly. (Confirmed via
servo_sweep + probe_v3 both having SIGINT handlers.)
"""

import argparse
import csv
import io
import sys
import threading
import time
from collections import deque

import matplotlib
import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np


# Rolling buffer of recent samples. Updated by the reader thread; read
# by the matplotlib animation. Lock isn't strictly necessary because
# deque append is atomic in CPython, but explicit is safer.
BUFFER_MAXLEN = 20000  # ~40 sec at 500 Hz worst case
_buffer_lock = threading.Lock()
buf_t  = deque(maxlen=BUFFER_MAXLEN)
buf_mlc = deque(maxlen=BUFFER_MAXLEN)
buf_az = deque(maxlen=BUFFER_MAXLEN)
_stop = threading.Event()


def reader_thread(stream):
    """Read CSV from stream and append to the deques.
    Skips blank lines and non-numeric rows defensively."""
    # Skip header
    first = stream.readline()
    if not first:
        return
    if first.strip() and "elapsed_ms" not in first:
        # Maybe no header (e.g. testing with a stripped file); back up by
        # parsing this line below.
        lines = [first]
    else:
        lines = []
    while not _stop.is_set():
        line = stream.readline()
        if not line:
            # EOF
            break
        lines.append(line)
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            parts = ln.split(",")
            if len(parts) != 5:
                continue
            try:
                t_ms = int(parts[0])
                mlc = int(parts[1], 16)
                az  = float(parts[4])
            except ValueError:
                continue
            with _buffer_lock:
                buf_t.append(t_ms / 1000.0)
                buf_mlc.append(mlc)
                buf_az.append(az)
        lines = []


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=None,
                    help="read from FILE instead of stdin (for offline testing)")
    ap.add_argument("--window", type=float, default=15.0,
                    help="seconds of recent data to keep on screen")
    ap.add_argument("--fps", type=int, default=15,
                    help="plot refresh rate")
    args = ap.parse_args()

    if args.file:
        stream = open(args.file)
    else:
        # Wrap stdin to line-buffer; without this, matplotlib's main loop
        # can starve the reader.
        stream = sys.stdin

    rt = threading.Thread(target=reader_thread, args=(stream,), daemon=True)
    rt.start()

    # Plot setup
    fig, axes = plt.subplots(2, 1, figsize=(12, 5), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})
    ax_acc, ax_mlc = axes
    fig.suptitle("LSM6DSOX MLC live classification — real time",
                 fontsize=11)

    line_az, = ax_acc.plot([], [], lw=0.7, color="#2b6cb0")
    ax_acc.set_ylabel("A_z (g)")
    ax_acc.grid(True, alpha=0.3)
    ax_acc.set_ylim(-1.15, -0.7)

    ax_mlc.set_ylabel("MLC")
    ax_mlc.set_yticks([])
    ax_mlc.set_ylim(0, 1)
    ax_mlc.set_xlabel("Time (s)")
    ax_mlc.text(0.005, 0.5, "still", color="#4a5568",
                transform=ax_mlc.transAxes, va="center", ha="left", fontsize=9)
    ax_mlc.text(0.995, 0.5, "motion = red", color="#e53e3e",
                transform=ax_mlc.transAxes, va="center", ha="right", fontsize=9)

    readout = fig.text(0.99, 0.96, "", ha="right", va="top",
                       fontsize=10, family="monospace",
                       bbox=dict(boxstyle="round,pad=0.3",
                                 facecolor="white", alpha=0.7))

    # We re-draw the MLC strip as axvspan rectangles each frame. The
    # rectangles persist across frames, so we keep a list and clear it
    # on every redraw.
    mlc_patches = []

    def update(frame):
        with _buffer_lock:
            if not buf_t:
                return [line_az, readout]
            t = np.fromiter(buf_t, dtype=float)
            mlc = np.fromiter(buf_mlc, dtype=int)
            az = np.fromiter(buf_az, dtype=float)

        t_now = t[-1]
        t_min = max(0.0, t_now - args.window)

        # Slice to window
        keep = t >= t_min
        t_w = t[keep]
        mlc_w = mlc[keep]
        az_w = az[keep]

        # Accel
        line_az.set_data(t_w, az_w)
        ax_acc.set_xlim(t_min, t_now + 0.5)

        # MLC strip: clear old patches, redraw runs
        for p in mlc_patches:
            p.remove()
        mlc_patches.clear()
        if len(mlc_w) > 0:
            change_idx = np.flatnonzero(np.diff(mlc_w)) + 1
            run_starts = np.concatenate(([0], change_idx))
            run_ends = np.concatenate((change_idx, [len(mlc_w)]))
            for s, e in zip(run_starts, run_ends):
                val = mlc_w[s]
                color = "#e53e3e" if val != 0 else "#cbd5e0"
                p = ax_mlc.axvspan(t_w[s], t_w[e-1], color=color, alpha=0.8)
                mlc_patches.append(p)

        # Readout
        last_mlc = int(mlc[-1])
        readout.set_text(
            f"t = {t_now:6.2f} s\n"
            f"MLC: {'motion' if last_mlc != 0 else 'still'} (0x{last_mlc:02X})"
        )

        return [line_az, readout] + mlc_patches

    interval_ms = 1000 // args.fps
    # blit=False because we resize axes each frame
    anim = animation.FuncAnimation(fig, update, interval=interval_ms,
                                   blit=False, cache_frame_data=False)

    try:
        plt.show()
    finally:
        _stop.set()


if __name__ == "__main__":
    sys.exit(main())
