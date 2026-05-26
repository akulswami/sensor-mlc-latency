"""Combined latency + energy analysis across the v7.5 latency-experiment campaign.

Reads tegrastats.log + trials.csv from every
data/training/latency-experiment/block-*-btest/ directory and produces per-cell
summary statistics across pipeline x condition x scheduling regimes.

Run:
    python3 code/analysis/analyze_energy_and_latency.py
        [--data-base data/training/latency-experiment]
        [--out path/to/output.md]

Block-ID conventions (assigned during the 2026-05-25 btest campaigns):
    001-005   pre-restructure smoke (vanilla, mixed conditions)
    101-112   pre-restructure validation (failed MLC i2c-contention cells)
    200-202   restructured-orchestrator validation
    301-312   restructured-orchestrator 12-block run (PRIMARY VANILLA)
    401-407   mlc-binary variant runs (vanilla scheduling)
    501-502   chrt+taskset smoke
    601-618   18-block chrt+taskset campaign

Tegrastats sampling: ~once per 400ms, so a 30s btest block produces ~75 samples
of each rail. Across n=18 blocks per cell, this gives ~1300 samples per cell
for the primary VDD_IN rail.

The on-Jetson INA3221 (bus 1, 0x40, kernel hwmon1) is the source of VDD_IN,
VDD_CPU_GPU_CV, and VDD_SOC reported by tegrastats. There is no separate
sensor-side power monitor in this rig; reported power is the Jetson SoC's
internal rails, which is the correct axis for testing the industry claim
that on-sensor inference "lets the host sleep."
"""

import argparse
import csv
import re
# Local code/analysis/statistics.py shadows stdlib when this script runs
# from this directory. Use importlib.util to load stdlib statistics by path.
import importlib.util as _ilu
_stats_spec = _ilu.spec_from_file_location(
    "_py_stdlib_statistics", "/usr/lib/python3.10/statistics.py")
_pystats = _ilu.module_from_spec(_stats_spec)
_stats_spec.loader.exec_module(_pystats)
mean = _pystats.mean
median = _pystats.median
stdev = _pystats.stdev
import sys
from collections import defaultdict
from pathlib import Path


# Block IDs by campaign. The 2026-05-25 btest campaigns are the only ones
# that should be aggregated for inference; pre-restructure blocks (001-005),
# pre-restructure validation (101-112), and validation/smoke runs (200-202,
# 401, 501-502) had different orchestrator behavior and should be excluded
# from the primary analysis or tagged separately.
PRIMARY_VANILLA_BLOCKS = set(range(301, 313)) | set(range(402, 408))  # 301-312, 402-407
PRIMARY_CHRT_BLOCKS = set(range(601, 619))  # 601-618
EXPERIMENTAL_VANILLA_BLOCKS = (
    set(range(1, 6))         # pre-restructure smoke
    | set(range(101, 113))   # pre-restructure validation (failed MLC cells)
    | set(range(200, 203))   # restructure validation
    | {401}                  # mlc-binary smoke validation
)
EXPERIMENTAL_CHRT_BLOCKS = {501, 502}  # chrt+taskset smoke

# 2026-05-25/26 long-duration smoke blocks. These are 1800-second blocks
# captured to validate the rig under sustained load and to diagnose the
# energy-axis methodology. Block 700 was the first 30-min run; subsequent
# blocks systematically tested the apples-to-apples energy comparison
# under jetson_clocks-ON conditions (nvpmodel 25W mode).
#
# Critical caveat: jetson_clocks state varied across these blocks due to
# nvpmodel reasserting MIN_FREQ. Empirical jetson_clocks effectiveness
# (from tegrastats CPU-freq fields, 0% of samples below 1700 MHz means
# jc was effective; otherwise it was defeated by nvpmodel):
#   b700 mlc i2c-contention: jc EFFECTIVE (0% below max)
#   b701 host idle:          jc DEFEATED  (~50% below max)
#   b702 mlc idle:           jc EFFECTIVE
#   b703 host idle:          jc EFFECTIVE
LONG_DURATION_BLOCKS = {700, 701, 702, 703}

VANILLA_BLOCK_RANGES = PRIMARY_VANILLA_BLOCKS | EXPERIMENTAL_VANILLA_BLOCKS | LONG_DURATION_BLOCKS
CHRT_BLOCK_RANGES = PRIMARY_CHRT_BLOCKS | EXPERIMENTAL_CHRT_BLOCKS

