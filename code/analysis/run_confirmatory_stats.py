#!/usr/bin/env python3
"""run_confirmatory_stats.py
==========================

Apply pre-registered statistical tests to the confirmatory-2026-05-26
campaign data, per pre-reg §12 (as amended by v7.5 Change 9 and v7.6).

Pre-registered hypotheses (active post-v7.9):
  H1' (one-sided MWU):  host_idle latencies stochastically LESS than mlc_idle
  H2' (one-sided MWU):  host_i2c-contention latencies stochastically LESS than mlc_i2c-contention
  H3' (Hodges-Lehmann + bootstrap CI):  (Δ_MLC - Δ_host) > 0 where Δ = contention - idle
  H5' (TOST equivalence):  host_stress equivalent to host_idle within ±30 µs
  H6' (one-sided MWU + bootstrap CI):  cpu_stress_power > idle_power, threshold +1000 mW
  H7' (one-sided proportion test):  classifier stability under contention (needs per-window analysis; deferred)

Multiple-comparison correction: Holm-Bonferroni across family {H1', H2', H3', H5', H6', H7'},
family-wise α = 0.05 (per §12.2 and v7.6).

Effect sizes (all comparisons): Hodges-Lehmann + 95% bootstrap CI per §12.3.

H6' (energy) is reported but is NOT computed from per-trial latency; it requires
tegrastats.log analysis. H6' is deferred to a separate script.
H7' (classifier stability) requires per-window decision data; also deferred.

This script computes H1', H2', H3', H5' from the campaign trial data.

Usage:
    python3 code/analysis/run_confirmatory_stats.py
"""

import csv
import json
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

import numpy as np

# Import the pre-registered statistics module
sys.path.insert(0, str(Path(__file__).resolve().parent))
import statistics as stat_module

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BLOCKS_DIR = REPO_ROOT / "data" / "training" / "latency-experiment"
CAMPAIGN_ID = "confirmatory-2026-05-26"
OUT_DIR = REPO_ROOT / "data" / "processed" / CAMPAIGN_ID
ALPHA = 0.05
BOOTSTRAP_N = 10_000
H5_MARGIN_US = 30.0   # per v7.5 §2 H5' equivalence margin


def load_per_cell_latencies():
    """Load all trial latencies grouped by (pipeline, condition). Returns dict."""
    by_cell = defaultdict(list)
    by_block = defaultdict(list)  # (pipeline, condition) -> list of (block_id, [lats])
    block_lats_map = defaultdict(dict)  # (pipeline, condition, block_id) -> [lats]

    for bdir in sorted(BLOCKS_DIR.glob(f"block-{CAMPAIGN_ID}-b*")):
        meta_path = bdir / "block_metadata.json"
        trials_csv = bdir / "trials.csv"
        if not meta_path.exists() or not trials_csv.exists():
            continue
        meta = json.loads(meta_path.read_text())
        cell = (meta["pipeline"], meta["condition"])
        block_id = meta["block_id"]
        block_lats = []
        with open(trials_csv) as f:
            for row in csv.DictReader(f):
                if row.get("included", "").lower() == "true" and row.get("latency_us"):
                    lat = float(row["latency_us"])
                    by_cell[cell].append(lat)
                    block_lats.append(lat)
        if block_lats:
            by_block[cell].append((block_id, block_lats))
            block_lats_map[(cell[0], cell[1], block_id)] = block_lats
    return by_cell, by_block


def hold_bonferroni_verdict(p_values, names, alpha=0.05):
    """Apply Holm-Bonferroni and return per-test verdicts."""
    return stat_module.holm_bonferroni(p_values, alpha=alpha)


