#!/usr/bin/env python3
"""
compare_decisions.py

Diffs two CSV files emitted by replay_parity.c (or any tool producing the
same schema) and reports parity at the per-window class level.

This is the gate-clearing tool for the pre-registration parity step:
  - Run replay_parity against the trained tree on a CSV from session N.
  - Run the on-sensor MLC against the same physical input (or replay the
    same CSV through MEMS Studio offline), log MLC0_SRC at each window
    boundary into the same schema.
  - compare_decisions.py both --> bit-identical pass/fail.

Expected schema (CSV header on row 1):
    window_idx,t_window_end_s,var_norm,p2p_norm,class

Comparison contract:
  - STRICT equal-length: if window counts differ, that's a parity
    FAILURE. Truncating to the shorter file would hide cases where
    the host and silicon disagreed about whether a window boundary
    occurred at all (e.g. due to a decimation phase mismatch).
  - Comparison key: the `class` column. Other columns (var_norm,
    p2p_norm, t_window_end_s) are informational; they're not required
    to be bit-identical between host and silicon because the host
    computes in float32 while the MLC uses half-precision internally.
    Only the CLASS LABEL has to agree.
  - First divergence is reported with full context (both rows).
  - Exit code: 0 if bit-identical classes across all rows, 1 otherwise.

Usage:
    compare_decisions.py FILE_A FILE_B [--label-a NAME] [--label-b NAME]
                                       [--quiet]

Example:
    compare_decisions.py host.csv mlc.csv --label-a host --label-b mlc
"""

from __future__ import annotations
import argparse
import csv
import sys
from dataclasses import dataclass


@dataclass
class Row:
    window_idx: int
    t_window_end_s: float
    var_norm: float
    p2p_norm: float
    klass: int  # `class` is a reserved word

    @classmethod
    def from_csv(cls, row: dict[str, str], lineno: int, source: str) -> "Row":
        try:
            return cls(
                window_idx=int(row["window_idx"]),
                t_window_end_s=float(row["t_window_end_s"]),
                var_norm=float(row["var_norm"]),
                p2p_norm=float(row["p2p_norm"]),
                klass=int(row["class"]),
            )
        except (KeyError, ValueError) as e:
            raise ValueError(
                f"{source}:line{lineno}: malformed row: {row!r} ({e})"
            ) from e


def load(path: str) -> list[Row]:
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        expected = {"window_idx", "t_window_end_s", "var_norm", "p2p_norm", "class"}
        missing = expected - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{path}: missing columns {sorted(missing)}; "
                f"got {reader.fieldnames}"
            )
        for i, raw in enumerate(reader, start=2):  # header is line 1
            rows.append(Row.from_csv(raw, i, path))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file_a")
    ap.add_argument("file_b")
    ap.add_argument("--label-a", default="A",
                    help="display name for file_a (default: A)")
    ap.add_argument("--label-b", default="B",
                    help="display name for file_b (default: B)")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress per-row divergence details, only report summary")
    args = ap.parse_args()

    try:
        rows_a = load(args.file_a)
        rows_b = load(args.file_b)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    n_a, n_b = len(rows_a), len(rows_b)
    print(f"{args.label_a}: {n_a} windows from {args.file_a}")
    print(f"{args.label_b}: {n_b} windows from {args.file_b}")

    # Strict-equal contract: a row-count mismatch is a parity failure.
    if n_a != n_b:
        print(f"\nFAIL: window counts differ ({n_a} vs {n_b}). This indicates "
              f"the two pipelines disagreed about whether a window boundary "
              f"occurred at all, not just about the label. Common causes: "
              f"decimation phase mismatch, different window length, one "
              f"pipeline got fewer samples.", file=sys.stderr)
        return 1

    # Per-row comparison on class only.
    n_compared = n_a
    n_disagree = 0
    first_div: tuple[int, Row, Row] | None = None

    for i, (a, b) in enumerate(zip(rows_a, rows_b)):
        if a.klass != b.klass:
            n_disagree += 1
            if first_div is None:
                first_div = (i, a, b)

    agreement_pct = 100.0 * (n_compared - n_disagree) / n_compared if n_compared else 0.0

    if n_disagree == 0:
        print(f"\nPASS: {n_compared}/{n_compared} classes agree (100.000%). "
              f"Bit-identical class labels across all windows.")
        return 0

    print(f"\nFAIL: {n_disagree}/{n_compared} classes disagree "
          f"({agreement_pct:.3f}% agreement).")

    if not args.quiet and first_div is not None:
        i, a, b = first_div
        print(f"\nFirst divergence at row index {i} (window_idx_{args.label_a}={a.window_idx}, "
              f"window_idx_{args.label_b}={b.window_idx}):")
        print(f"  {args.label_a}: t={a.t_window_end_s:.6f}s  var={a.var_norm:.6e}  "
              f"p2p={a.p2p_norm:.6e}  class={a.klass}")
        print(f"  {args.label_b}: t={b.t_window_end_s:.6f}s  var={b.var_norm:.6e}  "
              f"p2p={b.p2p_norm:.6e}  class={b.klass}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