def _block_campaign(bid):
    """Return 'primary', 'experimental', or 'long-duration' for a given block ID."""
    if bid in PRIMARY_VANILLA_BLOCKS or bid in PRIMARY_CHRT_BLOCKS:
        return "primary"
    if bid in LONG_DURATION_BLOCKS:
        return "long-duration"
    if bid in EXPERIMENTAL_VANILLA_BLOCKS or bid in EXPERIMENTAL_CHRT_BLOCKS:
        return "experimental"
    return "unknown"


def block_to_cell(block_name):
    """Parse 'block-{id}-{pipeline}-{condition}[-btest]' into a 5-tuple.

    The '-btest' suffix marks 30-second exploration blocks. Long-duration
    blocks (e.g. 700-703) omit the suffix.
    """
    if not block_name.startswith("block-"):
        return None
    if block_name.endswith("-btest"):
        body = block_name[len("block-"):-len("-btest")]
    else:
        body = block_name[len("block-"):]
    parts = body.split("-")
    if len(parts) < 3:
        return None
    try:
        bid = int(parts[0])
    except ValueError:
        return None

    if bid in CHRT_BLOCK_RANGES:
        scheduling = "chrt+taskset"
    elif bid in VANILLA_BLOCK_RANGES:
        scheduling = "vanilla"
    else:
        scheduling = "unknown"

    rest = "-".join(parts[1:])
    if rest.startswith("mlc-binary-"):
        pipeline = "mlc-binary"
        condition = rest[len("mlc-binary-"):]
    elif rest.startswith("mlc-"):
        pipeline = "mlc"
        condition = rest[len("mlc-"):]
    elif rest.startswith("host-"):
        pipeline = "host"
        condition = rest[len("host-"):]
    else:
        return None

    campaign = _block_campaign(bid)
    return bid, pipeline, condition, scheduling, campaign


def parse_tegrastats(path):
    """Yield VDD_IN milliwatt readings (current instantaneous, not the avg field)."""
    if not path.exists():
        return
    pattern = re.compile(r"VDD_IN (\d+)mW")
    for line in path.read_text(errors="ignore").splitlines():
        m = pattern.search(line)
        if m:
            yield int(m.group(1))


def parse_trials(path):
    """Yield included trial latencies (microseconds) from extract_latency_v7 output."""
    if not path.exists():
        return
    with path.open() as f:
        for row in csv.DictReader(f):
            if row.get("included", "").strip().lower() == "true":
                try:
                    yield float(row["latency_us"])
                except (KeyError, ValueError):
                    continue