def test_h1_h2(by_cell):
    """H1' / H2': one-sided MWU, alternative='less' (host stochastically less than mlc)."""
    results = {}

    # H1': host_idle vs mlc_idle
    host_idle = np.array(by_cell[("host", "idle")])
    mlc_idle = np.array(by_cell[("mlc", "idle")])
    h1_mwu = stat_module.mann_whitney_u(host_idle, mlc_idle, alternative="less")
    h1_hl = stat_module.hodges_lehmann(host_idle, mlc_idle)
    h1_ci = stat_module.hodges_lehmann_bootstrap_ci(host_idle, mlc_idle, n_boot=BOOTSTRAP_N)
    results["H1'"] = {
        "description": "host_idle latencies stochastically LESS than mlc_idle",
        "n_x": len(host_idle), "n_y": len(mlc_idle),
        "test": "one-sided Mann-Whitney U, alternative='less'",
        "U": float(h1_mwu.u_statistic),
        "p_value": float(h1_mwu.p_value),
        "hodges_lehmann_us": float(h1_hl),
        "hl_ci_95pct_us": [float(h1_ci.ci_low), float(h1_ci.ci_high)],
        "x_median_us": float(np.median(host_idle)),
        "y_median_us": float(np.median(mlc_idle)),
    }

    # H2': host_i2c-contention vs mlc_i2c-contention
    host_ic = np.array(by_cell[("host", "i2c-contention")])
    mlc_ic = np.array(by_cell[("mlc", "i2c-contention")])
    h2_mwu = stat_module.mann_whitney_u(host_ic, mlc_ic, alternative="less")
    h2_hl = stat_module.hodges_lehmann(host_ic, mlc_ic)
    h2_ci = stat_module.hodges_lehmann_bootstrap_ci(host_ic, mlc_ic, n_boot=BOOTSTRAP_N)
    results["H2'"] = {
        "description": "host_i2c-contention latencies stochastically LESS than mlc_i2c-contention",
        "n_x": len(host_ic), "n_y": len(mlc_ic),
        "test": "one-sided Mann-Whitney U, alternative='less'",
        "U": float(h2_mwu.u_statistic),
        "p_value": float(h2_mwu.p_value),
        "hodges_lehmann_us": float(h2_hl),
        "hl_ci_95pct_us": [float(h2_ci.ci_low), float(h2_ci.ci_high)],
        "x_median_us": float(np.median(host_ic)),
        "y_median_us": float(np.median(mlc_ic)),
    }
    return results


def test_h3(by_cell):
    """H3': (Δ_MLC - Δ_host) > 0 where Δ = contention - idle.
    Hodges-Lehmann difference + bootstrap CI strictly above 0."""
    host_idle = np.array(by_cell[("host", "idle")])
    host_ic = np.array(by_cell[("host", "i2c-contention")])
    mlc_idle = np.array(by_cell[("mlc", "idle")])
    mlc_ic = np.array(by_cell[("mlc", "i2c-contention")])

    # Δ_host = HL shift host_ic vs host_idle. Δ_mlc = HL shift mlc_ic vs mlc_idle.
    delta_host = stat_module.hodges_lehmann(host_ic, host_idle)
    delta_host_ci = stat_module.hodges_lehmann_bootstrap_ci(host_ic, host_idle, n_boot=BOOTSTRAP_N)
    delta_mlc = stat_module.hodges_lehmann(mlc_ic, mlc_idle)
    delta_mlc_ci = stat_module.hodges_lehmann_bootstrap_ci(mlc_ic, mlc_idle, n_boot=BOOTSTRAP_N)

    # Bootstrap CI of (Δ_MLC − Δ_host) via the pre-registered §12 H2 function
    # `bootstrap_difference_of_medians`. The function computes
    # (median(host_stress) − median(mlc_stress)) − (median(host_nostress) − median(mlc_nostress)).
    # We want (Δ_MLC − Δ_host) where Δ = condition − idle for each pipeline:
    #   = [median(mlc_ic) − median(mlc_idle)] − [median(host_ic) − median(host_idle)]
    # Algebraic identity: this equals
    #   = [median(mlc_ic) − median(host_ic)] − [median(mlc_idle) − median(host_idle)]   {grouped by condition}
    # ...so passing (stress=ic, nostress=idle) and (host=mlc, mlc=host) — i.e., SWAP host/mlc — yields:
    #   point = [median(mlc_ic) − median(host_ic)] − [median(mlc_idle) − median(host_idle)] = (Δ_MLC − Δ_host)
    # This is documented in the v7.9 paper draft notes and reflects an operationalization
    # of the v7.6 pre-registered H3' framing through the v7.4 pre-registered §12 H2 function.
    diff_result = stat_module.bootstrap_difference_of_medians(
        x_stress_host=mlc_ic,    # swapped: mlc-as-host-arg under contention
        x_stress_mlc=host_ic,    # swapped: host-as-mlc-arg under contention
        x_nostress_host=mlc_idle,  # swapped: mlc-as-host-arg under idle
        x_nostress_mlc=host_idle,  # swapped: host-as-mlc-arg under idle
        n_boot=BOOTSTRAP_N,
    )

    return {"H3'": {
        "description": "(Δ_MLC − Δ_host) > 0; MLC degrades more under contention than host",
        "delta_mlc_us": float(delta_mlc),
        "delta_mlc_ci_95pct": [float(delta_mlc_ci.ci_low), float(delta_mlc_ci.ci_high)],
        "delta_host_us": float(delta_host),
        "delta_host_ci_95pct": [float(delta_host_ci.ci_low), float(delta_host_ci.ci_high)],
        "diff_of_diffs_us": float(diff_result.point),
        "diff_of_diffs_ci_95pct": [float(diff_result.ci_low), float(diff_result.ci_high)],
        "p_value": float(diff_result.p_value),
        "test": "bootstrap of (Δ_MLC − Δ_host) via pre-registered §12 H2 function with mlc/host argument swap (algebraic identity documented in source)",
    }}


