#!/usr/bin/env python3
"""
fp16_emulate.py

Faithful Python reimplementation of parity_core.c's pc_step, with a
toggle for FP16 emulation of intermediate filter arithmetic.

Purpose: test the hypothesis that the 40 motion-arm host-vs-silicon
disagreements (host=class0 with p2p in [0.031, 0.049], silicon=class4,
threshold 0.049316) are caused by float32 vs half-precision arithmetic
accumulating in the IIR1 high-pass filter over a 75-sample window.

This is NOT a re-implementation of silicon's actual computation.
AN5259 §1.2 states that filter coefficients are stored as
half-precision; it does NOT specify the precision of every
intermediate result. FP16 emulation here is an aggressive lower
bound on silicon's precision — it casts every filter intermediate
to float16. If FP16 emulation moves host's p2p_norm above 0.049316
on the 40 disagreement windows, that's EVIDENCE (not proof) that
the disagreement mechanism is precision-related.

Mirrors parity_core.c exactly:
  - decimation: sensor_sample_count is 1-based; sample i goes to MLC
    iff i % decim_ratio == 0. So decim=2 keeps sensor samples
    2, 4, 6, ... (even-numbered when 1-indexed).
  - filter step: y = b1*x + b2*x1 - a2*y1, then y * gain (parity_core
    convention A; tree.json's a2 is already sign-flipped from MEMS
    Studio's Convention B).
  - window: 75 MLC samples per window; window triggers on
    mlc_sample_count % win_len == 0 once win_filled >= win_len.
  - variance: parity_core uses double (float64) precision for the
    mean and sum-of-squares accumulators, regardless of filter
    precision. We replicate that — variance is NOT included in the
    FP16 emulation, only the filter is.
  - p2p: max - min of the window buffer (whatever precision the
    filter wrote to it).
  - t_window_end_s: the timestamp of the sensor sample that
    triggered the window decision (i.e., the 150th sensor sample
    for window 0 at decim=2, win=75).

Output schema (matches replay_parity for easy diffing):
  window_idx,t_window_end_s,var_norm,p2p_norm,class

Usage:
  fp16_emulate.py --accel-csv FILE --tree-json FILE \\
                  [--windows W1,W2,...|all] [--mode fp32|fp16] [--quiet]
"""

from __future__ import annotations
import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class TreeConfig:
    window_length: int
    sensor_odr_hz: int
    mlc_odr_hz: int
    decimation_ratio: int
    filter_b1: float
    filter_b2: float
    filter_a2: float
    filter_gain: float
    threshold: float
    threshold_comparison: str  # "lt" or "lte"

    @classmethod
    def load(cls, path: str) -> "TreeConfig":
        data = json.loads(Path(path).read_text())
        filt = data["filters"][0]
        assert filt["type"] == "iir1_hp", f"unexpected filter type: {filt['type']}"

        # Find the p2p threshold and comparison operator. The tree
        # splits on whichever feature_id corresponds to peak_to_peak.
        features_by_id = {f["id"]: f for f in data["features"]}
        p2p_id = next(
            fid for fid, f in features_by_id.items() if f["type"] == "peak_to_peak"
        )
        threshold = None
        comparison = None
        for node in data["tree"]:
            if node.get("is_leaf") or node.get("leaf"):
                continue
            if node["feature_id"] == p2p_id:
                threshold = float(node["threshold"])
                comparison = node["comparison"]
                break
        if threshold is None:
            raise ValueError("No p2p split found in tree")

        return cls(
            window_length=int(data["window_length"]),
            sensor_odr_hz=int(data["sensor_odr_hz"]),
            mlc_odr_hz=int(data["mlc_odr_hz"]),
            decimation_ratio=int(data["decimation_ratio"]),
            filter_b1=float(filt["b1"]),
            filter_b2=float(filt["b2"]),
            filter_a2=float(filt["a2"]),
            filter_gain=float(filt.get("gain", 1.0)),
            threshold=threshold,
            threshold_comparison=comparison,
        )


