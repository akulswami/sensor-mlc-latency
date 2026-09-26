#!/usr/bin/env python3
"""
verify_letter_stats.py -- READ-ONLY verifier for the three statistical claim
sets in the response letter that have never been independently recomputed
from raw data:

  R1P2  CPU-affinity investigation
        - 232/232 pinned trials < 150 us
        - 70.1% >= 150 us in the original campaign (confirmatory mlc-binary/idle, n=531)
        - MWU p ~= 1.8e-75 (pinned vs original campaign)
        - Hodges-Lehmann shift -184.4 us
        - same-session unpinned control vs pinned blocks: p = 0.673
  R1P1  INT1 pulse width
        - median 9,007.9 us, IQR 9,006.4-9,009.1, n = 1,669 pulses
          across 27 confirmatory mlc blocks
  R1P5  Energy (post-hoc, run_pipeline_energy.py methodology)
        - VDD_CPU_GPU_CV, host vs mlc:
            idle       p ~= 8.4e-92,  diff +31.1 mW [27.8, 34.4]
            contention p ~= 5.5e-8,   diff  +7.3 mW [3.9, 10.7]
            stress     p ~= 1.4e-8,   CI [-28.8, 14.6]
        - VDD_IN idle: diff +37.3 mW [33.2, 41.4]  (~0.7% of 5,206 mW)

Methodology rules:
  * This script READS raw data and the analysis script's SOURCE. It never
    imports or executes project analysis code; the energy computation is an
    independent re-implementation. Statistical parameters (subsample factor,
    bootstrap N, seeds, campaign id, rail regexes, pipeline set) are extracted
    from the script source and verified, not assumed.
  * Because run_pipeline_energy.py uses fixed numpy seeds (42/43/44), the
    energy numbers must reproduce EXACTLY. Any mismatch is a finding.
  * Writes nothing. No output files, no caches, no edits.

Run from the repo root:
    python3 verify_letter_stats.py            # or: --root /path/to/repo
Exit code 0 = every check passed; 1 = at least one FAIL/ERROR.
"""

import argparse
import bisect
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np
from scipy import stats

RESULTS = []


