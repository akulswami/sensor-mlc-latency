#!/usr/bin/env python3
"""
demo_replay.py — animate a combined capture (probe CSV + servo log)
at 1x wall-clock speed.

Reads /tmp/demo_files/demo_capture.csv (from mlc_poll_probe_v3) and
/tmp/demo_files/demo_servo.log (from servo_sweep) and shows three
stacked panels:
  1. Accelerometer Z (g)
  2. MLC decision over time (color-banded)
  3. Servo phase over time (color-banded)

A vertical cursor advances at real time. The "MLC tracks servo motion"
story is the takeaway.

Usage:
  python3 demo_replay.py
  python3 demo_replay.py --capture /tmp/demo_files/demo_capture.csv \\
                         --servo   /tmp/demo_files/demo_servo.log
  python3 demo_replay.py --save demo.mp4    # save instead of show

Notes on what the capture contains:
  - mlc_poll_probe_v3 polls at ~500 Hz, over-sampling 208 Hz accel.
    Same accel sample appears 2-3x in consecutive rows.
  - elapsed_ms is monotonic clock from probe start.
  - The probe was started ~2 sec after the servo. We re-base the
    servo log's microsecond timestamps to a probe-relative axis so
    both panels share a time origin.
  - The first ~1 sec of the capture often shows an MLC startup
    transient (the IIR filter has not yet converged from zero
    initial conditions). Visualization includes it without comment
    so you can see the chip warm up.
"""

import argparse
import csv
import sys
from pathlib import Path

import matplotlib
import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np


def load_capture(path):
    """Return arrays (t_s, mlc_src, az_g) for plotting."""
    ts, mlc, az = [], [], []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts.append(int(row["elapsed_ms"]) / 1000.0)
            mlc.append(int(row["mlc_src"], 16))
            az.append(float(row["az_g"]))
    return np.array(ts), np.array(mlc), np.array(az)


def load_servo(path):
    """Return list of (phase, start_t_s, end_t_s) tuples on the SERVO clock
    (microseconds from first START event)."""
    events = []  # (us, event_name)
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split(",")
            if len(parts) != 3:
                continue
            us, name, _ticks = parts
            events.append((int(us), name))

    if not events:
        return []

    t0_us = events[0][0]
    phases = []
    # Walk events; identify phase boundaries
    current_phase = None
    phase_start = 0.0
    for us, name in events:
        rel_s = (us - t0_us) / 1e6
        if name == "MOTION_PHASE_START":
            if current_phase is not None:
                phases.append((current_phase, phase_start, rel_s))
            current_phase = "motion"
            phase_start = rel_s
        elif name == "STILL_PHASE_START":
            if current_phase is not None:
                phases.append((current_phase, phase_start, rel_s))
            current_phase = "still"
            phase_start = rel_s
        elif name == "END":
            if current_phase is not None:
                phases.append((current_phase, phase_start, rel_s))
            current_phase = None
    return phases


def align_servo_to_probe(phases, probe_lag_s):
    """The probe started probe_lag_s seconds AFTER the servo's first START
    event. Subtract probe_lag_s from every phase time so phases live on
    the probe clock. Phases that end before t=0 are dropped; phases that
    span t=0 are clipped."""
    out = []
    for name, t_start, t_end in phases:
        s = t_start - probe_lag_s
        e = t_end - probe_lag_s
        if e <= 0:
            continue
        if s < 0:
            s = 0.0
        out.append((name, s, e))
    return out


