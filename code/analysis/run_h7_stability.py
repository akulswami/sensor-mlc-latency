#!/usr/bin/env python3
"""run_h7_stability.py
=====================

H7' (classifier stability under I²C contention) analysis per pre-reg v7.6
Change 6 (Zenodo DOI 10.5281/zenodo.20400025).

Hypothesis (MLC bank-switch pipeline only):
  H7'₀: stability(MLC | i2c-contention) ≥ stability(MLC | idle)
  H7'₁: stability(MLC | i2c-contention) <  stability(MLC | idle)

Test: one-sided Fisher's exact at the per-trial level. Pre-reg specifies
"chi-square or Fisher's exact"; we use Fisher's exact because unstable
counts are small (≤15 per cell of n=540), where the chi-square
approximation can be inaccurate. Chi-square is computed for reference.

Operationalization: a trial is STABLE iff its (t_stim, t_next_stim] window
contained exactly 1 D1 rising edge. Equivalent in `trials.csv`:
  stable = exclusion_reason NOT IN {'no_d1_in_window', 'multiple_d1_in_window'}

`multiple_d0_before_d1` is a separate exclusion (D0 spacing on the MLC side)
and does NOT bear on H7' — those trials had exactly 1 D1 and are STABLE.
This matches the extractor's flow (see extract_latency_v7.py lines ~250-340:
D1 count is checked first; D0 pairing checks come after).

Holm-Bonferroni applied across full confirmatory family {H1', H2', H3',
H6', H7'} at family-wise α=0.05 per pre-reg v7.6. H5' uses TOST equivalence
and is reported separately (conventional exclusion from p-value-based
multiplicity correction).

Usage: python3 code/analysis/run_h7_stability.py
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.stats import chi2_contingency, fisher_exact

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BLOCKS_DIR = REPO_ROOT / "data" / "training" / "latency-experiment"
CAMPAIGN_ID = "confirmatory-2026-05-26"
OUT_DIR = REPO_ROOT / "data" / "processed" / CAMPAIGN_ID
ALPHA = 0.05

UNSTABLE_REASONS = {"no_d1_in_window", "multiple_d1_in_window"}

# p-values from prior per-hypothesis analyses (for Holm-Bonferroni
# across the full confirmatory family). These come from
# h_prime_results.json (2026-05-26) and h6_energy_results.json (2026-05-26).
PRIOR_PVALUES = {
    "H1'": 1.8660627704516216e-170,
    "H2'": 2.3317330777550803e-170,
    "H3'": 9.999000099990002e-05,
    "H6'": 0.0,  # MWU full-n; below float64 epsilon
}


def main():
    print(f"[h7_stability] Loading {CAMPAIGN_ID} MLC blocks...")
    counts = defaultdict(lambda: {"stable": 0, "unstable": 0,
                                  "no_d1": 0, "multi_d1": 0, "total": 0})

    blocks = sorted(BLOCKS_DIR.glob(f"block-{CAMPAIGN_ID}-b*"))
    for bdir in blocks:
        meta = json.loads((bdir / "block_metadata.json").read_text())
        if meta["pipeline"] != "mlc":
            continue
        cond = meta["condition"]
        with open(bdir / "trials.csv") as f:
            for row in csv.DictReader(f):
                counts[cond]["total"] += 1
                reason = row["exclusion_reason"]
                if reason == "no_d1_in_window":
                    counts[cond]["unstable"] += 1
                    counts[cond]["no_d1"] += 1
                elif reason == "multiple_d1_in_window":
                    counts[cond]["unstable"] += 1
                    counts[cond]["multi_d1"] += 1
                else:
                    counts[cond]["stable"] += 1

    print("[h7_stability] Per-condition tally (MLC pipeline only):")
    for cond in ["idle", "i2c-contention", "stress"]:
        c = counts[cond]
        rate = c["stable"] / c["total"] * 100 if c["total"] else 0
        print(f"  mlc/{cond:18s}: stable={c['stable']:4d}  "
              f"unstable={c['unstable']:3d} "
              f"(no_d1={c['no_d1']}, multi_d1={c['multi_d1']})  "
              f"total={c['total']:4d}  stability={rate:.2f}%")

    n_idle_s = counts["idle"]["stable"]
    n_idle_u = counts["idle"]["unstable"]
    n_cont_s = counts["i2c-contention"]["stable"]
    n_cont_u = counts["i2c-contention"]["unstable"]

    # 2x2 contingency: [[idle_stable, idle_unstable], [cont_stable, cont_unstable]]
    # alternative='greater' tests OR > 1, equivalent to H7'₁:
    #   odds(stable|idle) > odds(stable|cont) ⇔ p_cont < p_idle ⇔ H7'₁
    table = [[n_idle_s, n_idle_u], [n_cont_s, n_cont_u]]
    p_idle = n_idle_s / (n_idle_s + n_idle_u)
    p_cont = n_cont_s / (n_cont_s + n_cont_u)

    res_one = fisher_exact(table, alternative="greater")
    res_two = fisher_exact(table, alternative="two-sided")
    chi2, p_chi2, _, _ = chi2_contingency(np.array(table))

    rejected_one_sided = res_one.pvalue < ALPHA
    direction_matches = p_cont < p_idle

    if rejected_one_sided and direction_matches:
        verdict = "SUPPORTED"
    elif not direction_matches:
        verdict = "NOT SUPPORTED (direction OPPOSITE to pre-reg prediction)"
    else:
        verdict = "NOT SUPPORTED (correct direction but p ≥ α)"

    print()
    print("=" * 75)
    print("H7' RESULT (pre-registered one-sided Fisher's exact, MLC pipeline)")
    print("=" * 75)
    print(f"  p(stable | idle)       = {p_idle:.4f} ({n_idle_s}/{n_idle_s+n_idle_u})")
    print(f"  p(stable | contention) = {p_cont:.4f} ({n_cont_s}/{n_cont_s+n_cont_u})")
    print(f"  Δ (contention − idle)  = {(p_cont-p_idle)*100:+.2f} pp")
    print(f"  pre-reg prediction:    contention < idle  ({'MATCH' if direction_matches else 'OPPOSITE'})")
    print()
    print(f"  odds ratio:            {res_one.statistic:.4f}")
    print(f"  Fisher 1-sided (pre-reg direction, alt='greater'):  p = {res_one.pvalue:.4f}")
    print(f"  Fisher 2-sided (reference):                          p = {res_two.pvalue:.4f}")
    print(f"  Chi-square 2-sided (reference):  χ²={chi2:.3f}, p = {p_chi2:.4f}")
    print()
    print(f"  H7' VERDICT: {verdict}")

    # Holm-Bonferroni across full confirmatory family
    print()
    print("=" * 75)
    print("Holm-Bonferroni across full family {H1', H2', H3', H6', H7'} at α=0.05")
    print("=" * 75)
    family = list(PRIOR_PVALUES.items()) + [("H7'", res_one.pvalue)]
    sorted_family = sorted(family, key=lambda x: x[1])
    m = len(sorted_family)
    print(f"  rank | hypothesis | raw p          | Holm-adj p      | threshold      | rejected")
    print(f"  -----+------------+----------------+-----------------+----------------+----------")
    for i, (name, p) in enumerate(sorted_family):
        adj_p = min(1.0, p * (m - i))
        threshold = ALPHA / (m - i)
        rej = p <= threshold
        print(f"  {i+1:4d} | {name:10s} | {p:14.4e} | {adj_p:15.4e} | {threshold:14.4e} | {rej}")

    # Save JSON
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "generated_at": datetime.now().isoformat(),
        "pre_reg_anchor": "v7.6 Change 6 (Zenodo DOI 10.5281/zenodo.20400025)",
        "hypothesis": {
            "name": "H7'",
            "description": "Classifier stability under I²C contention (MLC pipeline)",
            "null": "stability(MLC | i2c-contention) >= stability(MLC | idle)",
            "alternative": "stability(MLC | i2c-contention) < stability(MLC | idle)",
            "pipeline_under_test": "mlc (bank-switch)",
            "operationalization": ("stable = trial has exactly 1 D1 in stimulus window "
                                   "(exclusion_reason NOT in {no_d1_in_window, multiple_d1_in_window})"),
        },
        "per_condition_counts": {k: dict(v) for k, v in counts.items()},
        "contingency_table_idle_vs_contention": {
            "row_idle": [n_idle_s, n_idle_u],
            "row_contention": [n_cont_s, n_cont_u],
        },
        "stability_rates": {
            "idle": p_idle,
            "contention": p_cont,
            "diff_pp": (p_cont - p_idle) * 100,
        },
        "test_results": {
            "fisher_one_sided_alternative_greater": {
                "odds_ratio": float(res_one.statistic),
                "p_value": float(res_one.pvalue),
                "interpretation": ("alt='greater' tests OR>1, equivalent to H7'₁ "
                                   "(idle more stable than contention)"),
            },
            "fisher_two_sided": {
                "odds_ratio": float(res_two.statistic),
                "p_value": float(res_two.pvalue),
            },
            "chi_square_two_sided": {
                "statistic": float(chi2),
                "p_value": float(p_chi2),
            },
        },
        "verdict": verdict,
        "alpha": ALPHA,
        "rejected_one_sided_pre_reg_direction": bool(rejected_one_sided and direction_matches),
        "direction_matches_prediction": bool(direction_matches),
        "holm_bonferroni_family": {
            "family": ["H1'", "H2'", "H3'", "H6'", "H7'"],
            "alpha": ALPHA,
            "results": {name: {"raw_p": float(p),
                               "rank": i + 1,
                               "adjusted_p": float(min(1.0, p * (m - i))),
                               "threshold": float(ALPHA / (m - i)),
                               "rejected": bool(p <= ALPHA / (m - i))}
                        for i, (name, p) in enumerate(sorted_family)},
            "note": ("H5' uses TOST equivalence and is reported separately. "
                     "It is not included in this Holm-Bonferroni family per convention."),
        },
        "notes": ("Three pre-registered hypotheses have been falsified during this study: "
                  "H1 (btest scale, v7.5), H4' (long-duration jc-effective, v7.6), and "
                  "H7' (this analysis). Each is recorded with empirical evidence; the "
                  "pre-registration discipline preserves the audit trail."),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "h7_stability_results.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print()
    print(f"[h7_stability] Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
