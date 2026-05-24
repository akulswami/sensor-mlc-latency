#!/usr/bin/env python3
"""
silicon_align.py

Stage 2 of the §9 parity gate.

Takes the host-side per-window decisions emitted by replay_parity and the
50 Hz on-sensor MLC poll log from mlc_poller, and produces a row-aligned
"silicon decisions" CSV in the same schema as replay_parity's output.
The aligned file can then be diffed against the host file by
compare_decisions.py without further fuss.

The semantics chosen here (one of several defensible options; documented
in the lab notebook for 2026-05-23):

  - One silicon-aligned row per host window. Row counts match the host
    file by construction.
  - Each host window covers (t_prev_window_end_s, t_window_end_s] in
    accel-relative seconds. Silicon polls are converted to the same
    time basis using session.json's imu_t0_monotonic_s and binned.
  - The class for each host window is the class of the LAST silicon
    poll falling inside it. Rationale: the MLC updates MLC0_SRC at
    MLC-window cadence, so within one host window the silicon's
    MLC0_SRC value is either constant or transitions at most once;
    the last poll most naturally captures "what would silicon have
    reported at this window's end if it were the source of truth."
  - Silicon polls before the host's first window starts (negative
    accel-relative time) are dropped — they have no corresponding
    host window.
  - If a host window contains zero silicon polls, that is treated as
    a fatal error, not silently filled. This should not happen for
    session 4 (silicon poll rate ~48.7 Hz, host window cadence ~1.4 Hz,
    so each host window contains ~35 polls); if it ever does, the
    alignment math is wrong and we want to know loudly.

Output schema (same as replay_parity, so compare_decisions.py reads it):

    window_idx,t_window_end_s,var_norm,p2p_norm,class

  - window_idx, t_window_end_s: copied from host_decisions.csv.
  - var_norm, p2p_norm: 0.0. Silicon does not expose feature values
    (AN5259 §1.3); compare_decisions.py compares only on class anyway.
  - class: last silicon poll's mlc_src for that window.

Usage:
    silicon_align.py --host-decisions host_decisions.csv \\
                     --silicon-raw silicon_raw.csv \\
                     --session-json session.json \\
                     --class-name still|motion \\
                     [--quiet]
"""

from __future__ import annotations
import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class HostWindow:
    """One row from the host-side replay_parity output."""
    window_idx: int
    t_window_end_s: float  # accel-relative seconds


@dataclass
class SiliconPoll:
    """One row from mlc_poller's silicon_raw.csv."""
    t_accel_relative_s: float  # converted from CLOCK_MONOTONIC
    mlc_src: int


def load_host_decisions(path: str) -> list[HostWindow]:
    """Read replay_parity's output. We only need window_idx and t_window_end_s."""
    rows: list[HostWindow] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        required = {"window_idx", "t_window_end_s"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{path}: missing columns {sorted(missing)}; "
                f"got {reader.fieldnames}"
            )
        for i, raw in enumerate(reader, start=2):
            try:
                rows.append(HostWindow(
                    window_idx=int(raw["window_idx"]),
                    t_window_end_s=float(raw["t_window_end_s"]),
                ))
            except (KeyError, ValueError) as e:
                raise ValueError(f"{path}:line{i}: malformed: {raw!r} ({e})") from e
    return rows


def load_silicon_raw(path: str, imu_t0_monotonic_s: float) -> list[SiliconPoll]:
    """Read mlc_poller's silicon_raw.csv. Skip the 3 comment lines and the
    column header, then convert each absolute CLOCK_MONOTONIC timestamp
    to accel-relative seconds by subtracting imu_t0_monotonic_s.
    """
    polls: list[SiliconPoll] = []
    with open(path) as f:
        lineno = 0
        header_seen = False
        for raw_line in f:
            lineno += 1
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            if not header_seen:
                # First non-comment, non-blank line is the column header.
                # Tolerate any whitespace around commas.
                cols = [c.strip() for c in line.split(",")]
                if cols != ["t_monotonic_s", "mlc_src"]:
                    raise ValueError(
                        f"{path}:line{lineno}: unexpected column header: {cols!r}; "
                        f"expected ['t_monotonic_s', 'mlc_src']"
                    )
                header_seen = True
                continue
            # Data row.
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 2:
                raise ValueError(
                    f"{path}:line{lineno}: expected 2 columns, got {len(parts)}: {line!r}"
                )
            try:
                t_abs = float(parts[0])
                mlc_src = int(parts[1])
            except ValueError as e:
                raise ValueError(f"{path}:line{lineno}: parse error: {line!r} ({e})") from e
            polls.append(SiliconPoll(
                t_accel_relative_s=t_abs - imu_t0_monotonic_s,
                mlc_src=mlc_src,
            ))
    if not header_seen:
        raise ValueError(f"{path}: no column header found")
    return polls


