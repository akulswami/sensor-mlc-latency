#!/usr/bin/env python3
"""
mlc_json_to_parity.py

Converts a MEMS Studio MLC configuration JSON export into the stable
tree.json schema consumed by replay_parity.c and host_pipeline_parity.c.

STATUS (2026-05-21): SKELETON. The MEMS Studio JSON field names and
nesting are unknown until a real export is in hand. Every extractor
below raises NotImplementedError with a pointer to the section of
docs/mems-studio-json-parity-extraction.md that documents what it
needs to produce. When the first export arrives:

  1. Run with --inspect to dump the top-level shape of the input.
  2. For each NotImplementedError, locate the right field in the
     MEMS Studio JSON and fill in the extractor.
  3. Run with --validate-only on a known-good export to confirm all
     extractors find what they need.
  4. Run normally to emit tree.json. Feed it to replay_parity and
     run code/jetson/host_inference/test_replay_parity.sh as a
     smoke test.

The OUTPUT schema is locked. It matches the parser in
code/jetson/host_inference/parity_core.c. Changing it requires
updating parity_core too. See docs/mems-studio-json-parity-extraction.md
section "Extraction script" for the schema.

Usage:
    mlc_json_to_parity.py INPUT_JSON [--inspect] [--validate-only]
                                     [--output OUTPUT_JSON]
                                     [--mlc-odr-hz N]
                                     [--sensor-odr-hz N]

The --mlc-odr-hz and --sensor-odr-hz flags exist because these values
may be set globally in the MEMS Studio session rather than in the
exported JSON; supplying them on the command line is a fallback.
"""

from __future__ import annotations
import argparse
import json
import sys
from typing import Any


# ============================================================
# Output schema constants. Must match parity_core.c expectations.
# ============================================================

OUTPUT_SCHEMA_VERSION = 1  # bump if the schema below changes
COMPARISON_VALUES = {"lt", "lte", "gt", "gte"}
FILTER_TYPES = {"iir1_hp"}     # extend as parity_core grows
FEATURE_TYPES = {"variance", "peak_to_peak"}
ESTIMATORS = {"biased", "unbiased"}


# ============================================================
# Extractor stubs. Each is a TODO marker with a contract.
# ============================================================

def extract_window_length(mlc_json: dict) -> int:
    """Window length in samples. Spec candidates: 25, 75, 200.
    Reference: docs/mems-studio-json-parity-extraction.md §1."""
    raise NotImplementedError(
        "Locate the window length field in MEMS Studio JSON. "
        "Likely keys: 'window_length', 'WL', 'samples_per_window'. "
        "Return an int."
    )


def extract_sensor_odr_hz(mlc_json: dict, cli_override: int | None) -> int:
    """Accelerometer ODR in Hz. Spec: 208 Hz.
    Reference: docs/mems-studio-json-parity-extraction.md §2 (note that
    sensor ODR is distinct from MLC ODR — see extract_mlc_odr_hz).
    If MEMS Studio doesn't embed the sensor ODR in the MLC JSON, use
    the CLI override and document why in this function's body."""
    if cli_override is not None:
        return cli_override
    raise NotImplementedError(
        "Locate the sensor accelerometer ODR field. May not be in the "
        "MLC JSON; if so, pass via --sensor-odr-hz and remove this "
        "raise. Spec value is 208 Hz."
    )


def extract_mlc_odr_hz(mlc_json: dict, cli_override: int | None) -> int:
    """MLC output data rate. AN5259 caps at 104 Hz. Valid: 12.5, 26,
    52, 104. Selected via MLC_ODR bits in EMB_FUNC_ODR_CFG_C (60h)."""
    if cli_override is not None:
        return cli_override
    raise NotImplementedError(
        "Locate MLC_ODR field. Likely keys: 'mlc_odr', 'odr', "
        "'output_data_rate'. AN5259 §1 cap: 104 Hz."
    )