def check(section, name, ok, detail):
    ok = bool(ok)
    RESULTS.append((section, name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def info(msg):
    print(f"  [info] {msg}")


class VerifierError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# numeric comparison helpers (claims are rounded; tolerance = half last digit)
# ---------------------------------------------------------------------------

def p_matches(computed, mantissa, exponent):
    """mantissa has 2 sig figs, e.g. 8.4e-92 -> window +-0.05e-92."""
    claimed = mantissa * 10.0 ** exponent
    tol = 0.05 * 10.0 ** exponent
    return abs(computed - claimed) <= tol


def dec_matches(computed, claimed, digits):
    return abs(computed - claimed) <= 0.5 * 10.0 ** (-digits) + 1e-12


# ---------------------------------------------------------------------------
# shared loaders
# ---------------------------------------------------------------------------

def load_trial_latencies(trials_path):
    """Included-trial latencies (us) from a trials.csv."""
    lat = []
    with open(trials_path, newline="") as f:
        for row in csv.DictReader(f):
            inc = (row.get("included") or "").strip()
            if inc not in ("True", "true", "1"):
                continue
            lat.append(float(row["latency_us"]))
    return lat


def load_meta(block_dir):
    p = block_dir / "block_metadata.json"
    if not p.exists():
        raise VerifierError(f"missing block_metadata.json in {block_dir.name}")
    return json.loads(p.read_text())


# ===========================================================================
# PART 1 -- R1P2: affinity investigation
# ===========================================================================

def part1_affinity(root):
    print("\n=== PART 1: R1P2 affinity statistics ===")
    lat_dir = root / "data/training/latency-experiment"
    if not lat_dir.is_dir():
        raise VerifierError(f"not found: {lat_dir}")

    # ---- affinity-session blocks, grouped from metadata -------------------
    aff = {}  # block_id -> (meta, latencies)
    for d in sorted(lat_dir.glob("block-affinity-2026-09-21-*")):
        meta = load_meta(d)
        tp = d / "trials.csv"
        if not tp.exists():
            raise VerifierError(f"missing trials.csv in {d.name}")
        aff[meta["block_id"]] = (meta, load_trial_latencies(tp))

    for bid, (meta, lat) in sorted(aff.items()):
        info(f"{bid}: pipeline={meta.get('pipeline')} condition={meta.get('condition')} "
             f"pin={meta.get('affinity_pin')} btest={meta.get('btest')} "
             f"included={meta.get('included')} n_included_trials={len(lat)}")

    def pool(pred):
        out = []
        for meta, lat in aff.values():
            if pred(meta):
                out.extend(lat)
        return np.asarray(out, dtype=float)

    is_main_b = lambda m: re.search(r"-b\d{3}$", m["block_id"]) is not None
    base = lambda m: (m.get("included", True) and not m.get("btest", False)
                      and m.get("pipeline") == "mlc-binary" and m.get("condition") == "idle")

    pinned_sets = {
        "b001-b003 only": pool(lambda m: base(m) and m.get("affinity_pin") is True and is_main_b(m)),
        "pin=True mlc-binary idle (incl. smoke)": pool(lambda m: base(m) and m.get("affinity_pin") is True),
        "pin=True any pipeline": pool(lambda m: m.get("included", True) and not m.get("btest", False)
                                     and m.get("affinity_pin") is True),
    }
    for name, arr in pinned_sets.items():
        if len(arr):
            info(f"pinned candidate '{name}': n={len(arr)}, "
                 f"<150us: {int((arr < 150).sum())}, max={arr.max():.2f} us")

    pinned = pinned_sets["b001-b003 only"]
    if len(pinned) == 0:
        raise VerifierError("no pinned b00x trials found")
    ctrl = pool(lambda m: base(m) and m.get("affinity_pin") is False)
    if len(ctrl) == 0:
        raise VerifierError("no unpinned same-session control trials found")
    pinned_ctrl = np.concatenate([pinned, ctrl])
    info(f"pinned+control pooled: n={len(pinned_ctrl)}, "
         f"<150us: {int((pinned_ctrl < 150).sum())}, max={pinned_ctrl.max():.2f} us")
    check("R1P2", "all session trials < 150 us",
          bool((pinned < 150).all()) and bool((ctrl < 150).all()),
          f"pinned(b001-b003) n={len(pinned)} max={pinned.max():.2f} us; "
          f"control n={len(ctrl)} max={ctrl.max():.2f} us")
    check("R1P2", "trial count 232",
          len(pinned) == 232 or len(pinned_ctrl) == 232,
          f"pinned(b001-b003)={len(pinned)}, pinned+control={len(pinned_ctrl)} "
          f"(claim: 232 -- if it matches the pooled count, verify the letter's wording)")

    # ---- original campaign: confirmatory mlc-binary / idle -----------------
    orig = []
    n_orig_blocks = 0
    for d in sorted(lat_dir.glob("block-confirmatory-2026-05-26-*")):
        meta = load_meta(d)
        if not meta.get("included", True):
            continue
        if meta.get("pipeline") == "mlc-binary" and meta.get("condition") == "idle":
            tp = d / "trials.csv"
            if not tp.exists():
                raise VerifierError(f"missing trials.csv in {d.name}")
            orig.extend(load_trial_latencies(tp))
            n_orig_blocks += 1
    orig = np.asarray(orig, dtype=float)
    pct_ge = 100.0 * float((orig >= 150).mean())
    info(f"original campaign: {n_orig_blocks} confirmatory mlc-binary/idle blocks, "
         f"n={len(orig)}, >=150us: {int((orig >= 150).sum())} ({pct_ge:.2f}%)")
    check("R1P2", "original campaign n=531", len(orig) == 531, f"computed n={len(orig)}")
    check("R1P2", "original campaign 70.1% >= 150 us", dec_matches(pct_ge, 70.1, 1),
          f"computed {pct_ge:.2f}% (claim: 70.1%)")

    # ---- MWU + Hodges-Lehmann: pinned vs original --------------------------
    mwu = stats.mannwhitneyu(pinned, orig, alternative="two-sided")
    hl = float(np.median(np.subtract.outer(pinned, orig)))
    info(f"pinned vs original: MWU U={mwu.statistic:.1f}, p={mwu.pvalue:.3e}, "
         f"HL shift={hl:.2f} us, medians {np.median(pinned):.2f} vs {np.median(orig):.2f} us")
    check("R1P2", "MWU p ~= 1.8e-75", p_matches(mwu.pvalue, 1.8, -75),
          f"computed p={mwu.pvalue:.3e} (claim: 1.8e-75)")
    check("R1P2", "HL shift -184.4 us", dec_matches(hl, -184.4, 1),
          f"computed {hl:.2f} us (claim: -184.4)")

    # ---- same-session unpinned control comparisons -------------------------
    mwu_ctrl_pin = stats.mannwhitneyu(ctrl, pinned, alternative="two-sided")
    mwu_ctrl_orig = stats.mannwhitneyu(ctrl, orig, alternative="two-sided")
    info(f"control (ctrl001): n={len(ctrl)}, median={np.median(ctrl):.2f} us, "
         f">=150us: {100.0 * float((ctrl >= 150).mean()):.1f}%")
    info(f"control vs original (informational): p={mwu_ctrl_orig.pvalue:.3e}")
    check("R1P2", "control vs pinned p = 0.673", dec_matches(mwu_ctrl_pin.pvalue, 0.673, 3),
          f"computed p={mwu_ctrl_pin.pvalue:.4f} (claim: 0.673)")


# ===========================================================================
# PART 2 -- R1P1: INT1 pulse width from digital.csv
# ===========================================================================

def read_digital(path):
    """Return (times, [ch0, ch1, ch2]) as numpy arrays. Transition-based CSV."""
    ts, c0, c1, c2 = [], [], [], []
    with open(path, newline="") as f:
        r = csv.reader(f)
        header = next(r)
        if not header or not header[0].startswith("Time"):
            raise VerifierError(f"unexpected digital.csv header in {path.parent.name}: {header}")
        for row in r:
            if not row:
                continue
            ts.append(float(row[0]))
            c0.append(int(row[1])); c1.append(int(row[2])); c2.append(int(row[3]))
    return np.asarray(ts), [np.asarray(c0), np.asarray(c1), np.asarray(c2)]


def pulses_us(ts, vs):
    """Complete high pulses (both edges observed): list of (rise_t_s, width_us)."""
    out = []
    rise = None
    prev = None
    for t, v in zip(ts, vs):
        if prev is None:
            prev = v
            continue
        if prev == 0 and v == 1:
            rise = t
        elif prev == 1 and v == 0 and rise is not None:
            out.append((rise, (t - rise) * 1e6))
            rise = None
        prev = v
    return out


def _near(t, sorted_targets, tol_s=2e-3):
    i = bisect.bisect_left(sorted_targets, t)
    for j in (i - 1, i):
        if 0 <= j < len(sorted_targets) and abs(sorted_targets[j] - t) <= tol_s:
            return True
    return False


def channel_match_frac(edges, targets, tol_s=2e-3):
    if not edges or not targets:
        return 0.0
    return sum(1 for t in targets if _near(t, edges, tol_s)) / len(targets)


def part2_pulse_width(root):
    print("\n=== PART 2: R1P1 INT1 pulse width ===")
    lat_dir = root / "data/training/latency-experiment"

    # tuple: (block_id, pipeline, widths_all_complete_pulses, widths_matched_to_included_trials)
    blocks = []
    for d in sorted(lat_dir.glob("block-confirmatory-2026-05-26-*")):
        meta = load_meta(d)
        if not meta.get("included", True):
            continue
        if meta.get("pipeline") not in ("mlc", "mlc-binary"):
            continue
        dig = d / "digital.csv"
        if not dig.exists():
            info(f"{d.name}: no digital.csv, skipped")
            continue
        tp = d / "trials.csv"
        if not tp.exists():
            raise VerifierError(f"missing trials.csv in {d.name}")

        ts, chans = read_digital(dig)
        pulses_per_ch = [pulses_us(ts, c) for c in chans]
        # identify the D0/INT1 channel by matching pulse rising edges to trials' t_d0_s
        with open(tp, newline="") as f:
            rows = list(csv.DictReader(f))
        t_d0_inc = sorted(float(r["t_d0_s"]) for r in rows
                          if (r.get("included") or "").strip() in ("True", "true", "1")
                          and (r.get("t_d0_s") or "").strip())
        t_d0_all = sorted(float(r["t_d0_s"]) for r in rows
                          if (r.get("t_d0_s") or "").strip())
        fracs = [channel_match_frac(sorted(r for r, _ in p), t_d0_inc) for p in pulses_per_ch]
        best = int(np.argmax(fracs))
        if fracs[best] < 0.5:
            raise VerifierError(
                f"{d.name}: no digital channel matches t_d0_s "
                f"(match fractions {['%.2f' % x for x in fracs]})")
        if fracs[best] < 0.9:
            info(f"{d.name}: WARNING weak channel match ch{best} frac={fracs[best]:.2f}")

        pulses = pulses_per_ch[best]
        widths_all = [w for _, w in pulses]
        widths_matched_inc = [w for r, w in pulses if _near(r, t_d0_inc)]
        widths_matched_all = [w for r, w in pulses if _near(r, t_d0_all)]
        blocks.append((meta["block_id"], meta["pipeline"],
                       widths_all, widths_matched_inc, widths_matched_all))

    if not blocks:
        raise VerifierError("no confirmatory mlc/mlc-binary blocks with digital.csv found")

    def stats_of(sel, idx, pred=None):
        pooled = np.asarray([w for b in sel for w in b[idx] if pred is None or pred(w)],
                            dtype=float)
        if len(pooled) == 0:
            return None
        q1l, q3l = np.percentile(pooled, [25, 75])
        q1h, q3h = np.percentile(pooled, [25, 75], method="higher")
        return {"n": len(pooled), "med": float(np.median(pooled)),
                "q1l": q1l, "q3l": q3l, "q1h": q1h, "q3h": q3h}

    WIDTH_VARIANTS = ((lambda w: w > 1000.0, "width > 1 ms"),
                      (lambda w: 1000.0 < w < 20000.0, "width 1-20 ms"))

    def show(label, sel):
        for idx, vname in ((2, "all complete pulses"), (3, "matched to included trials"),
                           (4, "matched to all trials")):
            s = stats_of(sel, idx)
            if s:
                info(f"{label} [{vname}]: blocks={len(sel)}, pulses={s['n']}, "
                     f"median={s['med']:.2f} us, IQR(linear)=[{s['q1l']:.2f}, {s['q3l']:.2f}], "
                     f"IQR(higher)=[{s['q1h']:.2f}, {s['q3h']:.2f}]")
        for pred, vname in WIDTH_VARIANTS:
            s = stats_of(sel, 2, pred)
            if s:
                info(f"{label} [{vname}]: blocks={len(sel)}, pulses={s['n']}, "
                     f"median={s['med']:.2f} us, IQR(linear)=[{s['q1l']:.2f}, {s['q3l']:.2f}], "
                     f"IQR(higher)=[{s['q1h']:.2f}, {s['q3h']:.2f}]")

    g_mlc = [b for b in blocks if b[1] == "mlc"]
    g_mlcb = [b for b in blocks if b[1] == "mlc-binary"]
    show("pipeline=mlc", g_mlc)
    show("pipeline=mlc-binary", g_mlcb)
    show("mlc + mlc-binary", blocks)

    variants = [s for s in (stats_of(g_mlc, 2), stats_of(g_mlc, 3), stats_of(g_mlc, 4),
                            stats_of(g_mlc, 2, WIDTH_VARIANTS[0][0]),
                            stats_of(g_mlc, 2, WIDTH_VARIANTS[1][0])) if s]
    if not variants:
        raise VerifierError("no mlc-pipeline pulses")
    check("R1P1", "27 mlc blocks", len(g_mlc) == 27, f"computed {len(g_mlc)} blocks")
    check("R1P1", "n = 1,669 pulses", any(s["n"] == 1669 for s in variants),
          "computed n=" + ", ".join(str(s["n"]) for s in variants)
          + " (variants: all, matched-inc, matched-all, >1ms, 1-20ms)")
    check("R1P1", "median 9,007.9 us", any(dec_matches(s["med"], 9007.9, 1) for s in variants),
          "computed median=" + ", ".join(f"{s['med']:.2f}" for s in variants) + " us")
    def iqr_ok(s):
        lin = dec_matches(s["q1l"], 9006.4, 1) and dec_matches(s["q3l"], 9009.1, 1)
        hi = dec_matches(s["q1h"], 9006.4, 1) and dec_matches(s["q3h"], 9009.1, 1)
        return lin or hi
    check("R1P1", "IQR 9,006.4-9,009.1 us", any(iqr_ok(s) for s in variants),
          "computed " + "; ".join(
              f"linear=[{s['q1l']:.2f}, {s['q3l']:.2f}] higher=[{s['q1h']:.2f}, {s['q3h']:.2f}]"
              for s in variants))


# ===========================================================================
# PART 3 -- R1P5: energy (independent re-implementation of run_pipeline_energy.py)
# ===========================================================================

def extract_int(src, name):
    m = re.search(rf"\b{name}\s*=\s*(\d[\d_]*)", src)
    if not m:
        raise VerifierError(f"could not extract {name} from run_pipeline_energy.py")
    return int(m.group(1).replace("_", ""))


def extract_str(src, name):
    m = re.search(rf"\b{name}\s*=\s*[\"']([^\"']+)[\"']", src)
    if not m:
        raise VerifierError(f"could not extract {name} from run_pipeline_energy.py")
    return m.group(1)


def extract_pipelines(src):
    m = re.search(r"\bPIPELINES\s*=\s*[\{\(\[]([^\}\)\]]+)", src)
    if not m:
        raise VerifierError("could not extract PIPELINES from run_pipeline_energy.py")
    names = set(re.findall(r'["\']([^"\']+)["\']', m.group(1)))
    if not names:
        raise VerifierError("PIPELINES extracted but contains no quoted names")
    return names


def extract_rail_pattern(src, rail):
    m = re.search(r'[rR]?["\']([^"\']*' + re.escape(rail) + r'[^"\']*mW[^"\']*)["\']', src)
    if not m:
        raise VerifierError(f"could not extract rail regex for {rail}")
    return m.group(1)


def part3_energy(root):
    print("\n=== PART 3: R1P5 energy (re-implementation of run_pipeline_energy.py) ===")
    script_path = root / "code/analysis/run_pipeline_energy.py"
    if not script_path.exists():
        raise VerifierError(f"not found: {script_path}")
    src = script_path.read_text()

    SUBSAMPLE_FACTOR = extract_int(src, "SUBSAMPLE_FACTOR")
    BOOTSTRAP_N = extract_int(src, "BOOTSTRAP_N")
    CAMPAIGN_ID = extract_str(src, "CAMPAIGN_ID")
    PIPELINES = extract_pipelines(src)
    rail_pats = {r: re.compile(extract_rail_pattern(src, r)) for r in ("VDD_CPU_GPU_CV", "VDD_IN")}
    for seed in (42, 43, 44):
        if f"seed={seed}" not in src:
            info(f"WARNING: seed={seed} not found verbatim in script source; "
                 f"verify subsample/bootstrap seeds manually")
    info(f"extracted: CAMPAIGN_ID={CAMPAIGN_ID!r}, PIPELINES={sorted(PIPELINES)}, "
         f"SUBSAMPLE_FACTOR={SUBSAMPLE_FACTOR}, BOOTSTRAP_N={BOOTSTRAP_N}")
    for r, p in rail_pats.items():
        info(f"rail regex {r}: {p.pattern!r}")

    lat_dir = root / "data/training/latency-experiment"
    bl = re.search(r"\bBLOCKS_DIR\s*=\s*(.+)", src)
    if bl and "latency-experiment" not in bl.group(1):
        info(f"WARNING: script BLOCKS_DIR line does not mention latency-experiment: {bl.group(1).strip()}")

    # ---- loader (re-implementation) ---------------------------------------
    from collections import defaultdict
    grouped = defaultdict(lambda: defaultdict(list))
    block_count = defaultdict(int)
    for bdir in sorted(lat_dir.glob(f"block-{CAMPAIGN_ID}-b*")):
        meta_path, tegra_path = bdir / "block_metadata.json", bdir / "tegrastats.log"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        if not meta.get("included", True):
            continue
        if not tegra_path.exists():
            continue
        pipeline, condition = meta.get("pipeline"), meta.get("condition")
        if pipeline not in PIPELINES or condition is None:
            continue
        rails = defaultdict(list)
        with open(tegra_path) as f:
            for line in f:
                for rail, pat in rail_pats.items():
                    m = pat.search(line)
                    if m:
                        rails[rail].append(int(m.group(1)))
        for rail, samples in rails.items():
            grouped[(pipeline, condition)][rail].extend(samples)
        block_count[(pipeline, condition)] += 1

    for (pl, cond), rails in sorted(grouped.items()):
        info(f"group {pl}/{cond}: blocks={block_count[(pl, cond)]}, "
             f"n(VDD_CPU_GPU_CV)={len(rails.get('VDD_CPU_GPU_CV', []))}, "
             f"n(VDD_IN)={len(rails.get('VDD_IN', []))}")

    # ---- statistics (re-implementation; deterministic, seeds 42/43/44) -----
    def subsample(samples, factor, seed):
        samples = np.asarray(samples, dtype=float)
        if len(samples) <= factor:
            return samples
        rng = np.random.default_rng(seed=seed)
        offset = rng.integers(0, factor)
        return samples[offset::factor]

    def compare(a_samples, b_samples):
        a = np.asarray(a_samples, dtype=float)
        b = np.asarray(b_samples, dtype=float)
        a_sub = subsample(a, SUBSAMPLE_FACTOR, seed=42)
        b_sub = subsample(b, SUBSAMPLE_FACTOR, seed=43)
        mwu = stats.mannwhitneyu(a_sub, b_sub, alternative="two-sided")
        rng = np.random.default_rng(seed=44)
        n_a, n_b = len(a), len(b)
        diffs = np.empty(BOOTSTRAP_N)
        for i in range(BOOTSTRAP_N):
            a_b = a[rng.integers(0, n_a, size=n_a)]
            b_b = b[rng.integers(0, n_b, size=n_b)]
            diffs[i] = a_b.mean() - b_b.mean()
        return {
            "p": float(mwu.pvalue),
            "diff": float(a.mean() - b.mean()),
            "lo": float(np.percentile(diffs, 2.5)),
            "hi": float(np.percentile(diffs, 97.5)),
            "a_mean": float(a.mean()), "b_mean": float(b.mean()),
            "n_a": n_a, "n_b": n_b,
        }

    # ---- run all comparisons, then check claims ---------------------------
    cond_map = {}
    for cond in sorted({c for (_, c) in grouped}):
        cl = cond.lower()
        if "idle" in cl:
            cond_map["idle"] = cond
        elif "contention" in cl:
            cond_map["contention"] = cond
        elif "stress" in cl:
            cond_map["stress"] = cond
    if len(cond_map) != 3:
        raise VerifierError(f"could not map conditions to idle/contention/stress; "
                            f"present: {sorted({c for (_, c) in grouped})}")

    results = {}  # (cond_label, rail, pair) -> result
    for clabel, cond in sorted(cond_map.items()):
        for rail in ("VDD_CPU_GPU_CV", "VDD_IN"):
            host = grouped.get(("host", cond), {}).get(rail, [])
            for other in ("mlc", "mlc-binary"):
                o = grouped.get((other, cond), {}).get(rail, [])
                if host and o:
                    r = compare(host, o)
                    results[(clabel, rail, other)] = r
                    print(f"  [data] {clabel:10s} {rail:15s} host vs {other:10s} "
                          f"n={r['n_a']}/{r['n_b']} means={r['a_mean']:.1f}/{r['b_mean']:.1f} mW  "
                          f"diff={r['diff']:+.1f} [{r['lo']:+.1f}, {r['hi']:+.1f}]  p={r['p']:.3e}")

    def get(clabel, rail, pair="mlc"):
        r = results.get((clabel, rail, pair))
        if r is None:
            raise VerifierError(f"missing comparison {clabel}/{rail}/host-vs-{pair}")
        return r

    claims = [
        ("idle",       8.4, -92, 31.1, 27.8, 34.4),
        ("contention", 5.5,  -8,  7.3,  3.9, 10.7),
        ("stress",     1.4,  -8, None, -28.8, 14.6),
    ]
    for clabel, mant, ex, diff_c, lo_c, hi_c in claims:
        r = get(clabel, "VDD_CPU_GPU_CV", "mlc")
        check("R1P5", f"VDD_CPU_GPU_CV {clabel} p ~={mant}e{ex}",
              p_matches(r["p"], mant, ex), f"computed p={r['p']:.3e}")
        if diff_c is not None:
            check("R1P5", f"VDD_CPU_GPU_CV {clabel} diff {diff_c:+.1f} mW",
                  dec_matches(r["diff"], diff_c, 1), f"computed {r['diff']:+.2f} mW")
        check("R1P5", f"VDD_CPU_GPU_CV {clabel} CI [{lo_c:+.1f}, {hi_c:+.1f}]",
              dec_matches(r["lo"], lo_c, 1) and dec_matches(r["hi"], hi_c, 1),
              f"computed [{r['lo']:+.2f}, {r['hi']:+.2f}] mW")

    r_in = get("idle", "VDD_IN", "mlc")
    check("R1P5", "VDD_IN idle diff +37.3 mW [33.2, 41.4]",
          dec_matches(r_in["diff"], 37.3, 1) and dec_matches(r_in["lo"], 33.2, 1)
          and dec_matches(r_in["hi"], 41.4, 1),
          f"computed {r_in['diff']:+.2f} [{r_in['lo']:+.2f}, {r_in['hi']:+.2f}] mW")
    # The letter attributes the 5,206 mW baseline to H6' ("VDD_IN baseline, H6'"),
    # NOT to the post-hoc pipeline-energy pooling (whose host idle mean is 5,230.4).
    # Check provenance: h6_energy_results.json must contain idle_mean_mw ~= 5206.44,
    # and the letter's ratio arithmetic must hold against it.
    host_in_idle = np.asarray(grouped[("host", cond_map["idle"])]["VDD_IN"], dtype=float)
    info(f"post-hoc pooling host VDD_IN idle: mean={r_in['a_mean']:.1f} mW, "
         f"median={float(np.median(host_in_idle)):.1f} mW "
         f"(NOT the letter's cited baseline -- the letter cites H6')")
    h6_path = root / "data/processed/confirmatory-2026-05-26/h6_energy_results.json"
    if not h6_path.exists():
        raise VerifierError(f"not found: {h6_path} (needed for H6' baseline provenance)")
    h6 = json.loads(h6_path.read_text())
    found = []

    def _walk(o, path="$"):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "idle_mean_mw" and isinstance(v, (int, float)):
                    found.append((path, float(v)))
                else:
                    _walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                _walk(v, f"{path}[{i}]")

    _walk(h6)
    for pth, v in found:
        info(f"h6_energy_results.json: idle_mean_mw at {pth} = {v:.2f} mW")
    h6_base = next((v for _, v in found if dec_matches(v, 5206.0, 0)), None)
    pct_h6 = 100.0 * r_in["diff"] / h6_base if h6_base else float("nan")
    check("R1P5", "5,206 mW baseline traceable to H6' + ratio ~0.7%",
          h6_base is not None and dec_matches(pct_h6, 0.7, 1),
          f"H6' idle_mean_mw={h6_base if h6_base else 'NOT FOUND'} mW; "
          f"37.27/{h6_base:.1f} = {pct_h6:.2f}% (claim: 5,206 mW, ~0.7%)"
          if h6_base else f"no idle_mean_mw ~= 5206 in {found}")


# ===========================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    import scipy
    print("verify_letter_stats.py -- READ-ONLY (writes nothing)")
    print(f"root: {root}")
    print(f"numpy {np.__version__}, scipy {scipy.__version__}")

    for fn in (part1_affinity, part2_pulse_width, part3_energy):
        try:
            fn(root)
        except VerifierError as e:
            check(fn.__name__, "section completed", False, f"ERROR: {e}")
        except Exception as e:  # fail loud, but keep going
            check(fn.__name__, "section completed", False,
                  f"UNEXPECTED {type(e).__name__}: {e}")

    n_fail = sum(1 for _, _, ok, _ in RESULTS if not ok)
    print("\n=== SUMMARY ===")
    print(f"{len(RESULTS) - n_fail}/{len(RESULTS)} checks passed.")
    if n_fail:
        print("FAILURES:")
        for sec, name, ok, det in RESULTS:
            if not ok:
                print(f"  - [{sec}] {name}: {det}")
        print("\nDo NOT ship until every mismatch is explained or the letter is corrected.")
    else:
        print("ALL CHECKS PASSED -- letter numbers reproduce from raw data.")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
