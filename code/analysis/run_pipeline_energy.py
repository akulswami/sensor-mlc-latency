#!/usr/bin/env python3
"""run_pipeline_energy.py
========================

POST-HOC analysis, added in response to IEEE Sensors Letters review of
SENSL-26-06-RL-0906 (Reviewer 1, point 5; Reviewer 2, energy comment).
This is NOT part of the original pre-registration (v7.5/v7.6) — it
re-slices data already collected for H6'/jc_eff/throttling checks along
an axis (pipeline) that the original H6' script never used.

What this answers that run_h6_energy.py does not:
  run_h6_energy.py pools VDD_IN across ALL pipelines and asks:
      "does system power rise under synthetic CPU stress?"
  This script groups by (pipeline, condition) and asks:
      "does the host pipeline draw more Jetson-side compute power
       than the MLC pipeline, under matched condition?"
  That second question is what the reviewers actually asked for.

Why VDD_CPU_GPU_CV instead of VDD_IN:
  tegrastats.log already contains three rails per line: VDD_IN (total
  module input power), VDD_CPU_GPU_CV (combined CPU+GPU compute rail),
  and VDD_SOC. VDD_IN includes background system draw (memory, I/O,
  idle peripherals) that is common to both pipelines and dilutes the
  comparison. VDD_CPU_GPU_CV isolates the compute rail that the host
  pipeline's on-CPU classifier actually runs on. host_pipeline.c has no
  CUDA/TensorRT/GPU calls, and GR3D_FREQ sits at 0% across the sampled
  tegrastats lines, so on this workload VDD_CPU_GPU_CV is effectively a
  CPU-power measurement, not GPU-contaminated.

IMPORTANT SCOPE LIMIT — read before citing this in the response letter:
  VDD_CPU_GPU_CV covers the Jetson module's own compute rail only. It
  does NOT include the LSM6DSOX's on-sensor MLC engine current, which
  lives entirely on the sensor's own supply (external to this rail).
  For the mlc/mlc-binary pipelines, this script tells you the Jetson
  SIDE cost of running the polling/orchestration loop — not the
  sensor-side MLC classification cost. The sensor-side number requires
  the separate PPK2 current-sense measurement. Report these as two
  halves of one comparison, not as a substitute for each other.

Usage:
    python3 code/analysis/run_pipeline_energy.py
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import statistics as stat_module

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BLOCKS_DIR = REPO_ROOT / "data" / "training" / "latency-experiment"
CAMPAIGN_ID = "confirmatory-2026-05-26"
OUT_DIR = REPO_ROOT / "data" / "processed" / CAMPAIGN_ID
SUBSAMPLE_FACTOR = 10  # same autocorrelation correction as run_h6_energy.py (500ms samples)
ALPHA = 0.05
BOOTSTRAP_N = 10_000

RAIL_RE = {
    "VDD_IN": re.compile(r"VDD_IN\s+(\d+)mW/\d+mW"),
    "VDD_CPU_GPU_CV": re.compile(r"VDD_CPU_GPU_CV\s+(\d+)mW/\d+mW"),
    "VDD_SOC": re.compile(r"VDD_SOC\s+(\d+)mW/\d+mW"),
}

PIPELINES = ["host", "mlc", "mlc-binary"]


def parse_tegrastats_multirail(path):
    """Return dict rail_name -> list of instantaneous mW samples."""
    out = {k: [] for k in RAIL_RE}
    with open(path) as f:
        for line in f:
            for rail, pat in RAIL_RE.items():
                m = pat.search(line)
                if m:
                    out[rail].append(int(m.group(1)))
    return out


def load_by_pipeline_condition():
    """Return {(pipeline, condition): {rail: [samples...]}} pooled across blocks,
    restricted to the confirmatory campaign (same scope run_h6_energy.py uses)."""
    grouped = defaultdict(lambda: defaultdict(list))
    block_count = defaultdict(int)
    skipped_no_tegra = 0
    for bdir in sorted(BLOCKS_DIR.glob(f"block-{CAMPAIGN_ID}-b*")):
        meta_path = bdir / "block_metadata.json"
        tegra_path = bdir / "tegrastats.log"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        if not meta.get("included", True):
            continue  # respect the same exclusion flag the latency analysis uses
        if not tegra_path.exists():
            skipped_no_tegra += 1
            continue
        pipeline = meta.get("pipeline")
        condition = meta.get("condition")
        if pipeline not in PIPELINES or condition is None:
            continue
        rails = parse_tegrastats_multirail(tegra_path)
        key = (pipeline, condition)
        for rail, samples in rails.items():
            grouped[key][rail].extend(samples)
        block_count[key] += 1
    return grouped, block_count, skipped_no_tegra


def subsample(samples, factor, seed=42):
    samples = np.asarray(samples, dtype=float)
    if len(samples) <= factor:
        return samples
    rng = np.random.default_rng(seed=seed)
    offset = rng.integers(0, factor)
    return samples[offset::factor]


def compare(a_label, a_samples, b_label, b_samples, rail):
    a = np.asarray(a_samples, dtype=float)
    b = np.asarray(b_samples, dtype=float)
    a_sub = subsample(a, SUBSAMPLE_FACTOR, seed=42)
    b_sub = subsample(b, SUBSAMPLE_FACTOR, seed=43)
    mwu = stat_module.mann_whitney_u(a_sub, b_sub, alternative="two-sided")

    rng = np.random.default_rng(seed=44)
    n_a, n_b = len(a), len(b)
    diffs = np.empty(BOOTSTRAP_N)
    for i in range(BOOTSTRAP_N):
        a_b = a[rng.integers(0, n_a, size=n_a)]
        b_b = b[rng.integers(0, n_b, size=n_b)]
        diffs[i] = a_b.mean() - b_b.mean()
    diff_point = float(a.mean() - b.mean())
    ci_low, ci_high = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))

    print(f"  [{rail}] {a_label} (n={n_a}, mean={a.mean():.1f} mW) vs "
          f"{b_label} (n={n_b}, mean={b.mean():.1f} mW)")
    print(f"    diff = {diff_point:+.1f} mW  (95% CI [{ci_low:+.1f}, {ci_high:+.1f}])"
          f"   MWU p (subsampled, two-sided) = {mwu.p_value:.4e}")
    return {
        "rail": rail,
        "a_label": a_label, "a_n": n_a, "a_mean_mw": float(a.mean()),
        "b_label": b_label, "b_n": n_b, "b_mean_mw": float(b.mean()),
        "diff_mw": diff_point, "diff_ci_95pct_mw": [ci_low, ci_high],
        "mwu_p_value_subsampled": float(mwu.p_value),
    }


def main():
    print("[pipeline_energy] Loading tegrastats samples grouped by (pipeline, condition)...")
    grouped, block_count, skipped = load_by_pipeline_condition()
    if skipped:
        print(f"[pipeline_energy] NOTE: {skipped} included blocks had no tegrastats.log, skipped.")
    print()

    conditions = sorted({cond for (_, cond) in grouped})
    print(f"[pipeline_energy] Conditions present: {conditions}")
    for (pipeline, condition), rails in sorted(grouped.items()):
        n = len(rails.get("VDD_CPU_GPU_CV", []))
        print(f"  pipeline={pipeline:12s} condition={condition:15s} "
              f"blocks={block_count[(pipeline, condition)]:3d}  VDD_CPU_GPU_CV samples={n}")
    print()

    results = []
    for condition in conditions:
        print(f"=== condition: {condition} ===")
        for rail in ("VDD_CPU_GPU_CV", "VDD_IN"):
            host = grouped.get(("host", condition), {}).get(rail, [])
            mlc = grouped.get(("mlc", condition), {}).get(rail, [])
            mlcb = grouped.get(("mlc-binary", condition), {}).get(rail, [])
            if host and mlc:
                results.append({"condition": condition,
                                 **compare(f"host/{condition}", host, f"mlc/{condition}", mlc, rail)})
            else:
                print(f"  [{rail}] skipping host vs mlc: missing data "
                      f"(host n={len(host)}, mlc n={len(mlc)})")
            if host and mlcb:
                results.append({"condition": condition,
                                 **compare(f"host/{condition}", host, f"mlc-binary/{condition}", mlcb, rail)})
        print()

    summary = {
        "generated_at": datetime.now().isoformat(),
        "note": ("POST-HOC analysis added in response to review. Not part of pre-reg "
                 "v7.5/v7.6. VDD_CPU_GPU_CV isolates Jetson-side compute power; it "
                 "excludes the LSM6DSOX's on-sensor MLC engine current, which is "
                 "measured separately via PPK2."),
        "campaign_id": CAMPAIGN_ID,
        "subsample_factor": SUBSAMPLE_FACTOR,
        "n_bootstrap_resamples": BOOTSTRAP_N,
        "comparisons": results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "pipeline_energy_results.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[pipeline_energy] Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
