"""
test_extract_latency_v7.py
==========================

Unit tests for extract_latency_v7.py. Validates each algorithmic
component against hand-constructed synthetic Saleae traces.

Run with:
    cd code/analysis
    python3 test_extract_latency_v7.py
"""

from __future__ import annotations

import sys
import tempfile
import csv as csv_module
from pathlib import Path

import extract_latency_v7 as mod
from extract_latency_v7 import (
    Edge, PWMCycle, StimulusTransition, TrialRecord,
    detect_pwm_cycles, detect_stimulus_transitions, assign_trials,
    parse_saleae_csv, extract_trials_from_csv,
    PWM_CENTER_PULSE_US, PWM_MOTION_THRESHOLD_US, N_CONFIRM_CYCLES,
    MAX_PAIR_GAP_US,
)


# ---------------------------------------------------------------------------
# Helpers for synthetic trace construction
# ---------------------------------------------------------------------------

def make_pwm_cycle_edges(t_start_s: float, pulse_width_us: float,
                        cycle_period_us: float = 20_000.0) -> list:
    """Construct a list of (D2-only) Edge events for a single PWM cycle:
    a rising edge at t_start, a falling edge at t_start + pulse_width.
    """
    return [
        Edge(t_s=t_start_s, channel=2, direction="rising"),
        Edge(t_s=t_start_s + pulse_width_us * 1e-6, channel=2, direction="falling"),
    ]


def make_d2_trace(pulse_widths_us: list, t_start_s: float = 0.0,
                  cycle_period_us: float = 20_000.0) -> list:
    """Construct a complete D2 trace from a sequence of per-cycle pulse widths."""
    edges = []
    for i, pw in enumerate(pulse_widths_us):
        t_cycle_start = t_start_s + i * cycle_period_us * 1e-6
        edges.extend(make_pwm_cycle_edges(t_cycle_start, pw, cycle_period_us))
    return edges


