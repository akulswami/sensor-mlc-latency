"""
extract_latency_v7.py
=====================

Wire-level latency extractor for the v7 sensor-mlc-latency experiment.

Pre-reg refs:
  - v7 Change 3 (§6.1): latency = t(D1_rising) - t(D0_rising), from Saleae trace.
  - v7 Change 6 item 6: implementation requirements.
  - v7.1: D3 → D1 correction.
  - v7.3: D2-based motion-window gating; sweep.log retired from gating.

Input:
  - A Saleae digital-channel CSV with columns:
      Time [s], Channel 0, Channel 1, Channel 2
    (D0 = sensor INT1, D1 = decision GPIO, D2 = PCA9685 PWM)
  - Saleae sample format: each row is a transition (NOT a uniform sample);
    successive rows show channel-state changes.

Output:
  - A per-trial CSV with one row per stimulus transition:
      trial_id, stimulus_type, t_stim_s, t_d0_s, t_d1_s, latency_us,
      included, exclusion_reason

Pinned constants per pre-reg v7.3 (2026-05-25, empirically derived from
data/training/2026-05-25-burst-btest):
  PWM_CENTER_PULSE_US      = 1380
  PWM_MOTION_THRESHOLD_US  = 500
  N_CONFIRM_CYCLES         = 3
  MAX_PAIR_GAP_US          = 100_000  (per §6.2)

Sync-edge handling: the first D1 rising edge of a still-arm trace is the
session sync edge per Gate 1; it is not a measurement edge. Callers
pass is_first_arm=True for the still arm to enable sync-edge skipping.

Usage as a script:
  python3 extract_latency_v7.py \\
      --csv data/training/SESSION/still/digital.csv \\
      --is-first-arm \\
      --out data/processed/SESSION/still/trials.csv

Usage as a library:
  from extract_latency_v7 import extract_trials_from_csv, TrialRecord
  trials = extract_trials_from_csv(csv_path, is_first_arm=True)
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Pinned constants (pre-reg v7.3)
# ---------------------------------------------------------------------------

PWM_CENTER_PULSE_US: float = 1380.0
PWM_MOTION_THRESHOLD_US: float = 500.0
N_CONFIRM_CYCLES: int = 3
MAX_PAIR_GAP_US: float = 100_000.0  # §6.2: 100ms exclusion


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    """A single channel transition."""
    t_s: float           # Saleae timestamp (seconds)
    channel: int         # 0, 1, or 2
    direction: str       # 'rising' or 'falling'


@dataclass
class PWMCycle:
    """One PWM cycle on D2: rising edge to next falling edge to next rising edge."""
    t_rising_s: float
    t_falling_s: float
    pulse_width_us: float
    classification: str   # 'still' or 'motion'


@dataclass
class StimulusTransition:
    """A confirmed stimulus transition (still↔motion)."""
    t_s: float                  # Saleae time of the first cycle of the new state
    transition_type: str        # 'still_to_motion' or 'motion_to_still'


@dataclass
class TrialRecord:
    """One trial (or attempted trial) — per stimulus transition."""
    trial_id: int
    stimulus_type: str          # 'still_to_motion' or 'motion_to_still'
    t_stim_s: float             # Stimulus transition time
    t_d0_s: Optional[float]     # D0 rising edge time, if found
    t_d1_s: Optional[float]     # D1 rising edge time, if found
    latency_us: Optional[float] # D1 - D0 (microseconds), if both present
    included: bool              # True iff the trial passed all exclusion criteria
    exclusion_reason: str       # '' if included; otherwise per §6.2/§11/etc.


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def parse_saleae_csv(csv_path: Path) -> List[Edge]:
    """Parse a Saleae digital-channel CSV into a list of Edge objects.

    The Saleae format: each row is a snapshot of all channels at a transition
    time. We walk through rows and emit one Edge per channel-state change.
    """
    edges: List[Edge] = []
    with open(csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)
        # Validate header
        if not (len(header) >= 4 and header[0].lower().startswith("time")):
            raise ValueError(f"Unexpected header: {header}")

        prev_states: Optional[Tuple[int, int, int]] = None
        for row in reader:
            if len(row) < 4:
                continue
            try:
                t = float(row[0])
                d0, d1, d2 = int(row[1]), int(row[2]), int(row[3])
            except ValueError:
                continue
            cur_states = (d0, d1, d2)
            if prev_states is not None:
                for ch, (prev, cur) in enumerate(zip(prev_states, cur_states)):
                    if cur != prev:
                        direction = "rising" if cur == 1 else "falling"
                        edges.append(Edge(t_s=t, channel=ch, direction=direction))
            prev_states = cur_states

    return edges


# ---------------------------------------------------------------------------
# D2 PWM cycle classification
# ---------------------------------------------------------------------------

def detect_pwm_cycles(edges: List[Edge]) -> List[PWMCycle]:
    """Walk the D2 edges and produce one PWMCycle per (rising → falling) pair.

    Classification per cycle:
      'still' if |pulse_width_us - PWM_CENTER_PULSE_US| <= PWM_MOTION_THRESHOLD_US
      'motion' otherwise
    """
    d2_edges = [e for e in edges if e.channel == 2]
    cycles: List[PWMCycle] = []

    # Walk through rising→falling pairs
    i = 0
    while i < len(d2_edges):
        rising = d2_edges[i]
        if rising.direction != "rising":
            i += 1
            continue
        # Find the next falling edge
        j = i + 1
        while j < len(d2_edges) and d2_edges[j].direction != "falling":
            j += 1
        if j >= len(d2_edges):
            break  # incomplete cycle at end

        falling = d2_edges[j]
        pulse_width_us = (falling.t_s - rising.t_s) * 1e6
        deviation = abs(pulse_width_us - PWM_CENTER_PULSE_US)
        classification = "still" if deviation <= PWM_MOTION_THRESHOLD_US else "motion"

        cycles.append(PWMCycle(
            t_rising_s=rising.t_s,
            t_falling_s=falling.t_s,
            pulse_width_us=pulse_width_us,
            classification=classification,
        ))
        i = j + 1

    return cycles


def detect_stimulus_transitions(cycles: List[PWMCycle]) -> List[StimulusTransition]:
    """Detect stimulus transitions (still↔motion) using N-consecutive-cycle confirmation.

    A transition is emitted at the time of the first cycle of a new run of
    classifications, provided that the new run continues for at least
    N_CONFIRM_CYCLES cycles. The transition timestamp is the start of the
    first cycle of the new state.
    """
    if len(cycles) < N_CONFIRM_CYCLES:
        return []

    transitions: List[StimulusTransition] = []

    # Track current confirmed state. Initially, look at the first N_CONFIRM_CYCLES
    # cycles to determine the initial state.
    initial_run = [c.classification for c in cycles[:N_CONFIRM_CYCLES]]
    if len(set(initial_run)) != 1:
        # Initial classifications inconsistent; fall back to majority
        current_state = max(set(initial_run), key=initial_run.count)
    else:
        current_state = initial_run[0]

    # Walk forward looking for confirmed transitions
    i = N_CONFIRM_CYCLES
    while i < len(cycles):
        cycle = cycles[i]
        if cycle.classification != current_state:
            # Candidate transition. Check if the next N_CONFIRM_CYCLES-1
            # cycles also match the new classification.
            new_state = cycle.classification
            confirm_idx = i
            confirmed = True
            for k in range(1, N_CONFIRM_CYCLES):
                if confirm_idx + k >= len(cycles):
                    confirmed = False
                    break
                if cycles[confirm_idx + k].classification != new_state:
                    confirmed = False
                    break
            if confirmed:
                # Emit the transition at the start of cycle i (first cycle of new state)
                trans_type = f"{current_state}_to_{new_state}"
                transitions.append(StimulusTransition(
                    t_s=cycle.t_rising_s,
                    transition_type=trans_type,
                ))
                current_state = new_state
                i = confirm_idx + N_CONFIRM_CYCLES
                continue
        i += 1

    return transitions


# ---------------------------------------------------------------------------
# Trial assignment
# ---------------------------------------------------------------------------

def assign_trials(
    edges: List[Edge],
    transitions: List[StimulusTransition],
    is_first_arm: bool = False,
    pipeline: str = "host",
) -> List[TrialRecord]:
    """For each stimulus transition, find the trial's D0/D1 pair and emit a TrialRecord.

    Per pre-reg v7.4: trial-pairing within a stimulus window (t_stim, t_next_stim]:
      1. Count D1 rising edges in the window.
         - 0 -> §11 criterion 1 exclusion ("no_d1_in_window")
         - >=2 -> §11 criterion 4 (host) exclusion ("multiple_d1_in_window")
         - exactly 1 -> proceed
      2. Pair D1 with most recent D0 in (t_stim, t_d1].
         - For MLC pipeline: if >=2 D0s in that range, §11 criterion 4 (MLC)
           exclusion ("multiple_d0_before_d1")
         - For host pipeline: D0 streams at sensor ODR; multiple D0s are
           normal and expected, not an exclusion.
      3. Compute latency = t_d1 - t_d0; if > 100 ms, §6.2 exclusion.

    Sync-edge handling: if is_first_arm=True, the first D1 rising edge in the
    entire trace is the session sync edge (Gate 1) and is treated as
    not-a-measurement-edge. It is consumed and skipped before trial pairing.

    pipeline ('host' or 'mlc') controls the criterion 4 behavior per v7.4.
    """
    if pipeline not in ("host", "mlc"):
        raise ValueError(f"pipeline must be 'host' or 'mlc', got {pipeline!r}")

    d0_risings = sorted(
        [e.t_s for e in edges if e.channel == 0 and e.direction == "rising"]
    )
    d1_risings = sorted(
        [e.t_s for e in edges if e.channel == 1 and e.direction == "rising"]
    )

    # Sync-edge skip
    if is_first_arm and d1_risings:
        d1_risings = d1_risings[1:]

    trials: List[TrialRecord] = []

    # Determine the window for each stimulus transition: (t_stim, t_next_stim].
    # The last stimulus transition's window extends to end-of-capture (use
    # the latest edge in the trace as the implicit end).
    all_edge_times = [e.t_s for e in edges]
    capture_end_s = max(all_edge_times) if all_edge_times else 0.0

    for trial_id, trans in enumerate(transitions):
        t_stim = trans.t_s
        if trial_id + 1 < len(transitions):
            t_next_stim = transitions[trial_id + 1].t_s
        else:
            t_next_stim = capture_end_s

        # Count D1 rising edges in (t_stim, t_next_stim]
        d1_in_window = [t for t in d1_risings if t_stim < t <= t_next_stim]

        if len(d1_in_window) == 0:
            trials.append(TrialRecord(
                trial_id=trial_id,
                stimulus_type=trans.transition_type,
                t_stim_s=t_stim,
                t_d0_s=None,
                t_d1_s=None,
                latency_us=None,
                included=False,
                exclusion_reason="no_d1_in_window",
            ))
            continue

        if len(d1_in_window) >= 2:
            # §11 criterion 4 for host pipeline (and applies to MLC too;
            # the classifier oscillation case is real for both).
            trials.append(TrialRecord(
                trial_id=trial_id,
                stimulus_type=trans.transition_type,
                t_stim_s=t_stim,
                t_d0_s=None,
                t_d1_s=d1_in_window[0],
                latency_us=None,
                included=False,
                exclusion_reason="multiple_d1_in_window",
            ))
            continue

        # Exactly one D1 in the window
        t_d1 = d1_in_window[0]

        # Find paired D0 = most recent D0 in (t_stim, t_d1]
        d0_in_pair_range = [t for t in d0_risings if t_stim < t <= t_d1]

        if not d0_in_pair_range:
            trials.append(TrialRecord(
                trial_id=trial_id,
                stimulus_type=trans.transition_type,
                t_stim_s=t_stim,
                t_d0_s=None,
                t_d1_s=t_d1,
                latency_us=None,
                included=False,
                exclusion_reason="no_d0_between_stim_and_d1",
            ))
            continue

        # For MLC pipeline only: §11 criterion 4 — multiple D0 before D1 is
        # ambiguous (the MLC fired twice before the host could read MLC0_SRC).
        # For host pipeline: D0 streams at sensor ODR; multiple D0s in this
        # range are normal and not an exclusion.
        if pipeline == "mlc" and len(d0_in_pair_range) >= 2:
            trials.append(TrialRecord(
                trial_id=trial_id,
                stimulus_type=trans.transition_type,
                t_stim_s=t_stim,
                t_d0_s=d0_in_pair_range[-1],
                t_d1_s=t_d1,
                latency_us=None,
                included=False,
                exclusion_reason="multiple_d0_before_d1",
            ))
            continue

        t_d0 = d0_in_pair_range[-1]
        latency_us = (t_d1 - t_d0) * 1e6

        # §6.2: gap > 100 ms exclusion
        if latency_us > MAX_PAIR_GAP_US:
            trials.append(TrialRecord(
                trial_id=trial_id,
                stimulus_type=trans.transition_type,
                t_stim_s=t_stim,
                t_d0_s=t_d0,
                t_d1_s=t_d1,
                latency_us=latency_us,
                included=False,
                exclusion_reason="latency_exceeds_100ms",
            ))
            continue

        trials.append(TrialRecord(
            trial_id=trial_id,
            stimulus_type=trans.transition_type,
            t_stim_s=t_stim,
            t_d0_s=t_d0,
            t_d1_s=t_d1,
            latency_us=latency_us,
            included=True,
            exclusion_reason="",
        ))

    return trials


# ---------------------------------------------------------------------------
# Top-level entry points
# ---------------------------------------------------------------------------

def extract_trials_from_csv(
    csv_path: Path,
    is_first_arm: bool = False,
    pipeline: str = "host",
) -> List[TrialRecord]:
    """Top-level: CSV → list of TrialRecords.

    pipeline ('host' or 'mlc') controls the §11 criterion 4 behavior per
    pre-reg v7.4. See assign_trials for details.
    """
    edges = parse_saleae_csv(csv_path)
    cycles = detect_pwm_cycles(edges)
    transitions = detect_stimulus_transitions(cycles)
    trials = assign_trials(edges, transitions,
                            is_first_arm=is_first_arm, pipeline=pipeline)
    return trials


def write_trials_csv(trials: List[TrialRecord], out_path: Path) -> None:
    """Write trials to a CSV file."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "trial_id", "stimulus_type", "t_stim_s", "t_d0_s", "t_d1_s",
            "latency_us", "included", "exclusion_reason"
        ])
        writer.writeheader()
        for tr in trials:
            writer.writerow(asdict(tr))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Extract per-trial latencies from a Saleae CSV.")
    parser.add_argument("--csv", required=True, type=Path, help="Path to Saleae digital CSV.")
    parser.add_argument("--out", required=True, type=Path, help="Output CSV path.")
    parser.add_argument("--pipeline", choices=["host", "mlc"], required=True,
                        help="Which pipeline produced the trace. Controls the "
                             "§11 criterion 4 behavior per pre-reg v7.4.")
    parser.add_argument("--is-first-arm", action="store_true",
                        help="If set, the first D1 rising edge is treated as the session sync edge "
                             "(skipped as a measurement edge). Use for the still arm of v7 captures.")
    args = parser.parse_args()

    trials = extract_trials_from_csv(
        args.csv, is_first_arm=args.is_first_arm, pipeline=args.pipeline
    )
    write_trials_csv(trials, args.out)

    n_total = len(trials)
    n_included = sum(1 for t in trials if t.included)
    print(f"Extracted {n_total} stimulus transitions.")
    print(f"  Included trials: {n_included}")
    print(f"  Excluded: {n_total - n_included}")
    print(f"  Output: {args.out}")

    if n_included > 0:
        latencies = [t.latency_us for t in trials if t.included and t.latency_us is not None]
        latencies.sort()
        print(f"  Latency (us): min={latencies[0]:.1f}, "
              f"median={latencies[len(latencies)//2]:.1f}, "
              f"max={latencies[-1]:.1f}")


if __name__ == "__main__":
    main()