def align(host_windows: list[HostWindow],
          silicon_polls: list[SiliconPoll]) -> list[tuple[HostWindow, int, int]]:
    """For each host window, return (window, class, poll_count_in_window).

    Strategy (lab notebook 2026-05-23):
      - Each host window covers (t_prev, t_curr], left-open right-closed.
        For window 0, t_prev = 0.0 (accel-relative time origin = imu_t0).
      - The class assigned is the mlc_src of the LAST poll whose
        t_accel_relative_s falls inside that interval.
      - poll_count_in_window is informational; non-zero is asserted by
        the caller (zero is a fatal alignment error).

    Both inputs must be in ascending time order; we assert this defensively
    rather than assuming, because silently-misordered input would produce
    silently-wrong alignment.
    """
    # Defensive ordering checks.
    for i in range(1, len(host_windows)):
        if host_windows[i].t_window_end_s <= host_windows[i-1].t_window_end_s:
            raise ValueError(
                f"host_windows not strictly ascending at index {i}: "
                f"t[{i-1}]={host_windows[i-1].t_window_end_s} >= "
                f"t[{i}]={host_windows[i].t_window_end_s}"
            )
    for i in range(1, len(silicon_polls)):
        if silicon_polls[i].t_accel_relative_s < silicon_polls[i-1].t_accel_relative_s:
            raise ValueError(
                f"silicon_polls not ascending at index {i}: "
                f"t[{i-1}]={silicon_polls[i-1].t_accel_relative_s} > "
                f"t[{i}]={silicon_polls[i].t_accel_relative_s}"
            )

    results: list[tuple[HostWindow, int, int]] = []
    poll_idx = 0
    n_polls = len(silicon_polls)

    # Skip silicon polls that fall before the host's recording started.
    while poll_idx < n_polls and silicon_polls[poll_idx].t_accel_relative_s <= 0.0:
        poll_idx += 1

    prev_t_end = 0.0
    for w in host_windows:
        # Collect all polls in (prev_t_end, w.t_window_end_s].
        in_window: list[SiliconPoll] = []
        while poll_idx < n_polls and silicon_polls[poll_idx].t_accel_relative_s <= w.t_window_end_s:
            if silicon_polls[poll_idx].t_accel_relative_s > prev_t_end:
                in_window.append(silicon_polls[poll_idx])
            poll_idx += 1
        if not in_window:
            raise RuntimeError(
                f"host window {w.window_idx} (t_end={w.t_window_end_s:.6f}, "
                f"prev_t_end={prev_t_end:.6f}) contains zero silicon polls. "
                f"This indicates a time-alignment failure: either clock_offset_s "
                f"is wrong, the silicon poll loop stalled, or the host's window "
                f"cadence is faster than expected."
            )
        # Last poll wins.
        chosen_class = in_window[-1].mlc_src
        results.append((w, chosen_class, len(in_window)))
        prev_t_end = w.t_window_end_s

    return results


def write_aligned_csv(out: object,
                      aligned: list[tuple[HostWindow, int, int]]) -> None:
    """Emit in replay_parity's schema. var_norm and p2p_norm are 0.0."""
    out.write("window_idx,t_window_end_s,var_norm,p2p_norm,class\n")
    for w, cls, _ in aligned:
        out.write(f"{w.window_idx},{w.t_window_end_s:.6f},0.000000e+00,0.000000e+00,{cls}\n")


def find_class_block(session: dict, class_name: str) -> dict:
    """Pull the per-class block out of session.json's `classes` list."""
    classes = session.get("classes", [])
    for blk in classes:
        if blk.get("class") == class_name:
            return blk
    raise ValueError(
        f"class={class_name!r} not found in session.json; "
        f"available: {[blk.get('class') for blk in classes]}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host-decisions", required=True,
                    help="replay_parity output CSV (window_idx, t_window_end_s, ...)")
    ap.add_argument("--silicon-raw", required=True,
                    help="mlc_poller silicon_raw.csv (absolute CLOCK_MONOTONIC timestamps)")
    ap.add_argument("--session-json", required=True,
                    help="session.json from run_session_parity.py "
                         "(provides imu_t0_monotonic_s for time alignment)")
    ap.add_argument("--class-name", required=True, choices=["still", "motion"],
                    help="which class block to use from session.json for "
                         "imu_t0_monotonic_s")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress diagnostic stats on stderr")
    args = ap.parse_args()

    try:
        session = json.loads(Path(args.session_json).read_text())
        blk = find_class_block(session, args.class_name)
        imu_t0 = float(blk["imu_t0_monotonic_s"])

        host_windows = load_host_decisions(args.host_decisions)
        silicon_polls = load_silicon_raw(args.silicon_raw, imu_t0)
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if not host_windows:
        print(f"ERROR: no host windows in {args.host_decisions}", file=sys.stderr)
        return 2
    if not silicon_polls:
        print(f"ERROR: no silicon polls in {args.silicon_raw}", file=sys.stderr)
        return 2

    try:
        aligned = align(host_windows, silicon_polls)
    except (RuntimeError, ValueError) as e:
        print(f"ERROR (alignment): {e}", file=sys.stderr)
        return 1

    write_aligned_csv(sys.stdout, aligned)

    if not args.quiet:
        n_polls_total = len(silicon_polls)
        n_polls_used = sum(c for _, _, c in aligned)
        n_polls_dropped_pre = sum(
            1 for p in silicon_polls if p.t_accel_relative_s <= 0.0
        )
        n_polls_dropped_post = n_polls_total - n_polls_used - n_polls_dropped_pre
        avg_polls_per_win = n_polls_used / len(aligned) if aligned else 0.0
        min_polls = min((c for _, _, c in aligned), default=0)
        max_polls = max((c for _, _, c in aligned), default=0)
        class_counts: dict[int, int] = {}
        for _, cls, _ in aligned:
            class_counts[cls] = class_counts.get(cls, 0) + 1
        print(
            f"silicon_align: class={args.class_name}, "
            f"host_windows={len(host_windows)}, "
            f"silicon_polls_total={n_polls_total}, "
            f"used={n_polls_used}, dropped_pre_t0={n_polls_dropped_pre}, "
            f"dropped_post_last_window={n_polls_dropped_post}, "
            f"polls_per_window min/avg/max={min_polls}/{avg_polls_per_win:.2f}/{max_polls}, "
            f"aligned_class_distribution={class_counts}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