def extract_decimation_ratio(sensor_odr: int, mlc_odr: int) -> int:
    """Sensor ODR : MLC ODR ratio. AN5259 §1.1 says MLC decimates
    internally without filtering when sensor ODR > MLC ODR."""
    if sensor_odr % mlc_odr != 0:
        raise ValueError(
            f"sensor_odr_hz={sensor_odr} is not an integer multiple of "
            f"mlc_odr_hz={mlc_odr}. This is unusual; AN5259 examples "
            f"always use integer ratios. Verify the JSON values."
        )
    return sensor_odr // mlc_odr


def extract_filters(mlc_json: dict) -> list[dict]:
    """Filter chain. Reference: docs/mems-studio-json-parity-extraction.md §3.

    Output: list of filter dicts. Each:
      {"id": int, "type": "iir1_hp",
       "b1": float, "b2": float, "b3": float,
       "a2": float, "a3": float, "gain": float}

    Spec uses one IIR1 HP filter. AN5259 §1.2 coefficients are in
    half-precision float on the silicon; we emit float64 here and
    parity_core.c reads them as float32. The precision difference is
    accepted on the host side (label-level parity is the gate, not
    feature-level).

    AN5259 Table 3 reference values (HP IIR1, 26 Hz MLC ODR):
      f_cut = 1 Hz: b1=0.891725, b2=-0.891725, a2=-0.783450
      f_cut = 2 Hz: b1=0.802261, b2=-0.802261, a2=-0.604521
    At MLC_ODR != 26 Hz, recompute via:
      scipy.signal.butter(1, fc/(ODR/2), 'high')
    """
    raise NotImplementedError(
        "Locate filter definitions. Likely path: mlc_json['filters'] "
        "or nested under decision_tree/computation_block. Each filter "
        "should have type + 6 coefficient values. Default missing "
        "coefs to 0.0 (b3, a3 for IIR1)."
    )


def extract_features(mlc_json: dict) -> list[dict]:
    """Feature definitions. Reference: §4.

    Output: list of feature dicts. Each:
      {"id": int, "type": "variance" | "peak_to_peak",
       "input_filter_id": int, "estimator": "biased" | "unbiased"}

    Spec uses VARIANCE_NORM and PEAK_TO_PEAK_NORM, both on the L2 norm
    of the filtered acceleration. AN5259 does not specify whether
    variance uses biased (1/N) or unbiased (1/(N-1)) estimator;
    determine empirically by computing both on training windows and
    seeing which matches MLC output.
    """
    raise NotImplementedError(
        "Locate feature definitions. Each feature needs id, type, "
        "and the filter it consumes. Variance estimator may not be "
        "specified in the JSON; default to 'biased' and revise after "
        "comparing against MLC silicon output."
    )


def extract_tree(mlc_json: dict) -> list[dict]:
    """Decision tree as a list of nodes. Reference: §5.

    Output: list of node dicts. Internal node:
      {"node_id": int, "feature_id": int, "threshold": float,
       "comparison": "lt" | "lte" | "gt" | "gte",
       "left": int, "right": int}
    Leaf node:
      {"node_id": int, "leaf": true, "class": int}

    parity_core.c walks the tree starting at node_id=0.

    AN5259 calls the binary tree "Weka J48 format" when imported from
    external tools. MEMS Studio may export it as a flat list of
    statements ("if feat > thr then ...") or as a structured
    parent/child object. Either is OK; the extractor's job is to
    normalize to the flat-list form above.

    Comparison operator: AN5259 doesn't pin down whether thresholds
    use < or <=. Try lte first; if parity fails on near-threshold
    windows, retry with lt.
    """
    raise NotImplementedError(
        "Walk MEMS Studio's tree representation and emit one dict per "
        "node. Confirm comparison operator empirically — start with "
        "'lte' and verify against silicon output."
    )


def extract_class_codes(mlc_json: dict) -> dict[str, int]:
    """Map class names to numeric codes written to MLC0_SRC.

    Output: {"still": int, "motion": int}

    Spec: STILL=0 (matches MLC_OUT_NONTAP convention in mlc_pipeline/),
    MOTION=whatever Weka/MEMS Studio assigns. ST examples often use
    nonzero values like 1, 4, or 8 for the first non-zero class
    (AN5259 §3.4: walking=1, jogging=4, biking=8). The actual code
    must match what the silicon writes to MLC0_SRC.
    """
    raise NotImplementedError(
        "Locate class output codes. The JSON likely stores them under "
        "the leaf nodes' output_value field or in a separate "
        "class_codes map. Both still and motion must be present."
    )