def load_accel_csv(path: str) -> tuple[list[float], list[tuple[float, float, float]]]:
    """Returns (timestamps, [(ax, ay, az), ...]) in g. Auto-detects
    units like replay_parity (first sample magnitude > 5 => mg).
    """
    timestamps: list[float] = []
    samples: list[tuple[float, float, float]] = []
    units_inferred = False
    units_are_mg = False
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                t = float(parts[0])
                ax = float(parts[1])
                ay = float(parts[2])
                az = float(parts[3])
            except ValueError:
                continue  # header row
            if not units_inferred:
                mag = math.sqrt(ax * ax + ay * ay + az * az)
                units_are_mg = mag > 5.0
                units_inferred = True
            if units_are_mg:
                ax *= 1e-3
                ay *= 1e-3
                az *= 1e-3
            timestamps.append(t)
            samples.append((ax, ay, az))
    return timestamps, samples


def fp(x: float, mode: str) -> float:
    """Cast through the configured float precision.
    fp32: matches parity_core's `float` type for filter math.
    fp16: aggressive emulation — every intermediate cast to float16.
    """
    if mode == "fp32":
        return float(np.float32(x))
    if mode == "fp16":
        return float(np.float16(x))
    raise ValueError(f"unknown mode: {mode}")


def compute_decisions(
    cfg: TreeConfig,
    timestamps: list[float],
    samples: list[tuple[float, float, float]],
    mode: str,
) -> list[tuple[int, float, float, float]]:
    """Replicate pc_step's behavior. Returns one tuple per window:
    (window_idx, t_window_end_s, var_norm, p2p_norm).

    Filter math is done in `mode` precision (fp32 baseline or fp16
    emulation). Variance reduction is done in float64 to match
    parity_core's `double` accumulators (lines 408-419 of
    parity_core.c).
    """
    decim = cfg.decimation_ratio
    win_len = cfg.window_length

    # Filter coefficients in `mode` precision.
    b1 = fp(cfg.filter_b1, mode)
    b2 = fp(cfg.filter_b2, mode)
    a2 = fp(cfg.filter_a2, mode)
    gain = fp(cfg.filter_gain, mode)

    # Filter state, init to zero (parity_core's default).
    x1 = fp(0.0, mode)
    y1 = fp(0.0, mode)

    # Window buffer of filtered samples.
    win_buf: list[float] = [fp(0.0, mode)] * win_len
    win_idx = 0
    win_filled = 0
    window_count = 0
    sensor_count = 0
    mlc_count = 0

    results: list[tuple[int, float, float, float]] = []

    for t, (ax, ay, az) in zip(timestamps, samples):
        # Matches parity_core: sensor_sample_count++ at top of pc_step.
        sensor_count += 1

        # Decimation: pc_step returns false if sensor_count % decim != 0.
        # (parity_core.c lines 8-12.) This means we KEEP samples where
        # sensor_count is a multiple of decim — sensor samples 2, 4, 6, ...
        # for decim=2. Sample 1 is dropped; sample 2 is the first MLC sample.
        if decim > 1 and (sensor_count % decim) != 0:
            continue
        mlc_count += 1

        # L2 norm. parity_core uses single-precision sqrtf on float32
        # arguments (line 492). We cast inputs through `mode` and
        # compute the norm in `mode` precision.
        ax_c = fp(ax, mode)
        ay_c = fp(ay, mode)
        az_c = fp(az, mode)
        sq_sum = fp(
            fp(ax_c * ax_c, mode) + fp(ay_c * ay_c, mode) + fp(az_c * az_c, mode),
            mode,
        )
        norm = fp(math.sqrt(sq_sum), mode)

        # IIR1 HP step: y = b1*x + b2*x1 - a2*y1, then y * gain.
        # parity_core.c lines 380-383. All intermediates in `mode`.
        term1 = fp(b1 * norm, mode)
        term2 = fp(b2 * x1, mode)
        term3 = fp(a2 * y1, mode)
        y_pre = fp(fp(term1 + term2, mode) - term3, mode)
        y = fp(y_pre * gain, mode)
        # State update (parity_core does x1 = x, y1 = y AFTER computing y).
        x1 = norm
        y1 = y
        filtered = y

        # Push into window. parity_core's win_push: write at win_idx,
        # then increment with wrap, then bump win_filled.
        win_buf[win_idx] = filtered
        win_idx = (win_idx + 1) % win_len
        if win_filled < win_len:
            win_filled += 1

        # Window-boundary trigger: parity_core lines 496-497.
        #   if win_filled < win_len: return false
        #   if mlc_count % win_len != 0: return false
        if win_filled < win_len:
            continue
        if mlc_count % win_len != 0:
            continue

        # Compute features. Variance uses double (float64) per
        # parity_core.c lines 408-419, regardless of filter precision.
        # p2p uses max-min on whatever's in the buffer.
        mean = 0.0
        for v in win_buf:
            mean += float(v)
        mean /= float(win_len)
        ss = 0.0
        for v in win_buf:
            d = float(v) - mean
            ss += d * d
        # tree.json estimator is "biased" => denom = win_len.
        var_norm = float(np.float32(ss / float(win_len)))  # final cast to float

        mn = win_buf[0]
        mx = win_buf[0]
        for v in win_buf[1:]:
            if v < mn:
                mn = v
            if v > mx:
                mx = v
        p2p_norm = float(np.float32(mx - mn))  # final cast to float

        # t_window_end_s: the timestamp of the sensor sample that
        # triggered this window decision — i.e., the current `t`.
        results.append((window_count, t, var_norm, p2p_norm))
        window_count += 1

    return results


