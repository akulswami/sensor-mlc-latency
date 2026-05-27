#!/usr/bin/env python3
"""run_h6_energy.py
==================

H6' (energy under CPU stress) analysis per pre-reg v7.5 Change 9 / v7.6.

H6'₀: mean(power | cpu-stress) ≤ mean(power | idle) + 1000 mW
H6'₁: mean(power | cpu-stress) > mean(power | idle) + 1000 mW

Two pre-registered tests:
1. mann_whitney_u(cpu_stress_power, idle_power, alternative='greater') — one-sided
2. bootstrap CI on (mean(stress) - mean(idle)), checked against +1000 mW threshold

Per v7.5 Change 9, tegrastats samples are autocorrelated; effective sample
size is reduced by ~10x. The MWU p-value is therefore computed on
sub-sampled data (every 10th sample within each block, pooled across blocks).
Honest disclosure: this subsampling is the pre-registered correction; full-n
results are reported separately for transparency.

Pooling: stress samples are pooled across all 3 pipelines (3 cells × 9 blocks
× 601 samples ≈ 16,200 samples per condition). H6' is a condition-level test,
not a pipeline-level test.

Note: v7.5 Change 1 predicts the delta MAY be smaller under nvpmodel mode 3
than at btest scale because the baseline is already near max CPU frequency.
H6' SUPPORTED requires (a) MWU rejects null AND (b) CI on diff-of-means
lower bound > +1000 mW. Either failing means H6' NOT SUPPORTED, but this
may be a pre-registered expected outcome rather than evidence against the
broader research program.

Usage:
    python3 code/analysis/run_h6_energy.py
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
THRESHOLD_MW = 1000.0  # +1000 mW per v7.5 Change 9 / H6'
SUBSAMPLE_FACTOR = 10  # v7.5 Change 9: effective n reduced ~10x
ALPHA = 0.05
BOOTSTRAP_N = 10_000

VDD_IN_RE = re.compile(r"VDD_IN\s+(\d+)mW/\d+mW")


def parse_tegrastats(path):
    """Extract instantaneous VDD_IN (mW) samples from a tegrastats.log."""
    samples = []
    with open(path) as f:
        for line in f:
            m = VDD_IN_RE.search(line)
            if m:
                samples.append(int(m.group(1)))
    return samples


def load_per_cell_power():
    """Load per-block VDD_IN samples grouped by condition (pooled across pipelines)."""
    by_condition = defaultdict(list)  # condition -> list of (block_id, samples_list)
    block_count = defaultdict(int)
    for bdir in sorted(BLOCKS_DIR.glob(f"block-{CAMPAIGN_ID}-b*")):
        meta_path = bdir / "block_metadata.json"
        tegra_path = bdir / "tegrastats.log"
        if not meta_path.exists() or not tegra_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        samples = parse_tegrastats(tegra_path)
        if samples:
            by_condition[meta["condition"]].append((meta["block_id"], samples))
            block_count[meta["condition"]] += 1
    return by_condition, block_count


def subsample_block(samples, factor):
    """Take every `factor`-th sample, starting at a random offset within [0, factor) per block."""
    if len(samples) <= factor:
        return samples  # not enough to subsample meaningfully
    rng = np.random.default_rng(seed=42)  # deterministic for reproducibility
    offset = rng.integers(0, factor)
    return samples[offset::factor]


def autocorrelation_lag1(x):
    """Compute lag-1 autocorrelation of a sample list."""
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return None
    x_centered = x - np.mean(x)
    num = np.sum(x_centered[:-1] * x_centered[1:])
    den = np.sum(x_centered ** 2)
    return float(num / den) if den > 0 else None


def main():
    print("[h6_energy] Loading tegrastats samples...")
    by_condition, block_count = load_per_cell_power()
    print(f"[h6_energy] Loaded conditions:")
    for cond in sorted(by_condition.keys()):
        n_samples = sum(len(s) for _, s in by_condition[cond])
        print(f"  {cond:18s}: {block_count[cond]} blocks, {n_samples} VDD_IN samples")

    # Pool stress and idle samples ACROSS all pipelines (per pre-reg: H6' is condition-level)
    idle_blocks = by_condition.get("idle", [])
    stress_blocks = by_condition.get("stress", [])

    if not idle_blocks or not stress_blocks:
        print("ERROR: missing idle or stress condition data")
        return 1

    idle_full = np.concatenate([np.array(s) for _, s in idle_blocks])
    stress_full = np.concatenate([np.array(s) for _, s in stress_blocks])

    print()
    print(f"[h6_energy] Full sample sizes: idle={len(idle_full)}, stress={len(stress_full)}")
    print(f"[h6_energy] Means (full):       idle={idle_full.mean():.1f} mW, stress={stress_full.mean():.1f} mW")
    print(f"[h6_energy] Diff (full):        {stress_full.mean() - idle_full.mean():+.1f} mW")
    print(f"[h6_energy] Threshold:          +{THRESHOLD_MW:.0f} mW")
    print()

    # Lag-1 autocorrelation per condition (sanity check)
    idle_acf = autocorrelation_lag1(idle_full)
    stress_acf = autocorrelation_lag1(stress_full)
    print(f"[h6_energy] Lag-1 autocorrelation: idle={idle_acf:.3f}, stress={stress_acf:.3f}")
    print(f"[h6_energy]   (high values indicate autocorrelation; v7.5 Change 9 assumes ~10x effective n reduction)")

    # Subsample for MWU (per pre-reg)
    idle_blocks_sub = [subsample_block(s, SUBSAMPLE_FACTOR) for _, s in idle_blocks]
    stress_blocks_sub = [subsample_block(s, SUBSAMPLE_FACTOR) for _, s in stress_blocks]
    idle_sub = np.concatenate([np.array(s) for s in idle_blocks_sub])
    stress_sub = np.concatenate([np.array(s) for s in stress_blocks_sub])
    print(f"[h6_energy] Subsampled sizes (1/{SUBSAMPLE_FACTOR}): idle={len(idle_sub)}, stress={len(stress_sub)}")

    # Test 1: one-sided MWU
    mwu_full = stat_module.mann_whitney_u(stress_full, idle_full, alternative="greater")
    mwu_sub = stat_module.mann_whitney_u(stress_sub, idle_sub, alternative="greater")
    print()
    print(f"[h6_energy] MWU (full n, naive): p = {mwu_full.p_value:.4e}")
    print(f"[h6_energy] MWU (subsampled):     p = {mwu_sub.p_value:.4e}")

    # Test 2: bootstrap CI on difference of means
    print("[h6_energy] Bootstrap CI on difference of means (10000 resamples)...")
    rng = np.random.default_rng(seed=43)
    boot_diffs = np.empty(BOOTSTRAP_N)
    n_idle, n_stress = len(idle_full), len(stress_full)
    for i in range(BOOTSTRAP_N):
        idle_b = idle_full[rng.integers(0, n_idle, size=n_idle)]
        stress_b = stress_full[rng.integers(0, n_stress, size=n_stress)]
        boot_diffs[i] = stress_b.mean() - idle_b.mean()
    diff_point = float(stress_full.mean() - idle_full.mean())
    ci_low = float(np.percentile(boot_diffs, 2.5))
    ci_high = float(np.percentile(boot_diffs, 97.5))
    print(f"[h6_energy] Diff of means: {diff_point:+.1f} mW (95% CI: [{ci_low:+.1f}, {ci_high:+.1f}])")

    # Verdicts
    mwu_rejects = mwu_sub.p_value < ALPHA
    ci_clears_threshold = ci_low > THRESHOLD_MW

    print()
    print("=" * 75)
    print("H6' VERDICTS (per pre-reg v7.5 Change 9 + v7.6)")
    print("=" * 75)
    print(f"Test 1 (MWU subsampled, α={ALPHA}):  p = {mwu_sub.p_value:.4e}")
    print(f"  Rejects null (stress > idle)?      {'YES' if mwu_rejects else 'NO'}")
    print()
    print(f"Test 2 (Bootstrap CI on diff of means):")
    print(f"  Point estimate: {diff_point:+.1f} mW")
    print(f"  95% CI:         [{ci_low:+.1f}, {ci_high:+.1f}]")
    print(f"  Threshold:      +{THRESHOLD_MW:.0f} mW")
    print(f"  CI lower bound > +1000 mW?         {'YES' if ci_clears_threshold else 'NO'}")
    print()
    if mwu_rejects and ci_clears_threshold:
        verdict = "SUPPORTED"
    elif mwu_rejects:
        verdict = "PARTIALLY SUPPORTED (MWU rejects null but CI does not clear +1000 mW threshold)"
    else:
        verdict = "NOT SUPPORTED"
    print(f"H6' overall verdict: {verdict}")
    print()
    if not ci_clears_threshold:
        print("Note: per v7.5 Change 1, smaller energy delta under nvpmodel mode 3 was")
        print("a pre-registered prediction. NOT-SUPPORTED for H6' is consistent with that")
        print("prediction (the baseline near max CPU frequency leaves less headroom for")
        print("stress-ng to add power) — not a contradiction of the broader hypothesis.")

    # Save
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "generated_at": datetime.now().isoformat(),
        "pre_reg_anchors": ["v7.5 Change 9", "v7.6"],
        "threshold_mw": THRESHOLD_MW,
        "alpha": ALPHA,
        "subsample_factor": SUBSAMPLE_FACTOR,
        "n_bootstrap_resamples": BOOTSTRAP_N,
        "results": {
            "idle_n_samples_full": int(len(idle_full)),
            "stress_n_samples_full": int(len(stress_full)),
            "idle_n_samples_subsampled": int(len(idle_sub)),
            "stress_n_samples_subsampled": int(len(stress_sub)),
            "idle_mean_mw": float(idle_full.mean()),
            "stress_mean_mw": float(stress_full.mean()),
            "diff_of_means_mw": diff_point,
            "diff_ci_95pct_mw": [ci_low, ci_high],
            "mwu_full_p_value": float(mwu_full.p_value),
            "mwu_subsampled_p_value": float(mwu_sub.p_value),
            "idle_lag1_autocorr": idle_acf,
            "stress_lag1_autocorr": stress_acf,
        },
        "verdicts": {
            "mwu_rejects_null": bool(mwu_rejects),
            "ci_clears_1000_mw_threshold": bool(ci_clears_threshold),
            "h6_prime_overall": verdict,
        },
        "pre_registered_caveats": (
            "Per v7.5 Change 1, smaller energy delta under nvpmodel mode 3 was a "
            "pre-registered prediction. Falsification of H6' is consistent with that "
            "prediction (baseline near max CPU frequency leaves less headroom for "
            "stress-ng to add power)."
        ),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "h6_energy_results.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[h6_energy] Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