def write_synthetic_csv(d0_risings: list, d1_risings: list,
                        d2_edges: list) -> Path:
    """Write a synthetic Saleae CSV from edge lists.

    For simplicity: this generates a CSV where each row represents the state
    of all channels at a transition time. We merge all edges from all
    channels chronologically.
    """
    all_events = []
    for t in d0_risings:
        all_events.append((t, 0, "rising"))
        all_events.append((t + 0.0001, 0, "falling"))  # short pulse on D0 (100us)
    for t in d1_risings:
        all_events.append((t, 1, "rising"))
        all_events.append((t + 0.0001, 1, "falling"))
    for e in d2_edges:
        all_events.append((e.t_s, e.channel, e.direction))

    all_events.sort(key=lambda x: x[0])

    states = [0, 0, 0]
    rows = [(0.0, states[0], states[1], states[2])]
    for t, ch, direction in all_events:
        states[ch] = 1 if direction == "rising" else 0
        rows.append((t, states[0], states[1], states[2]))

    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    )
    writer = csv_module.writer(f)
    writer.writerow(["Time [s]", "Channel 0", "Channel 1", "Channel 2"])
    for r in rows:
        writer.writerow([f"{r[0]:.9f}", r[1], r[2], r[3]])
    f.close()
    return Path(f.name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pwm_cycle_classification_still():
    """A trace of center-pulse cycles classifies as still."""
    d2 = make_d2_trace([1380.0] * 10)
    cycles = detect_pwm_cycles(d2)
    assert len(cycles) == 10, f"expected 10 cycles, got {len(cycles)}"
    for c in cycles:
        assert c.classification == "still", (
            f"expected still for pulse_width {c.pulse_width_us}, got {c.classification}"
        )


def test_pwm_cycle_classification_motion():
    """A trace of endpoint-pulse cycles classifies as motion."""
    # 458us (MIN endpoint) and 2297us (MAX endpoint) both should classify as motion
    d2 = make_d2_trace([458.0, 2297.0, 458.0, 2297.0, 458.0])
    cycles = detect_pwm_cycles(d2)
    assert len(cycles) == 5
    for c in cycles:
        assert c.classification == "motion", (
            f"expected motion for pulse_width {c.pulse_width_us}, got {c.classification}"
        )


def test_pwm_cycle_threshold_boundary():
    """Test pulse widths near the threshold (1380 +/- 500 us = [880, 1880] still range).

    Note: testing AT exactly 500us deviation is unstable due to floating-point
    roundtrip in the (t_falling - t_rising) * 1e6 computation. Tests use
    deviations >= 2us off the boundary, which is far more than any FP noise
    and corresponds to a precision much finer than any real measurement
    distribution from this hardware (empirical pulse-widths are 458, 1380,
    2297 us, all >400us from the threshold).
    """
    # Comfortably inside still: pulse=878us (deviation 502us = motion)
    # Comfortably inside still: pulse=882us (deviation 498us = still)
    # Comfortably outside still on the high side: pulse=1882us (deviation 502us = motion)
    # Comfortably inside still on the high side: pulse=1878us (deviation 498us = still)
    d2 = make_d2_trace([882.0, 878.0, 1878.0, 1882.0])
    cycles = detect_pwm_cycles(d2)
    assert cycles[0].classification == "still", (
        f"pulse=882, dev=498 should be still, got {cycles[0].classification}"
    )
    assert cycles[1].classification == "motion", (
        f"pulse=878, dev=502 should be motion, got {cycles[1].classification}"
    )
    assert cycles[2].classification == "still", (
        f"pulse=1878, dev=498 should be still, got {cycles[2].classification}"
    )
    assert cycles[3].classification == "motion", (
        f"pulse=1882, dev=502 should be motion, got {cycles[3].classification}"
    )


def test_stimulus_transitions_simple():
    """A trace with 5 still, 5 motion, 5 still cycles produces 2 transitions."""
    pulses = [1380.0] * 5 + [2297.0] * 5 + [1380.0] * 5
    d2 = make_d2_trace(pulses)
    cycles = detect_pwm_cycles(d2)
    transitions = detect_stimulus_transitions(cycles)
    assert len(transitions) == 2, (
        f"expected 2 transitions, got {len(transitions)}: {transitions}"
    )
    assert transitions[0].transition_type == "still_to_motion"
    assert transitions[1].transition_type == "motion_to_still"
    # First transition occurs at start of cycle 5 (0-indexed): t = 5 * 20ms = 0.1s
    assert abs(transitions[0].t_s - 0.1) < 1e-6, (
        f"expected t≈0.1, got {transitions[0].t_s}"
    )
    # Second transition at start of cycle 10: t = 10 * 20ms = 0.2s
    assert abs(transitions[1].t_s - 0.2) < 1e-6


def test_stimulus_transition_requires_N_consecutive():
    """A single rogue 'motion' cycle in a still run should NOT trigger a transition."""
    # 5 still, 1 motion (glitch), 5 still
    pulses = [1380.0] * 5 + [2297.0] * 1 + [1380.0] * 5
    d2 = make_d2_trace(pulses)
    cycles = detect_pwm_cycles(d2)
    transitions = detect_stimulus_transitions(cycles)
    assert len(transitions) == 0, (
        f"expected 0 transitions for single-cycle glitch, got {len(transitions)}"
    )


def test_stimulus_transition_two_consecutive_insufficient():
    """Two consecutive motion cycles in a still run should NOT trigger (need N=3)."""
    # 5 still, 2 motion, 5 still
    pulses = [1380.0] * 5 + [2297.0] * 2 + [1380.0] * 5
    d2 = make_d2_trace(pulses)
    cycles = detect_pwm_cycles(d2)
    transitions = detect_stimulus_transitions(cycles)
    assert len(transitions) == 0, (
        f"expected 0 transitions for 2-cycle glitch, got {len(transitions)}"
    )


def test_stimulus_transition_three_consecutive_sufficient():
    """Three consecutive motion cycles should trigger a transition."""
    # 5 still, 3 motion (just enough to confirm), then back to still — but this trailing
    # still would be a brief motion. To get TWO transitions, we need 5 still / 3 motion / 5 still
    # → still→motion confirmed at cycle 5, motion→still after only 3 motion cycles needs the
    # subsequent 3 still cycles to confirm.
    pulses = [1380.0] * 5 + [2297.0] * 3 + [1380.0] * 5
    d2 = make_d2_trace(pulses)
    cycles = detect_pwm_cycles(d2)
    transitions = detect_stimulus_transitions(cycles)
    # Should detect still→motion (at cycle 5) and motion→still (at cycle 8)
    assert len(transitions) == 2
    assert transitions[0].transition_type == "still_to_motion"
    assert transitions[1].transition_type == "motion_to_still"


def test_trial_pairing_simple():
    """A clean D0→D1 pair at known latency."""
    d2 = make_d2_trace([1380.0] * 5 + [2297.0] * 5 + [1380.0] * 5)
    d0_risings = [0.105]  # 5ms after stimulus 0 (still→motion at t=0.1)
    d1_risings = [0.106]  # 1ms after D0 → 1000us latency
    cycles = detect_pwm_cycles(d2)
    transitions = detect_stimulus_transitions(cycles)

    edges = d2 + [
        Edge(t_s=t, channel=0, direction="rising") for t in d0_risings
    ] + [
        Edge(t_s=t, channel=1, direction="rising") for t in d1_risings
    ]
    trials = assign_trials(edges, transitions, is_first_arm=False)
    assert len(trials) == 2
    # First trial (still→motion) should pair D0=0.105 with D1=0.106
    t0 = trials[0]
    assert t0.included, f"first trial should be included; reason: {t0.exclusion_reason}"
    assert abs(t0.latency_us - 1000.0) < 1.0, f"expected ~1000us, got {t0.latency_us}"
    # Second trial has no D0/D1 events → no_d1_after_stim
    t1 = trials[1]
    assert not t1.included
    assert t1.exclusion_reason == "no_d1_after_stim"


def test_trial_exclusion_overlapping_d0():
    """Two D0 rising edges before the same D1 → §11 exclusion."""
    d2 = make_d2_trace([1380.0] * 5 + [2297.0] * 5 + [1380.0] * 5)
    d0_risings = [0.105, 0.106]  # two D0 edges in quick succession
    d1_risings = [0.110]
    cycles = detect_pwm_cycles(d2)
    transitions = detect_stimulus_transitions(cycles)
    edges = d2 + [
        Edge(t_s=t, channel=0, direction="rising") for t in d0_risings
    ] + [
        Edge(t_s=t, channel=1, direction="rising") for t in d1_risings
    ]
    trials = assign_trials(edges, transitions, is_first_arm=False)
    t0 = trials[0]
    assert not t0.included
    assert t0.exclusion_reason == "multiple_d0_before_d1"


def test_trial_exclusion_latency_exceeds_100ms():
    """D0→D1 gap > 100ms triggers §6.2 exclusion."""
    d2 = make_d2_trace([1380.0] * 5 + [2297.0] * 10 + [1380.0] * 5)
    d0_risings = [0.105]
    d1_risings = [0.210]  # 105ms gap, > 100ms threshold
    cycles = detect_pwm_cycles(d2)
    transitions = detect_stimulus_transitions(cycles)
    edges = d2 + [
        Edge(t_s=t, channel=0, direction="rising") for t in d0_risings
    ] + [
        Edge(t_s=t, channel=1, direction="rising") for t in d1_risings
    ]
    trials = assign_trials(edges, transitions, is_first_arm=False)
    t0 = trials[0]
    assert not t0.included
    assert t0.exclusion_reason == "latency_exceeds_100ms"


def test_trial_pairing_sync_edge_skipped():
    """If is_first_arm, the first D1 rising edge is the sync edge and is skipped."""
    # Trace: 5 still cycles, then 5 motion cycles starting at t=0.1
    d2 = make_d2_trace([1380.0] * 5 + [2297.0] * 5)
    # Sync edge at t=0.001 (very early), measurement D1 at t=0.106
    d0_risings = [0.105]
    d1_risings = [0.001, 0.106]  # first is sync, second is the real measurement
    cycles = detect_pwm_cycles(d2)
    transitions = detect_stimulus_transitions(cycles)

    edges = d2 + [
        Edge(t_s=t, channel=0, direction="rising") for t in d0_risings
    ] + [
        Edge(t_s=t, channel=1, direction="rising") for t in d1_risings
    ]
    # With is_first_arm=True, sync edge at 0.001 should be skipped
    trials = assign_trials(edges, transitions, is_first_arm=True)
    assert len(trials) == 1
    t0 = trials[0]
    assert t0.included, f"reason: {t0.exclusion_reason}"
    # Should pair D0=0.105 with D1=0.106 (NOT the 0.001 sync edge)
    assert abs(t0.latency_us - 1000.0) < 1.0


def test_trial_pairing_no_sync_skip_when_not_first_arm():
    """is_first_arm=False: D1 at 0.001 is treated as a real measurement edge."""
    d2 = make_d2_trace([1380.0] * 5 + [2297.0] * 5)
    d0_risings = [0.105]
    d1_risings = [0.001, 0.106]
    cycles = detect_pwm_cycles(d2)
    transitions = detect_stimulus_transitions(cycles)
    edges = d2 + [
        Edge(t_s=t, channel=0, direction="rising") for t in d0_risings
    ] + [
        Edge(t_s=t, channel=1, direction="rising") for t in d1_risings
    ]
    # Without sync skip, the next D1 after t_stim=0.1 is 0.106
    trials = assign_trials(edges, transitions, is_first_arm=False)
    assert len(trials) == 1
    t0 = trials[0]
    assert t0.included
    assert abs(t0.latency_us - 1000.0) < 1.0


def test_csv_roundtrip_via_synthetic_file():
    """End-to-end: write a synthetic CSV, parse it, run pipeline, verify."""
    d2 = make_d2_trace([1380.0] * 5 + [2297.0] * 5 + [1380.0] * 5)
    d0_risings = [0.105]
    d1_risings = [0.106]
    csv_path = write_synthetic_csv(d0_risings, d1_risings, d2)
    try:
        trials = extract_trials_from_csv(csv_path, is_first_arm=False)
        assert len(trials) == 2
        assert trials[0].included
        assert abs(trials[0].latency_us - 1000.0) < 1.0
    finally:
        csv_path.unlink()


def test_real_burst_btest_data():
    """Run extractor against the real 2026-05-25-burst-btest data; verify 6 transitions."""
    csv_path = Path("/tmp/burst_export/digital.csv")
    if not csv_path.exists():
        print(f"  SKIP (no btest data at {csv_path})")
        return
    trials = extract_trials_from_csv(csv_path, is_first_arm=False)
    assert len(trials) == 6, f"expected 6 transitions, got {len(trials)}"
    # All excluded because no D1 measurement edges in the btest


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_all_tests():
    tests = [name for name in dir(sys.modules[__name__]) if name.startswith("test_")]
    passed, failed = [], []
    for name in tests:
        fn = getattr(sys.modules[__name__], name)
        try:
            fn()
            passed.append(name)
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed.append((name, str(e)))
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ERROR {name}: {type(e).__name__}: {e}")

    print(f"\n{len(passed)} passed, {len(failed)} failed.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
