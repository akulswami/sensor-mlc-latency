"""
extract_latency_v2.py

Computes wire-level latency from solenoid-driven trials with piezo
ground-truth.

Inputs:
  digital_csv: Saleae digital export with columns
               Time [s], Channel 0 (D0=sensor INT),
               Channel 1 (D1=decision GPIO), Channel 2 (D2=solenoid trigger)
  analog_csv:  Saleae analog export with columns
               Time [s], Channel 0 (A0=piezo plunger),
               Channel 1 (A1=piezo breakout)
  out_csv:     Output CSV with one row per matched event
  --threshold-v: Voltage threshold for piezo edge detection (default 0.5)

For each rising crossing on A1 (piezo at sensor breakout, the real ground
truth), find:
  - the next rising edge on D1 (decision)
  - the most recent rising edge on D2 (solenoid command) before A1
  - the most recent rising crossing on A0 (piezo plunger) before A1

Then compute:
  latency_pipeline_us = D1 - A1   (wire-level pipeline latency, the headline)
  solenoid_delay_us   = A0 - D2   (electrical-to-mechanical delay of solenoid)
  propagation_us      = A1 - A0   (mechanical propagation through breakout)

Usage:
  python3 extract_latency_v2.py digital.csv analog.csv pairs.csv [--threshold-v 0.5]
"""
import argparse
import csv
import bisect


def parse_digital(path):
    """Returns (d0_rising, d1_rising, d2_rising) lists of timestamps in seconds."""
    d0_r, d1_r, d2_r = [], [], []
    prev = (0, 0, 0)
    with open(path) as f:
        reader = csv.reader(f)
        next(reader)  # header
        for row in reader:
            t = float(row[0])
            d0 = int(row[1])
            d1 = int(row[2])
            d2 = int(row[3])
            if d0 == 1 and prev[0] == 0: d0_r.append(t)
            if d1 == 1 and prev[1] == 0: d1_r.append(t)
            if d2 == 1 and prev[2] == 0: d2_r.append(t)
            prev = (d0, d1, d2)
    return d0_r, d1_r, d2_r


def parse_analog_crossings(path, threshold):
    """Returns (a0_rising, a1_rising) lists of timestamps where each analog
    channel crosses the threshold rising. Hysteresis: after a rise, requires
    the signal to drop back below 0.7 * threshold before a new rise can be
    counted."""
    a0_r, a1_r = [], []
    a0_armed = a1_armed = True
    low_threshold = threshold * 0.7

    with open(path) as f:
        reader = csv.reader(f)
        next(reader)
        prev_a0 = prev_a1 = 0.0
        for row in reader:
            t  = float(row[0])
            a0 = float(row[1])
            a1 = float(row[2])
            if a0_armed and prev_a0 < threshold and a0 >= threshold:
                a0_r.append(t)
                a0_armed = False
            elif not a0_armed and a0 < low_threshold:
                a0_armed = True
            if a1_armed and prev_a1 < threshold and a1 >= threshold:
                a1_r.append(t)
                a1_armed = False
            elif not a1_armed and a1 < low_threshold:
                a1_armed = True
            prev_a0, prev_a1 = a0, a1
    return a0_r, a1_r


def previous_before(sorted_list, t):
    """Largest x in sorted_list with x < t, or None."""
    idx = bisect.bisect_left(sorted_list, t)
    return sorted_list[idx - 1] if idx > 0 else None


def next_after(sorted_list, t):
    """Smallest x in sorted_list with x > t, or None."""
    idx = bisect.bisect_right(sorted_list, t)
    return sorted_list[idx] if idx < len(sorted_list) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("digital_csv")
    ap.add_argument("analog_csv")
    ap.add_argument("out_csv")
    ap.add_argument("--threshold-v", type=float, default=0.5,
                    help="Piezo voltage threshold for rising-edge detection (V)")
    args = ap.parse_args()

    print(f"Digital: {args.digital_csv}")
    print(f"Analog:  {args.analog_csv}")
    print(f"Threshold: {args.threshold_v} V")
    print()

    d0_r, d1_r, d2_r = parse_digital(args.digital_csv)
    a0_r, a1_r = parse_analog_crossings(args.analog_csv, args.threshold_v)

    print(f"D0 (sensor INT)     rising edges: {len(d0_r)}")
    print(f"D1 (decision GPIO)  rising edges: {len(d1_r)}")
    print(f"D2 (solenoid cmd)   rising edges: {len(d2_r)}")
    print(f"A0 (piezo plunger)  rising crossings: {len(a0_r)}")
    print(f"A1 (piezo breakout) rising crossings: {len(a1_r)}")
    print()

    if len(a1_r) == 0:
        print("No piezo events detected. Lower --threshold-v or check wiring.")
        return

    rows = []
    for t_a1 in a1_r:
        t_d1 = next_after(d1_r, t_a1)
        t_a0 = previous_before(a0_r, t_a1)
        t_d2 = previous_before(d2_r, t_a1)

        if t_d1 is None:
            continue  # no decision after this trigger

        latency_us       = (t_d1 - t_a1) * 1e6
        prop_us          = (t_a1 - t_a0) * 1e6 if t_a0 is not None else None
        sol_delay_us     = (t_a0 - t_d2) * 1e6 if (t_a0 is not None and t_d2 is not None) else None

        rows.append({
            "t_d2_solenoid_cmd_s": f"{t_d2:.9f}" if t_d2 is not None else "",
            "t_a0_plunger_s":      f"{t_a0:.9f}" if t_a0 is not None else "",
            "t_a1_breakout_s":     f"{t_a1:.9f}",
            "t_d1_decision_s":     f"{t_d1:.9f}",
            "solenoid_delay_us":   f"{sol_delay_us:.2f}" if sol_delay_us is not None else "",
            "propagation_us":      f"{prop_us:.2f}" if prop_us is not None else "",
            "latency_pipeline_us": f"{latency_us:.2f}",
        })

    print(f"Matched events: {len(rows)}")
    if not rows:
        print("No latency pairs computed. Check ordering of events.")
        return

    with open(args.out_csv, "w") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {args.out_csv}")
    print()

    latencies = sorted(float(r["latency_pipeline_us"]) for r in rows)
    n = len(latencies)
    print("=== Wire-level pipeline latency (A1 -> D1) ===")
    print(f"n      = {n}")
    print(f"min    = {latencies[0]:.2f} us")
    print(f"p25    = {latencies[n//4]:.2f} us")
    print(f"median = {latencies[n//2]:.2f} us")
    print(f"mean   = {sum(latencies)/n:.2f} us")
    print(f"p75    = {latencies[3*n//4]:.2f} us")
    print(f"max    = {latencies[-1]:.2f} us")

    sol_delays = [float(r["solenoid_delay_us"]) for r in rows if r["solenoid_delay_us"]]
    if sol_delays:
        sol_delays.sort()
        n2 = len(sol_delays)
        print()
        print("=== Solenoid actuation delay (D2 -> A0) ===")
        print(f"n      = {n2}")
        print(f"min    = {sol_delays[0]:.2f} us")
        print(f"median = {sol_delays[n2//2]:.2f} us")
        print(f"max    = {sol_delays[-1]:.2f} us")


if __name__ == "__main__":
    main()