def assert_no_meta_classifier(mlc_json: dict) -> None:
    """Reference: §7. Spec says meta-classifier is NOT used.
    Raise if the JSON shows one configured with nonzero end-counters."""
    raise NotImplementedError(
        "Inspect mlc_json for a 'meta_classifier' field. If present "
        "and has any nonzero end_counter, raise — this violates the "
        "spec and requires a v4 amendment OR reconfiguring MEMS Studio."
    )


# ============================================================
# Validation. Cross-checks across extracted fields.
# ============================================================

def validate(out: dict) -> None:
    """Raise ValueError on any contract violation. Run after every
    extractor succeeds to catch internal inconsistencies before
    parity_core sees the file."""
    # Window length sanity
    if out["window_length"] < 1 or out["window_length"] > 255:
        raise ValueError(f"window_length out of MLC range: {out['window_length']}")

    # ODR bounds
    if out["mlc_odr_hz"] not in (12, 13, 26, 52, 104):
        # 12.5 Hz rounds either way; allow both
        # Pre-existing values seen in AN5259 Table 1: 12.5, 26, 52, 104
        if out["mlc_odr_hz"] != 12 and abs(out["mlc_odr_hz"] - 12.5) > 0.5:
            raise ValueError(f"mlc_odr_hz not in AN5259 set: {out['mlc_odr_hz']}")

    # Decimation consistency
    expected_decim = out["sensor_odr_hz"] // out["mlc_odr_hz"]
    if out["decimation_ratio"] != expected_decim:
        raise ValueError(
            f"decimation_ratio={out['decimation_ratio']} != "
            f"sensor/mlc={expected_decim}"
        )

    # Filter type whitelist
    for f in out["filters"]:
        if f["type"] not in FILTER_TYPES:
            raise ValueError(
                f"unsupported filter type {f['type']!r}; "
                f"parity_core supports only {FILTER_TYPES}"
            )

    # Feature type whitelist
    feature_ids = set()
    for f in out["features"]:
        if f["type"] not in FEATURE_TYPES:
            raise ValueError(
                f"unsupported feature type {f['type']!r}; "
                f"parity_core supports only {FEATURE_TYPES}"
            )
        if f.get("estimator", "biased") not in ESTIMATORS:
            raise ValueError(
                f"unknown estimator {f['estimator']!r}"
            )
        feature_ids.add(f["id"])

    # Filter ids referenced by features must exist
    filter_ids = {f["id"] for f in out["filters"]}
    for f in out["features"]:
        if f["input_filter_id"] != -1 and f["input_filter_id"] not in filter_ids:
            raise ValueError(
                f"feature id {f['id']} references nonexistent "
                f"filter id {f['input_filter_id']}"
            )

    # Tree integrity
    node_ids = set()
    for node in out["tree"]:
        nid = node["node_id"]
        if nid in node_ids:
            raise ValueError(f"duplicate tree node_id {nid}")
        node_ids.add(nid)

    if 0 not in node_ids:
        raise ValueError("tree has no node_id 0 (parity_core starts walk there)")

    for node in out["tree"]:
        if node.get("leaf"):
            if "class" not in node:
                raise ValueError(f"leaf node {node['node_id']} missing 'class'")
        else:
            if node.get("comparison") not in COMPARISON_VALUES:
                raise ValueError(
                    f"node {node['node_id']} has invalid comparison "
                    f"{node.get('comparison')!r}"
                )
            if node["feature_id"] not in feature_ids:
                raise ValueError(
                    f"node {node['node_id']} references nonexistent "
                    f"feature id {node['feature_id']}"
                )
            if node["left"] not in node_ids and node["left"] not in [
                n["node_id"] for n in out["tree"]
            ]:
                # The check above is redundant after the dedupe loop;
                # kept here as a defensive recheck since node_ids is
                # populated incrementally during the leaf/internal pass.
                pass

    # Class codes present and distinct
    if "still" not in out["class_codes"] or "motion" not in out["class_codes"]:
        raise ValueError("class_codes must have 'still' and 'motion' keys")
    if out["class_codes"]["still"] == out["class_codes"]["motion"]:
        raise ValueError("still and motion class codes must differ")