def summarize(values, unit=""):
    if not values:
        return None
    sorted_v = sorted(values)
    n = len(sorted_v)
    return {
        "n": n,
        "min": sorted_v[0],
        "p25": sorted_v[max(0, int(0.25 * n) - 1)],
        "median": sorted_v[n // 2],
        "p75": sorted_v[min(n - 1, int(0.75 * n))],
        "max": sorted_v[-1],
        "mean": mean(sorted_v),
        "sd": stdev(sorted_v) if n > 1 else 0.0,
    }


def fmt_row(label, lat_stats, eng_stats, label_width=42):
    def fmt_stat(s, fmt):
        return fmt.format(s) if s is not None else "    -"
    parts = [label.ljust(label_width)]
    if lat_stats:
        parts.append(f"{lat_stats['n']:>4}")
        parts.append(f"{lat_stats['median']:>7.0f}")
        parts.append(f"{lat_stats['sd']:>6.0f}")
    else:
        parts.extend(["   -", "      -", "     -"])
    if eng_stats:
        parts.append(f"{eng_stats['n']:>5}")
        parts.append(f"{eng_stats['mean']:>8.0f}")
        parts.append(f"{eng_stats['sd']:>5.0f}")
    else:
        parts.extend(["    -", "       -", "    -"])
    return "  ".join(parts)


def main():
    # Declared here so the parser-loop function-scope variable is in scope
    # for the block-processing loop below.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-base", default="data/training/latency-experiment")
    parser.add_argument("--include-experimental", choices=["primary", "long-duration", "all"],
                        default="primary",
                        help="primary (default): only the planned 2026-05-25 btest campaign blocks "
                             "(301-312, 402-407, 601-618). "
                             "long-duration: also include the 2026-05-25/26 30-min smoke blocks "
                             "(700-703). "
                             "all: include pre-restructure smoke + validation blocks too.")
    parser.add_argument("--out", default=None,
                        help="Path to write markdown analysis output (default: stdout)")
    args = parser.parse_args()
    include_experimental = args.include_experimental

    data_base = Path(args.data_base)
    if not data_base.exists():
        sys.exit(f"data base not found: {data_base}")

    # Cell key -> {"latency": [...], "energy_mw": [...], "blocks": [...]}
    cells = defaultdict(lambda: {"latency": [], "energy_mw": [], "blocks": []})
    skipped = []

    for block_dir in sorted(data_base.glob("block-*")):
        cell = block_to_cell(block_dir.name)
        if cell is None:
            skipped.append((block_dir.name, "could not parse name"))
            continue
        bid, pipeline, condition, scheduling, campaign = cell
        if include_experimental == "primary":
            if campaign != "primary":
                continue
        elif include_experimental == "long-duration":
            # Per-cell aggregation: ONLY primary blocks (long-duration is
            # reported per-block separately below, not mixed in).
            if campaign != "primary":
                continue
        elif include_experimental == "all":
            # All blocks contribute to per-cell aggregates EXCEPT long-duration,
            # which is reported per-block.
            if campaign == "long-duration":
                continue
        key = (pipeline, condition, scheduling)
        cells[key]["blocks"].append(bid)
        cells[key]["latency"].extend(parse_trials(block_dir / "trials.csv"))
        cells[key]["energy_mw"].extend(parse_tegrastats(block_dir / "tegrastats.log"))

    # ----- Output -----
    out_lines = []
    p = out_lines.append

    p("# v7.5 Latency + Energy Analysis Output")
    p("")
    p("Auto-generated by `code/analysis/analyze_energy_and_latency.py`.")
    p("Source data: `data/training/latency-experiment/block-*-btest/`")
    p("")
    p("Latency = wire-level D0→D1 microseconds from `trials.csv`, included trials only.")
    p("Energy = INA3221 VDD_IN milliwatts from `tegrastats.log`, instantaneous samples.")
    p("")
    p(f"Mode: `--include-experimental {include_experimental}`. ")
    if include_experimental == "primary":
        p("Includes only the planned campaign blocks: vanilla 301-312 + 402-407, "
          "chrt+taskset 601-618. Pre-restructure smoke (001-005, 101-112), "
          "restructure-validation (200-202, 401), chrt+taskset smoke (501-502), and "
          "long-duration smoke (700-703) are EXCLUDED.")
    elif include_experimental == "long-duration":
        p("Includes the planned campaign blocks AND the 2026-05-25/26 30-min "
          "long-duration smoke blocks (700-703). The long-duration blocks were "
          "captured to validate the rig under sustained load and to investigate "
          "the energy-axis methodology. NOTE: jetson_clocks effectiveness varied "
          "across these blocks due to nvpmodel reassertion of MIN_FREQ. b700, "
          "b702, b703 had jetson_clocks effective throughout; b701 did not. "
          "See CAMPAIGN_SUMMARY.md \"Long-duration smoke findings\" for the "
          "apples-to-apples comparison.")
    else:
        p("Includes ALL blocks under the data base, including pre-restructure "
          "and smoke/validation blocks. Per-cell averages may mix orchestrator "
          "versions.")
    p("")
    p("## Per-cell summary")
    p("")
    p("```")
    header = "Cell".ljust(42) + "  " + "  ".join([
        "n_lat".rjust(4), "med_us".rjust(7), "sd_us".rjust(6),
        "n_eng".rjust(5), "mean_mW".rjust(8), "sd_mW".rjust(5),
    ])
    p(header)
    p("-" * len(header))

    pipeline_order = ["host", "mlc-binary", "mlc"]
    condition_order = ["idle", "i2c-contention", "stress"]
    scheduling_order = ["vanilla", "chrt+taskset"]

    for scheduling in scheduling_order:
        any_in_scheduling = any(
            (pipeline, condition, scheduling) in cells
            for pipeline in pipeline_order
            for condition in condition_order
        )
        if not any_in_scheduling:
            continue
        p("")
        p(f"--- {scheduling} scheduling ---")
        for pipeline in pipeline_order:
            for condition in condition_order:
                key = (pipeline, condition, scheduling)
                if key not in cells:
                    continue
                lat_stats = summarize(cells[key]["latency"])
                eng_stats = summarize(cells[key]["energy_mw"])
                label = f"{pipeline:11} {condition}"
                p(fmt_row(label, lat_stats, eng_stats))

    p("```")
    p("")

    # ----- Cross-cell comparisons -----
    p("## Energy: condition delta per pipeline (vanilla scheduling)")
    p("")
    for pipeline in pipeline_order:
        idle = cells.get((pipeline, "idle", "vanilla"), {"energy_mw": []})["energy_mw"]
        cont = cells.get((pipeline, "i2c-contention", "vanilla"), {"energy_mw": []})["energy_mw"]
        if idle and cont:
            idle_mean = mean(idle)
            cont_mean = mean(cont)
            delta = cont_mean - idle_mean
            pct = 100.0 * delta / idle_mean
            p(f"- **{pipeline}**: idle={idle_mean:.0f} mW (n={len(idle)}), "
              f"i2c-contention={cont_mean:.0f} mW (n={len(cont)}), "
              f"Δ=+{delta:.0f} mW ({pct:+.1f}%)")
    p("")

    p("## Latency: condition delta per pipeline (vanilla scheduling)")
    p("")
    for pipeline in pipeline_order:
        idle = cells.get((pipeline, "idle", "vanilla"), {"latency": []})["latency"]
        cont = cells.get((pipeline, "i2c-contention", "vanilla"), {"latency": []})["latency"]
        if idle and cont:
            idle_med = median(idle)
            cont_med = median(cont)
            delta = cont_med - idle_med
            pct = 100.0 * delta / idle_med
            p(f"- **{pipeline}**: idle={idle_med:.0f} µs (n={len(idle)}), "
              f"i2c-contention={cont_med:.0f} µs (n={len(cont)}), "
              f"Δ=+{delta:.0f} µs ({pct:+.1f}%)")
    p("")

    p("## Pipeline ordering at idle (vanilla scheduling)")
    p("")
    p("| Pipeline | Latency median (µs) | Energy mean (mW) |")
    p("|---|---|---|")
    for pipeline in pipeline_order:
        lat = cells.get((pipeline, "idle", "vanilla"), {"latency": []})["latency"]
        eng = cells.get((pipeline, "idle", "vanilla"), {"energy_mw": []})["energy_mw"]
        if lat and eng:
            p(f"| {pipeline} | {median(lat):.0f} | {mean(eng):.0f} |")
    p("")
    p("## Pipeline ordering under I²C contention (vanilla scheduling)")
    p("")
    p("| Pipeline | Latency median (µs) | Energy mean (mW) |")
    p("|---|---|---|")
    for pipeline in pipeline_order:
        lat = cells.get((pipeline, "i2c-contention", "vanilla"), {"latency": []})["latency"]
        eng = cells.get((pipeline, "i2c-contention", "vanilla"), {"energy_mw": []})["energy_mw"]
        if lat and eng:
            p(f"| {pipeline} | {median(lat):.0f} | {mean(eng):.0f} |")
    p("")

    p("## chrt+taskset (RT scheduling) effect")
    p("")
    p("| Cell | Latency median (vanilla→chrt) | Energy mean (vanilla→chrt) |")
    p("|---|---|---|")
    for pipeline in pipeline_order:
        for condition in ["idle", "i2c-contention"]:
            v_lat = cells.get((pipeline, condition, "vanilla"), {"latency": []})["latency"]
            c_lat = cells.get((pipeline, condition, "chrt+taskset"), {"latency": []})["latency"]
            v_eng = cells.get((pipeline, condition, "vanilla"), {"energy_mw": []})["energy_mw"]
            c_eng = cells.get((pipeline, condition, "chrt+taskset"), {"energy_mw": []})["energy_mw"]
            if v_lat and c_lat and v_eng and c_eng:
                p(f"| {pipeline} {condition} | "
                  f"{median(v_lat):.0f} → {median(c_lat):.0f} µs | "
                  f"{mean(v_eng):.0f} → {mean(c_eng):.0f} mW |")
    p("")

    # Long-duration smoke per-block table (each block reported individually
    # because mixing btest n=18 cells with long-duration n=316+ cells in the
    # same aggregate cell would be a category error: they were collected at
    # different durations and under different jetson_clocks states).
    if include_experimental in ("long-duration", "all"):
        ld_blocks_with_data = []
        for block_dir in sorted(data_base.glob("block-*")):
            cell = block_to_cell(block_dir.name)
            if cell is None:
                continue
            bid, pipeline, condition, scheduling, campaign = cell
            if campaign != "long-duration":
                continue
            # Read per-block data (not cell-aggregated)
            lats = list(parse_trials(block_dir / "trials.csv"))
            engs = list(parse_tegrastats(block_dir / "tegrastats.log"))
            # Read jc effectiveness from tegrastats (% samples with all CPU freqs >= 1700 MHz)
            import re
            jc_effective = None
            try:
                content = (block_dir / "tegrastats.log").read_text()
                n_total = 0
                n_below = 0
                for line in content.splitlines():
                    m = re.search(r"CPU \[([^\]]+)\]", line)
                    if m:
                        for entry in m.group(1).split(","):
                            f = re.search(r"@(\d+)", entry)
                            if f:
                                n_total += 1
                                if int(f.group(1)) < 1700:
                                    n_below += 1
                if n_total > 0:
                    jc_effective = 100.0 * (n_total - n_below) / n_total
            except Exception:
                pass
            ld_blocks_with_data.append((bid, pipeline, condition, lats, engs, jc_effective))

        if ld_blocks_with_data:
            p("## Long-duration smoke per-block (each block reported individually)")
            p("")
            p("These are 30-minute blocks captured to investigate the energy-axis "
              "methodology. They are reported per-block (not aggregated) because "
              "the jetson_clocks state varied across blocks; mixing them with "
              "btest-cell aggregates would be a category error.")
            p("")
            p("jc_eff = % of tegrastats CPU-freq samples at >= 1700 MHz (jc effective).")
            p("100% means jetson_clocks held throughout the block; lower means "
              "nvpmodel defeated jetson_clocks at points during the block.")
            p("")
            p("| Block | Pipeline | Condition | n_lat | lat_med (µs) | n_eng | eng_mean (mW) | eng_sd | jc_eff |")
            p("|------:|----------|----------------|------:|-------------:|------:|--------------:|-------:|-------:|")
            for bid, pipeline, condition, lats, engs, jc_eff in ld_blocks_with_data:
                lat_med = sorted(lats)[len(lats)//2] if lats else None
                eng_mean = sum(engs) / len(engs) if engs else None
                if len(engs) > 1:
                    eng_sd_val = (sum((e - eng_mean)**2 for e in engs) / (len(engs) - 1)) ** 0.5
                else:
                    eng_sd_val = 0
                lat_med_s = f"{lat_med:.0f}" if lat_med is not None else "-"
                eng_mean_s = f"{eng_mean:.0f}" if eng_mean is not None else "-"
                jc_eff_s = f"{jc_eff:.1f}%" if jc_eff is not None else "-"
                p(f"| {bid} | {pipeline} | {condition} | {len(lats)} | {lat_med_s} | "
                  f"{len(engs)} | {eng_mean_s} | {eng_sd_val:.0f} | {jc_eff_s} |")
            p("")

            # Apples-to-apples block (both with jc effective, both idle)
            jc_eff_idle = [(b, p_, c, l, e, j) for b, p_, c, l, e, j in ld_blocks_with_data
                          if c == "idle" and j is not None and j >= 99.0]
            if len(jc_eff_idle) >= 2:
                p("### Apples-to-apples: idle blocks with jc_eff ≈ 100%")
                p("")
                for bid, pipeline, condition, lats, engs, jc_eff in jc_eff_idle:
                    eng_mean = sum(engs) / len(engs) if engs else None
                    p(f"- **b{bid} {pipeline} {condition}**: energy mean = "
                      f"{eng_mean:.0f} mW, jc_eff = {jc_eff:.1f}%")
                # Compute the gap
                pipelines = sorted(set(p_ for b, p_, c, l, e, j in jc_eff_idle))
                if "host" in pipelines and "mlc" in pipelines:
                    host_eng = sum(sum(e)/len(e) for b, p_, c, l, e, j in jc_eff_idle if p_ == "host") / sum(1 for b, p_, c, l, e, j in jc_eff_idle if p_ == "host")
                    mlc_eng = sum(sum(e)/len(e) for b, p_, c, l, e, j in jc_eff_idle if p_ == "mlc") / sum(1 for b, p_, c, l, e, j in jc_eff_idle if p_ == "mlc")
                    gap = host_eng - mlc_eng
                    p("")
                    p(f"**Gap (host - mlc, idle, jc-effective): {gap:+.0f} mW.** "
                      f"{'MLC saves' if gap > 50 else 'MLC uses more' if gap < -50 else 'Within noise floor (±50 mW)'}.")
            p("")

    if skipped:
        p("## Skipped blocks")
        p("")
        for name, reason in skipped:
            p(f"- {name}: {reason}")
        p("")

    output = "\n".join(out_lines)
    if args.out:
        Path(args.out).write_text(output)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