def estimate_probe_lag(capture_t, servo_phases):
    """We don't know the exact probe-vs-servo lag from the data alone.
    The 'sleep 2' in the launcher implies ~2 sec. Return 2.0 unless
    overridden by --lag."""
    return 2.0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--capture", default="/tmp/demo_files/demo_capture.csv")
    ap.add_argument("--servo",   default="/tmp/demo_files/demo_servo.log")
    ap.add_argument("--lag", type=float, default=None,
                    help="seconds the probe was started AFTER the servo "
                         "(default: 2.0, matches launcher's sleep 2)")
    ap.add_argument("--save", default=None,
                    help="if given, save animation to this MP4 file "
                         "instead of showing interactively")
    ap.add_argument("--fps", type=int, default=20,
                    help="animation frame rate (default 20)")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="playback speed multiplier (default 1.0 = real time)")
    args = ap.parse_args()

    cap_path = Path(args.capture)
    servo_path = Path(args.servo)
    if not cap_path.exists():
        print(f"ERROR: {cap_path} not found", file=sys.stderr)
        return 1
    if not servo_path.exists():
        print(f"ERROR: {servo_path} not found", file=sys.stderr)
        return 1

    print(f"Loading {cap_path}...")
    t_s, mlc, az = load_capture(cap_path)
    print(f"  {len(t_s)} samples spanning {t_s[-1]:.1f} sec")

    print(f"Loading {servo_path}...")
    servo_phases_raw = load_servo(servo_path)
    print(f"  {len(servo_phases_raw)} phases")

    lag = args.lag if args.lag is not None else estimate_probe_lag(t_s, servo_phases_raw)
    print(f"  probe-vs-servo lag: {lag:.2f} sec")
    servo_phases = align_servo_to_probe(servo_phases_raw, lag)

    # Plot setup
    fig, axes = plt.subplots(3, 1, figsize=(12, 7), sharex=True,
                             gridspec_kw={"height_ratios": [2, 1, 1]})
    ax_acc, ax_mlc, ax_srv = axes

    # Panel 1: az
    ax_acc.plot(t_s, az, lw=0.6, color="#2b6cb0")
    ax_acc.set_ylabel("A_z (g)")
    ax_acc.set_title("LSM6DSOX MLC live classification — playback at 1× speed")
    ax_acc.grid(True, alpha=0.3)
    # Tight y limits with margin around the actual data
    az_min, az_max = float(np.min(az)), float(np.max(az))
    az_pad = max(0.05, 0.1 * (az_max - az_min))
    ax_acc.set_ylim(az_min - az_pad, az_max + az_pad)

    # Panel 2: MLC decision strip
    # Render as colored horizontal bars: red where mlc=motion, grey where still
    ax_mlc.set_ylabel("MLC")
    ax_mlc.set_yticks([])
    ax_mlc.set_ylim(0, 1)
    # Find runs of constant mlc_src
    if len(mlc) > 0:
        change_idx = np.flatnonzero(np.diff(mlc)) + 1
        run_starts = np.concatenate(([0], change_idx))
        run_ends = np.concatenate((change_idx, [len(mlc)]))
        for s, e in zip(run_starts, run_ends):
            val = mlc[s]
            color = "#e53e3e" if val != 0 else "#cbd5e0"
            ax_mlc.axvspan(t_s[s], t_s[e-1], color=color, alpha=0.8)
    ax_mlc.text(0.01, 0.5, "still", color="#4a5568", transform=ax_mlc.transAxes,
                va="center", ha="left", fontsize=9)
    ax_mlc.text(0.99, 0.5, "motion = red", color="#e53e3e",
                transform=ax_mlc.transAxes, va="center", ha="right", fontsize=9)

    # Panel 3: servo phase strip
    ax_srv.set_ylabel("Servo")
    ax_srv.set_yticks([])
    ax_srv.set_ylim(0, 1)
    ax_srv.set_xlabel("Probe-relative time (s)")
    for phase, ps, pe in servo_phases:
        color = "#e53e3e" if phase == "motion" else "#cbd5e0"
        ax_srv.axvspan(ps, pe, color=color, alpha=0.8)
    ax_srv.text(0.01, 0.5, "still", color="#4a5568", transform=ax_srv.transAxes,
                va="center", ha="left", fontsize=9)
    ax_srv.text(0.99, 0.5, "motion = red", color="#e53e3e",
                transform=ax_srv.transAxes, va="center", ha="right", fontsize=9)

    # Vertical "now" cursor on all three panels
    cursors = [ax.axvline(t_s[0], color="black", lw=1.5, alpha=0.7)
               for ax in axes]

    # Time-readout textbox
    time_text = ax_acc.text(0.02, 0.95, "", transform=ax_acc.transAxes,
                            fontsize=10, va="top", family="monospace",
                            bbox=dict(boxstyle="round,pad=0.3",
                                      facecolor="white", alpha=0.7))

    fig.tight_layout()

    total_sec = float(t_s[-1])
    frames = int(total_sec * args.fps / args.speed)

    def update(frame):
        # Wall-clock time corresponds to playback time.
        t_now = (frame / args.fps) * args.speed
        if t_now > total_sec:
            t_now = total_sec
        for c in cursors:
            c.set_xdata([t_now, t_now])

        # Read the current MLC and servo state for the readout
        # Find nearest capture sample
        i = int(np.searchsorted(t_s, t_now))
        i = max(0, min(i, len(t_s) - 1))
        mlc_now = mlc[i]
        servo_now = "—"
        for phase, ps, pe in servo_phases:
            if ps <= t_now < pe:
                servo_now = phase
                break
        time_text.set_text(
            f"t = {t_now:5.2f} s\n"
            f"MLC   : {'motion' if mlc_now != 0 else 'still '}  (0x{mlc_now:02X})\n"
            f"servo : {servo_now}"
        )
        return cursors + [time_text]

    interval_ms = 1000 / args.fps
    anim = animation.FuncAnimation(fig, update, frames=frames,
                                   interval=interval_ms, blit=True,
                                   repeat=False)

    if args.save:
        print(f"Saving to {args.save} (this can take a minute)...")
        # ffmpeg writer for MP4; falls back to default if not available
        try:
            writer = animation.FFMpegWriter(fps=args.fps, bitrate=2400)
            anim.save(args.save, writer=writer)
        except Exception as e:
            print(f"FFMpeg save failed ({e}), trying PillowWriter for GIF...")
            from matplotlib.animation import PillowWriter
            gif_path = args.save.rsplit(".", 1)[0] + ".gif"
            anim.save(gif_path, writer=PillowWriter(fps=args.fps))
            print(f"Saved as {gif_path} instead")
    else:
        plt.show()

    return 0


if __name__ == "__main__":
    sys.exit(main())