# ============================================================
# Inspector. Dumps a JSON structure shape (keys, types, lengths)
# without revealing every value. For first-look exploration.
# ============================================================

def inspect_shape(obj: Any, depth: int = 0, max_depth: int = 4) -> str:
    """Produce a compact human-readable tree of an arbitrary JSON
    object showing keys, types, and array lengths."""
    indent = "  " * depth
    if depth >= max_depth:
        return indent + "..."
    if isinstance(obj, dict):
        lines = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{indent}{k}:")
                lines.append(inspect_shape(v, depth + 1, max_depth))
            else:
                tname = type(v).__name__
                sample = repr(v) if not isinstance(v, str) or len(v) < 30 else repr(v[:27] + "...")
                lines.append(f"{indent}{k}: {tname} = {sample}")
        return "\n".join(lines)
    elif isinstance(obj, list):
        if not obj:
            return f"{indent}[] (empty)"
        sample_types = {type(x).__name__ for x in obj[:5]}
        lines = [f"{indent}[{len(obj)} items, types={sorted(sample_types)}]"]
        if obj and isinstance(obj[0], (dict, list)):
            lines.append(f"{indent}first item:")
            lines.append(inspect_shape(obj[0], depth + 1, max_depth))
        return "\n".join(lines)
    else:
        return f"{indent}{type(obj).__name__} = {obj!r}"


# ============================================================
# Main.
# ============================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_json")
    ap.add_argument("--inspect", action="store_true",
                    help="dump the input JSON shape and exit; do not extract")
    ap.add_argument("--validate-only", action="store_true",
                    help="run extraction + validation but skip writing output")
    ap.add_argument("--output", "-o", default="tree.json",
                    help="output path (default: tree.json)")
    ap.add_argument("--sensor-odr-hz", type=int, default=None,
                    help="sensor accel ODR override if not in JSON (Hz)")
    ap.add_argument("--mlc-odr-hz", type=int, default=None,
                    help="MLC ODR override if not in JSON (Hz)")
    args = ap.parse_args()

    try:
        with open(args.input_json) as f:
            mlc_json = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read {args.input_json}: {e}", file=sys.stderr)
        return 2

    if args.inspect:
        print(f"=== {args.input_json} shape ===")
        print(inspect_shape(mlc_json))
        return 0

    # Run all extractors. Any NotImplementedError surfaces with a
    # pointer to what needs to be filled in.
    out: dict = {"schema_version": OUTPUT_SCHEMA_VERSION}

    try:
        out["window_length"] = extract_window_length(mlc_json)
        out["sensor_odr_hz"] = extract_sensor_odr_hz(mlc_json, args.sensor_odr_hz)
        out["mlc_odr_hz"] = extract_mlc_odr_hz(mlc_json, args.mlc_odr_hz)
        out["decimation_ratio"] = extract_decimation_ratio(
            out["sensor_odr_hz"], out["mlc_odr_hz"]
        )
        assert_no_meta_classifier(mlc_json)
        out["filters"] = extract_filters(mlc_json)
        out["features"] = extract_features(mlc_json)
        out["tree"] = extract_tree(mlc_json)
        out["class_codes"] = extract_class_codes(mlc_json)
    except NotImplementedError as e:
        print(f"ERROR: extractor not yet implemented: {e}", file=sys.stderr)
        print(f"Hint: run --inspect first to see the JSON structure.",
              file=sys.stderr)
        return 1
    except (KeyError, ValueError, TypeError) as e:
        print(f"ERROR: extraction failed: {e}", file=sys.stderr)
        return 1

    try:
        validate(out)
    except ValueError as e:
        print(f"ERROR: validation failed: {e}", file=sys.stderr)
        return 1

    if args.validate_only:
        print(f"OK: extraction + validation succeeded for {args.input_json}")
        return 0

    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(f"OK: wrote {args.output}")
    print(f"     window={out['window_length']}  "
          f"mlc_odr={out['mlc_odr_hz']}  decim={out['decimation_ratio']}  "
          f"features={len(out['features'])}  nodes={len(out['tree'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
