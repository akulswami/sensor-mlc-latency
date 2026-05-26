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

VANILLA_BLOCK_RANGES = PRIMARY_VANILLA_BLOCKS | EXPERIMENTAL_VANILLA_BLOCKS
CHRT_BLOCK_RANGES = PRIMARY_CHRT_BLOCKS | EXPERIMENTAL_CHRT_BLOCKS

def _block_campaign(bid):
    """Return 'primary' or 'experimental' for a given block ID."""
    if bid in PRIMARY_VANILLA_BLOCKS or bid in PRIMARY_CHRT_BLOCKS:
        return "primary"
    if bid in EXPERIMENTAL_VANILLA_BLOCKS or bid in EXPERIMENTAL_CHRT_BLOCKS:
        return "experimental"
    return "unknown"


def block_to_cell(block_name):
    """Parse 'block-{id}-{pipeline}-{condition}-btest' into a 4-tuple."""
    if not block_name.startswith("block-") or not block_name.endswith("-btest"):
        return None
    body = block_name[len("block-"):-len("-btest")]
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
    parser.add_argument("--include-experimental", choices=["primary", "all"],
                        default="primary",
                        help="primary (default): include only the planned 2026-05-25 "
                             "btest campaign blocks (301-312, 402-407, 601-618). "
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

    for block_dir in sorted(data_base.glob("block-*-btest")):
        cell = block_to_cell(block_dir.name)
        if cell is None:
            skipped.append((block_dir.name, "could not parse name"))
            continue
        bid, pipeline, condition, scheduling, campaign = cell
        if include_experimental != "all" and campaign != "primary":
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
          "restructure-validation (200-202, 401), and chrt+taskset smoke (501-502) "
          "are EXCLUDED.")
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
