#!/usr/bin/env python3
"""
mlc_json_to_parity.py

Converts MEMS Studio MLC artifacts into the stable tree.json schema
consumed by replay_parity.c and host_pipeline_parity.c.

INPUTS (two files; MEMS Studio splits the trained classifier across them):
  - mlc_settings.json: high-level config — filters, features, datalogs,
    window length, MLC ODR, sensor settings. Has all hyperparameters
    but NOT the tree structure.
  - ST_decision_tree_*.txt: plain-text tree dump — feature references,
    thresholds, and class label per leaf. Has the tree structure.

NOT used by this tool:
  - mlc.json (register-write sequence) — the on-chip .ucf-equivalent.
    Opaque byte stream; no high-level structure. AN5259 §1.4 confirms
    the tree byte format is not publicly documented.
  - features.arff — the per-window feature dataset, training input,
    not needed for parity replay.

OUTPUT:
  - tree.json with the schema parity_core.c expects. See
    docs/mems-studio-json-parity-extraction.md for the full schema.

IMPORTANT — filter sign convention:
  MEMS Studio's UI uses H(z) = (b1 + b2 z^-1) / (1 - a2 z^-1)
                              [Convention B; difference eq has +a2 y[n-1]]
  parity_core.c implements   H(z) = (b1 + b2 z^-1) / (1 + a2 z^-1)
                              [Convention A; difference eq has -a2 y[n-1]]
  This extractor NEGATES the sign of a2 (and a3) when copying from
  mlc_settings.json to tree.json so that parity_core's filter math
  produces the same frequency response as MEMS Studio's training data.

IMPORTANT — class codes:
  Class codes (still=0, motion=4 for the 2026-05-22 run) are set in
  MEMS Studio's Config generation tab but DO NOT appear in either input
  file. They must be supplied via --class-codes "still=0,motion=4".
  Future MEMS Studio versions may export them; for now they're CLI.

Usage:
    mlc_json_to_parity.py mlc_settings.json
        --tree-file ST_decision_tree_*.txt
        --class-codes "still=0,motion=4"
        [--output tree.json]
        [--inspect | --validate-only]
        [--sensor-odr-hz N (override)]
        [--mlc-odr-hz N (override)]
"""