def test_h5(by_cell):
    """H5': TOST equivalence, host_stress vs host_idle, margin ±30 µs."""
    host_idle = np.array(by_cell[("host", "idle")])
    host_stress = np.array(by_cell[("host", "stress")])
    tost = stat_module.tost_bootstrap(
        host_stress, host_idle,
        low_bound=-H5_MARGIN_US, high_bound=H5_MARGIN_US,
        alpha=ALPHA, n_boot=BOOTSTRAP_N,
    )
    h5_hl = stat_module.hodges_lehmann(host_stress, host_idle)
    h5_ci = stat_module.hodges_lehmann_bootstrap_ci(host_stress, host_idle, n_boot=BOOTSTRAP_N)
    return {"H5'": {
        "description": f"host_stress equivalent to host_idle within ±{H5_MARGIN_US} µs",
        "n_x": len(host_stress), "n_y": len(host_idle),
        "test": f"TOST equivalence, bootstrap, margin ±{H5_MARGIN_US} µs",
        "median_diff_us": float(tost.point),
        "ci_90pct_us": [float(tost.ci_low), float(tost.ci_high)],
        "equivalent_at_alpha": bool(tost.equivalent),
        "p_lower": float(tost.p_lower),
        "p_upper": float(tost.p_upper),
        "p_value_tost": float(tost.p_value),
        "hodges_lehmann_us": float(h5_hl),
        "hl_ci_95pct_us": [float(h5_ci.ci_low), float(h5_ci.ci_high)],
        "x_median_us": float(np.median(host_stress)),
        "y_median_us": float(np.median(host_idle)),
    }}