def classify(p2p_norm: float, cfg: TreeConfig) -> int:
    """Apply the tree's threshold comparison. For session 4's tree
    (depth-1, single p2p split): if p2p satisfies the "left" branch
    condition, class=0 (still); else class=4 (motion).
    """
    if cfg.threshold_comparison == "lte":
        go_left = p2p_norm <= cfg.threshold
    elif cfg.threshold_comparison == "lt":
        go_left = p2p_norm < cfg.threshold
    else:
        raise ValueError(f"unsupported comparison: {cfg.threshold_comparison}")
    return 0 if go_left else 4


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--accel-csv", required=True)
    ap.add_argument("--tree-json", required=True)
    ap.add_argument("--windows", default="all",
                    help="comma-separated window indices, or 'all'")
    ap.add_argument("--mode", choices=["fp32", "fp16"], default="fp32")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cfg = TreeConfig.load(args.tree_json)
    if not args.quiet:
        print(f"# config: win={cfg.window_length} sensor={cfg.sensor_odr_hz}Hz "
              f"mlc={cfg.mlc_odr_hz}Hz decim={cfg.decimation_ratio} "
              f"threshold={cfg.threshold} cmp={cfg.threshold_comparison} "
              f"mode={args.mode}",
              file=sys.stderr)
        print(f"# filter: b1={cfg.filter_b1} b2={cfg.filter_b2} a2={cfg.filter_a2}",
              file=sys.stderr)

    timestamps, samples = load_accel_csv(args.accel_csv)
    if not args.quiet:
        print(f"# loaded {len(samples)} samples from {args.accel_csv}", file=sys.stderr)

    decisions = compute_decisions(cfg, timestamps, samples, args.mode)
    if not args.quiet:
        print(f"# computed {len(decisions)} window decisions", file=sys.stderr)

    if args.windows == "all":
        wanted = None  # emit every row
    else:
        wanted = set(int(w) for w in args.windows.split(","))

    print("window_idx,t_window_end_s,var_norm,p2p_norm,class")
    for wi, t, var_norm, p2p_norm in decisions:
        if wanted is not None and wi not in wanted:
            continue
        cls = classify(p2p_norm, cfg)
        print(f"{wi},{t:.6f},{var_norm:.6e},{p2p_norm:.6e},{cls}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