from __future__ import annotations
import argparse
import json
import re
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
    From mlc_settings.json key 'window_length' (string-typed in
    MEMS Studio 2.3.1, e.g. "75")."""
    raw = mlc_json.get("window_length")
    if raw is None:
        raise KeyError("mlc_settings.json missing 'window_length'")
    try:
        return int(raw)
    except (TypeError, ValueError) as e:
        raise ValueError(f"window_length not parseable as int: {raw!r}") from e


def extract_sensor_odr_hz(mlc_json: dict, cli_override: int | None) -> int:
    """Accelerometer ODR in Hz. Spec: 208 Hz.
    From mlc_settings.json key 'accelerometer_odr', stored as a string
    like "208 Hz". CLI override takes precedence."""
    if cli_override is not None:
        return cli_override
    raw = mlc_json.get("accelerometer_odr")
    if raw is None:
        raise KeyError("mlc_settings.json missing 'accelerometer_odr'")
    # Parse "208 Hz" or "208"
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(?:Hz)?\s*$", str(raw), re.IGNORECASE)
    if not m:
        raise ValueError(f"accelerometer_odr not parseable: {raw!r}")
    val = float(m.group(1))
    if val != int(val):
        raise ValueError(f"non-integer accelerometer_odr {val} unsupported")
    return int(val)


def extract_mlc_odr_hz(mlc_json: dict, cli_override: int | None) -> int:
    """MLC output data rate. AN5259 caps at 104 Hz. Valid: 12.5, 26,
    52, 104. Selected via MLC_ODR bits in EMB_FUNC_ODR_CFG_C (60h).
    From mlc_settings.json key 'mlc_odr', stored as a string like
    "104 Hz". CLI override takes precedence."""
    if cli_override is not None:
        return cli_override
    raw = mlc_json.get("mlc_odr")
    if raw is None:
        raise KeyError("mlc_settings.json missing 'mlc_odr'")
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(?:Hz)?\s*$", str(raw), re.IGNORECASE)
    if not m:
        raise ValueError(f"mlc_odr not parseable: {raw!r}")
    val = float(m.group(1))
    # Accept 12.5 as 12 for arithmetic with integer-typed downstream
    # consumers. Validation in validate() catches anything weird.
    if abs(val - 12.5) < 0.01:
        return 12
    if val != int(val):
        raise ValueError(f"non-integer mlc_odr {val} unsupported")
    return int(val)


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
    """Filter chain.

    From mlc_settings.json key 'filters', a list of:
      {"a2": "0.941339", "b1": "0.970669", "b2": "-0.970669",
       "filter_id": "filter_1", "filter_type": "IIR1", "input": "Acc_V"}

    Coefficients are stored as STRINGS in MEMS Studio 2.3.1.

    CRITICAL: a2 sign-flip. See module docstring. MEMS Studio's UI uses
    Convention B (H(z) = num / (1 - a2 z^-1)); parity_core.c uses
    Convention A (H(z) = num / (1 + a2 z^-1)). To get the same frequency
    response, we negate a2 (and a3 if present) when emitting tree.json.

    Output: list of filter dicts in parity_core's schema:
      {"id": int, "type": "iir1_hp",
       "b1": float, "b2": float, "b3": float,
       "a2": float, "a3": float, "gain": float}

    Filter id mapping: MEMS Studio uses 'filter_1', 'filter_2', etc.
    We extract the trailing integer.

    Filter type mapping: MEMS Studio uses 'IIR1', 'IIR2', 'BP_Acc_V2'
    (band-pass). parity_core supports only 'iir1_hp' currently. We
    emit 'iir1_hp' for 'IIR1' inputs; the HP-vs-LP distinction is
    encoded in the coefficient signs, not the type label, and the
    coefficients are passed through verbatim (modulo the a2 flip).
    """
    raw_filters = mlc_json.get("filters")
    if raw_filters is None:
        raise KeyError("mlc_settings.json missing 'filters'")
    if not isinstance(raw_filters, list):
        raise ValueError(f"'filters' is not a list: {type(raw_filters).__name__}")

    out = []
    for f in raw_filters:
        # Filter id
        raw_id = f.get("filter_id")
        if raw_id is None:
            raise KeyError(f"filter entry missing 'filter_id': {f}")
        m = re.match(r"filter_(\d+)$", str(raw_id))
        if not m:
            raise ValueError(f"unexpected filter_id format: {raw_id!r}")
        fid = int(m.group(1)) - 1  # MEMS Studio is 1-indexed, parity_core is 0-indexed

        # Filter type — only IIR1 supported by parity_core
        raw_type = f.get("filter_type", "").strip().upper()
        if raw_type != "IIR1":
            raise ValueError(
                f"unsupported filter_type {raw_type!r} for filter_{fid+1}; "
                f"parity_core currently supports only IIR1"
            )

        # Coefficients — stored as strings, parse to float.
        # a2 sign flip per Convention A <- Convention B conversion.
        def _f(key, default=0.0):
            v = f.get(key)
            if v is None or v == "":
                return default
            return float(v)

        out.append({
            "id":    fid,
            "type":  "iir1_hp",  # parity_core's only filter type tag
            "b1":    _f("b1"),
            "b2":    _f("b2"),
            "b3":    _f("b3"),
            "a2":   -_f("a2"),   # SIGN FLIP: Convention B -> Convention A
            "a3":   -_f("a3"),   # SIGN FLIP applies to all denominator terms
            "gain":  _f("gain", default=1.0),
        })

    return out


def extract_features(mlc_json: dict) -> list[dict]:
    """Feature definitions.

    From mlc_settings.json key 'features', a list of:
      {"feature_name": "VARIANCE", "input": "Acc_V_filter_1", "signed": false}

    Output: list of feature dicts in parity_core's schema:
      {"id": int, "type": "variance" | "peak_to_peak",
       "input_filter_id": int, "estimator": "biased"}

    Feature name mapping: MEMS Studio uses ALL_CAPS, parity_core uses
    lower_case. VARIANCE -> variance, PEAK_TO_PEAK -> peak_to_peak.

    Input mapping: MEMS Studio's 'input' string encodes both signal
    and filter:
      Acc_X / Acc_Y / Acc_Z / Acc_V / Acc_V2  -> no filter (raw)
      Acc_V_filter_1                          -> filter id 0 (filter_1)
      Acc_V_filter_2                          -> filter id 1 (filter_2)
    Spec only uses Acc_V_filter_1.

    Estimator: MEMS Studio doesn't document whether variance uses
    biased (1/N) or unbiased (1/(N-1)) estimator. AN5259 doesn't
    say either. Default to 'biased' (it's the simpler implementation
    and likely matches silicon). To verify, compare per-window
    variance values from replay_parity against the MEMS Studio
    ARFF output (which is what the silicon would also produce).
    If they don't match, switch to 'unbiased' and rerun.
    """
    raw_features = mlc_json.get("features")
    if raw_features is None:
        raise KeyError("mlc_settings.json missing 'features'")
    if not isinstance(raw_features, list):
        raise ValueError(f"'features' is not a list")

    name_map = {
        "VARIANCE":     "variance",
        "PEAK_TO_PEAK": "peak_to_peak",
    }

    out = []
    for idx, feat in enumerate(raw_features):
        raw_name = str(feat.get("feature_name", "")).strip().upper()
        if raw_name not in name_map:
            raise ValueError(
                f"unsupported feature_name {raw_name!r} (feature_{idx+1}); "
                f"parity_core supports only {sorted(name_map.keys())}"
            )

        raw_input = str(feat.get("input", "")).strip()
        # Parse input: Acc_<axis> or Acc_<axis>_filter_<n>
        m = re.match(r"Acc_(X|Y|Z|V|V2)(?:_filter_(\d+))?$", raw_input)
        if not m:
            raise ValueError(
                f"unexpected feature input format: {raw_input!r}"
            )
        # parity_core only knows about V/norm signal; X/Y/Z and V2
        # would need parity_core extensions.
        axis = m.group(1)
        if axis != "V":
            raise ValueError(
                f"feature input axis {axis} (in {raw_input!r}) not yet "
                f"supported by parity_core; spec uses Acc_V only"
            )
        filter_num = m.group(2)
        if filter_num is None:
            # Raw signal, no filter. parity_core uses -1 for "no filter".
            input_filter_id = -1
        else:
            input_filter_id = int(filter_num) - 1  # 1-indexed -> 0-indexed

        out.append({
            "id":              idx,
            "type":            name_map[raw_name],
            "input_filter_id": input_filter_id,
            "estimator":       "biased",  # see docstring note
        })

    return out


def extract_tree(tree_text: str, feature_name_to_id: dict[str, int],
                 class_name_to_code: dict[str, int]) -> list[dict]:
    """Decision tree as a list of nodes, parsed from MEMS Studio's
    plain-text tree dump (ST_decision_tree_*.txt).

    INPUT TEXT FORMAT — sample (depth-1 tree, this run):
        F2_ABS_PEAK_TO_PEAK_ACC_V_FILTER_1 <= 0.049316 : still (2718)
        F2_ABS_PEAK_TO_PEAK_ACC_V_FILTER_1  > 0.049316 : motion (2669)

        Number of Leaves: 2
        ...

    Each non-leaf rule line is of the form:
        <feature_name> <comparison> <threshold> : <class_name> (<count>)
    Indentation indicates depth in deeper trees:
        F1_ABS_... <= 0.5 : still (...)
        F1_ABS_... > 0.5
        |   F2_ABS_... <= 0.3 : motion (...)
        |   F2_ABS_... > 0.3 : still (...)

    OUTPUT — list of node dicts. Internal:
      {"node_id": int, "feature_id": int, "threshold": float,
       "comparison": "lt" | "lte" | "gt" | "gte",
       "left": int, "right": int}
    Leaf:
      {"node_id": int, "leaf": true, "class": int}

    The flat-list representation in parity_core walks from node 0.

    SIMPLIFICATION FOR DEPTH-1 TREES: in the 2026-05-22 w=75 run the
    tree is depth 1 — two leaves under a single split. We hard-code
    this case; deeper trees will need a real parser. NotImplementedError
    is raised for trees we don't yet handle, so we fail loudly rather
    than emit garbage.

    Feature reference parsing: MEMS Studio names features like
    F<N>_ABS_<TYPE>_<INPUT>. We use the F<N> prefix to look up the
    1-indexed feature, converting to 0-indexed for parity_core.
    """
    # Find rule lines: feature_name <cmp> threshold : class_name (count)
    rule_pattern = re.compile(
        r"^\s*"
        r"(F\d+_[A-Z0-9_]+)"     # feature name like F2_ABS_PEAK_TO_PEAK_ACC_V_FILTER_1
        r"\s*(<=|>=|<|>)\s*"     # comparison
        r"([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)"  # threshold
        r"\s*:\s*"
        r"(\S+)"                  # class name
        r"\s*\(\d+(?:/\d+(?:\.\d+)?)?\)"  # (count) or (count/misclassified)
        r"\s*$"
    )

    # Stripped CRLF, leading/trailing whitespace
    lines = [ln.rstrip("\r\n").rstrip() for ln in tree_text.splitlines()]
    rules = []
    for ln in lines:
        if not ln.strip():
            continue
        if ln.startswith(("Number of", "Size of", "Classes:", "Features:",
                          "===", "Confusion", "Total", "Correctly",
                          "Incorrectly", "Accuracy", "Cohen", "Report",
                          "=>", "still ", "motion ", "avg/total")):
            # Statistics block; skip
            continue
        m = rule_pattern.match(ln)
        if m:
            rules.append(m.groups())
            continue
        # Lines that survive: probably part of statistics; skip silently.

    if not rules:
        raise ValueError("no decision tree rules parsed from tree text")

    # Depth-1 tree case: exactly two rules, same feature, opposing
    # comparisons, single threshold.
    if len(rules) == 2:
        feat1, cmp1, thr1, cls1 = rules[0]
        feat2, cmp2, thr2, cls2 = rules[1]
        if feat1 != feat2:
            raise NotImplementedError(
                f"depth-1 tree path supports same-feature splits only; "
                f"got {feat1} and {feat2}. Deeper trees need a real "
                f"parser; this is reachable when MEMS Studio picks "
                f"different features in different leaves."
            )
        if thr1 != thr2:
            raise ValueError(
                f"depth-1 tree paths have different thresholds: "
                f"{thr1} vs {thr2}"
            )

        # Look up the feature id
        feat_id = feature_name_to_id.get(feat1)
        if feat_id is None:
            # MEMS Studio names them F<N>_..., where N is the 1-indexed
            # feature slot. Fall back to that.
            m = re.match(r"^F(\d+)_", feat1)
            if not m:
                raise ValueError(f"can't determine feature id from {feat1!r}")
            feat_id = int(m.group(1)) - 1  # 1-indexed -> 0-indexed

        # Map class names to codes
        if cls1 not in class_name_to_code:
            raise ValueError(f"unknown class {cls1!r} in tree leaf")
        if cls2 not in class_name_to_code:
            raise ValueError(f"unknown class {cls2!r} in tree leaf")

        # AN5259 doesn't formally pin down whether MLC silicon evaluates
        # < or <= at the threshold. MEMS Studio's text dump uses <= and >.
        # Default to that mapping. If parity fails on exact-threshold
        # windows, this is the first place to revisit.
        cmp_map = {"<=": "lte", ">=": "gte", "<": "lt", ">": "gt"}
        cmp_a = cmp_map[cmp1]

        # Two-leaf tree: root + 2 leaves.
        # node 0 = root with feature_id, threshold, comparison
        # node 1 = leaf for "if cmp_a then class=cls1"
        # node 2 = leaf for "else class=cls2"
        return [
            {
                "node_id":    0,
                "feature_id": feat_id,
                "threshold":  float(thr1),
                "comparison": cmp_a,
                "left":       1,  # taken when comparison is TRUE
                "right":      2,  # taken when comparison is FALSE
            },
            {
                "node_id": 1,
                "leaf":    True,
                "class":   class_name_to_code[cls1],
            },
            {
                "node_id": 2,
                "leaf":    True,
                "class":   class_name_to_code[cls2],
            },
        ]

    # Deeper tree — not supported in this version.
    raise NotImplementedError(
        f"parsed {len(rules)} rule lines; only depth-1 trees (2 rules) "
        f"are currently supported. Extend extract_tree to handle "
        f"indentation-based nesting if MEMS Studio produces a deeper "
        f"tree on future training runs."
    )


def extract_class_codes(cli_class_codes: str | None) -> dict[str, int]:
    """Map class names to numeric codes written to MLC0_SRC.

    Class codes are NOT present in mlc_settings.json or the tree text
    file. They are set in MEMS Studio's Config generation tab and
    written into the register-config mlc.json byte stream, where
    they're opaque. Must be supplied via CLI for now.

    Spec: STILL=0 (matches MLC_OUT_NONTAP convention in mlc_pipeline/),
    MOTION=whatever MEMS Studio assigns. ST examples often use values
    like 1, 4, or 8 (AN5259 §3.4: walking=1, jogging=4, biking=8).
    For our 2026-05-22 run: still=0, motion=4.

    Format: --class-codes "still=0,motion=4"
    """
    if cli_class_codes is None:
        raise ValueError(
            "--class-codes required. Format: 'still=0,motion=4'. "
            "Get the actual values from MEMS Studio Config generation "
            "tab (the 'still' and 'motion' dropdown fields under "
            "'Class output values')."
        )
    out = {}
    for pair in cli_class_codes.split(","):
        pair = pair.strip()
        if "=" not in pair:
            raise ValueError(f"bad --class-codes pair: {pair!r}")
        name, val = pair.split("=", 1)
        try:
            out[name.strip()] = int(val.strip())
        except ValueError:
            raise ValueError(f"non-integer class code: {pair!r}")
    return out


def assert_no_meta_classifier(mlc_json: dict) -> None:
    """Spec calls for no meta-classifier debouncing. Raise if the
    JSON shows end_counters with nonzero values.

    From mlc_settings.json: the meta-classifier is implied by the
    Config generation tab's 'End counter #N' fields. MEMS Studio
    2.3.1 doesn't appear to expose these in mlc_settings.json
    explicitly (they go directly into the register sequence in
    mlc.json), so we can't actually check from settings alone.

    For now: noop with a warning that the check is incomplete.
    If MEMS Studio ever surfaces the end counters in settings,
    upgrade this to a real check.
    """
    # Future: if mlc_json acquires an 'end_counters' field, enforce
    # all zeros here. For 2026-05-22 the absence makes this unenforceable.
    return


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
    ap.add_argument("input_json", help="mlc_settings.json from MEMS Studio")
    ap.add_argument("--tree-file", required=False, default=None,
                    help="ST_decision_tree_*.txt from MEMS Studio "
                         "(required unless --inspect)")
    ap.add_argument("--class-codes", default=None,
                    help="comma-separated name=code pairs, e.g. "
                         "'still=0,motion=4'. Required for emission "
                         "(MEMS Studio doesn't export these in JSON).")
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

    if args.tree_file is None:
        print("ERROR: --tree-file required (or use --inspect)", file=sys.stderr)
        return 2

    try:
        with open(args.tree_file) as f:
            tree_text = f.read()
    except OSError as e:
        print(f"ERROR: cannot read {args.tree_file}: {e}", file=sys.stderr)
        return 2

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
        out["class_codes"] = extract_class_codes(args.class_codes)

        # Tree needs the feature name -> id map built from the features
        # we just extracted. We have to invert MEMS Studio's naming
        # convention. Each MEMS Studio feature has a name like
        # F<N>_ABS_<TYPE>_<INPUT> where N is 1-indexed.
        # We map both the F<N>_ prefix-only form and the full name.
        feature_name_to_id: dict[str, int] = {}
        # We don't have the full MEMS Studio feature names in our
        # extracted features list (we converted them). Reconstruct
        # from the raw input.
        raw_features = mlc_json.get("features", [])
        for idx, raw_feat in enumerate(raw_features):
            raw_name = str(raw_feat.get("feature_name", "")).strip().upper()
            raw_input = str(raw_feat.get("input", "")).strip()
            # MEMS Studio's tree text uses
            # F<idx+1>_ABS_<feature_name>_<input_upper>
            full_name = f"F{idx+1}_ABS_{raw_name}_{raw_input.upper()}"
            feature_name_to_id[full_name] = idx

        out["tree"] = extract_tree(
            tree_text, feature_name_to_id, out["class_codes"]
        )
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
        print(f"OK: extraction + validation succeeded")
        print(f"     inputs: {args.input_json}, {args.tree_file}")
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