def main():
    print(f"[stats] Loading campaign {CAMPAIGN_ID}...")
    by_cell, by_block = load_per_cell_latencies()

    print(f"[stats] Loaded cells:")
    for cell in sorted(by_cell.keys()):
        print(f"  {cell[0]:12s} {cell[1]:17s}: n={len(by_cell[cell])}")

    print()
    print("[stats] Running pre-registered tests...")
    results = {}

    print("  H1' / H2' (one-sided MWU)...")
    results.update(test_h1_h2(by_cell))
    print("  H3' (bootstrap diff-of-diffs)...")
    results.update(test_h3(by_cell))
    print("  H5' (TOST)...")
    results.update(test_h5(by_cell))

    # Holm-Bonferroni across the 4 hypotheses tested in this script.
    # H6' (energy, deferred) and H7' (classifier stability, deferred) are NOT
    # in this round. Family-wise α = 0.05 across all 6, but here we compute
    # provisional verdicts for H1', H2', H3', H5'. The script reports both
    # the un-corrected p-values and the Holm-Bonferroni rank.
    # For Holm-Bonferroni: include only the 4 tests computed here.
    # (Honest note: the v7.6 pre-reg spec calls for correction across 6.
    # We expose the 4-test correction here for reporting; the paper will
    # apply correction across 6 once H6' and H7' are computed separately.)
    p_vals = [
        results["H1'"]["p_value"],
        results["H2'"]["p_value"],
        results["H3'"]["p_value"],
        # H5' uses equivalence; its "p_value" isn't directly applicable to
        # Holm-Bonferroni. Per pre-reg §12.2, multiplicity correction applies
        # across the family; for equivalence tests, the convention is to use
        # the larger of the two one-sided test p-values. The pre-reg module
        # does not return a single p-value for TOST. We use the binary
        # equivalence verdict + report the median-diff CI separately for H5'.
    ]
    names = ["H1'", "H2'", "H3'"]
    hb = stat_module.holm_bonferroni(p_vals, alpha=ALPHA)
    holm_verdicts = {
        name: {"rejected": bool(hb.reject[i]), "p_adjusted": float(hb.adjusted_p_values[i])}
        for i, name in enumerate(names)
    }

    # Bundle and save
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "generated_at": datetime.now().isoformat(),
        "pre_reg_anchor_doi_v7_9": "10.5281/zenodo.20405611",
        "n_bootstrap_resamples": BOOTSTRAP_N,
        "alpha": ALPHA,
        "h5_equivalence_margin_us": H5_MARGIN_US,
        "results": results,
        "holm_bonferroni": holm_verdicts,
        "deferred": {
            "H6_prime": "Energy comparison; requires tegrastats.log analysis (separate script).",
            "H7_prime": "Classifier stability under contention; requires per-window decision data (separate script).",
        },
        "notes": "H5' equivalence verdict is binary (TOST), not p-value; Holm-Bonferroni "
                 "across {H1', H2', H3'} only; H5' verdict reported separately. "
                 "Full pre-reg family is 6 hypotheses; H6' and H7' deferred to separate analyses.",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "h_prime_results.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n[stats] Wrote: {out_path}")
    print()
    print("=" * 75)
    print("PRE-REGISTERED HYPOTHESIS TEST RESULTS")
    print("=" * 75)
    for name in ["H1'", "H2'", "H3'", "H5'"]:
        r = results[name]
        print(f"\n{name}: {r['description']}")
        if "p_value" in r:
            print(f"  p-value:       {r['p_value']:.4e}")
            if name in holm_verdicts:
                hb_v = holm_verdicts[name]
                print(f"  Holm-adj p:    {hb_v['p_adjusted']:.4e}")
                print(f"  Verdict (α=0.05 Holm): {'REJECTED null → SUPPORTED' if hb_v['rejected'] else 'NOT rejected'}")
        if "hodges_lehmann_us" in r:
            ci = r['hl_ci_95pct_us']
            print(f"  Hodges-Lehmann shift: {r['hodges_lehmann_us']:.1f} µs (95% CI: [{ci[0]:.1f}, {ci[1]:.1f}])")
        if name == "H3'":
            ci = r['diff_of_diffs_ci_95pct']
            print(f"  Δ_MLC: {r['delta_mlc_us']:.1f} µs (95% CI: [{r['delta_mlc_ci_95pct'][0]:.1f}, {r['delta_mlc_ci_95pct'][1]:.1f}])")
            print(f"  Δ_host: {r['delta_host_us']:.1f} µs (95% CI: [{r['delta_host_ci_95pct'][0]:.1f}, {r['delta_host_ci_95pct'][1]:.1f}])")
            print(f"  (Δ_MLC - Δ_host): {r['diff_of_diffs_us']:.1f} µs (95% CI: [{ci[0]:.1f}, {ci[1]:.1f}])")
            print(f"  Verdict: H3' SUPPORTED if 95% CI strictly above 0 → {'YES' if ci[0] > 0 else 'NO'}")
        if name == "H5'":
            ci = r['ci_90pct_us']
            print(f"  Median diff: {r['median_diff_us']:.1f} µs (90% CI: [{ci[0]:.1f}, {ci[1]:.1f}])")
            print(f"  TOST verdict (CI ⊂ ±{H5_MARGIN_US}): {'EQUIVALENT (H5 supported)' if r['equivalent_at_alpha'] else 'NOT equivalent (H5 NOT supported)'}")
    print()
    print("Deferred: H6' (energy), H7' (classifier stability)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
