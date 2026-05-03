"""
extract_latency.py

Extract wire-level latency pairs from a Saleae digital-export CSV.

Format expected (Saleae Logic 2 default digital export):
    Time [s], Channel 0, Channel 1, ...
    Rows are state-change events, not uniform samples.

Convention used here:
    Channel 0 = D0 = sensor INT (start of event)
    Channel 1 = D1 = decision GPIO (end of event)

For each rising edge on D0, finds the first rising edge on D1 that
occurs before the next D0 rising edge. Reports the per-pair latency
in microseconds.

Usage:
    python3 extract_latency.py <input.csv> [<output.csv>]

If <output.csv> is given, writes one row per matched pair as:
    pair_index, t_d0_seconds, t_d1_seconds, latency_us
"""
import csv
import sys
from pathlib import Path


def parse_events(path):
    events = []
    with open(path) as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            t = float(row[0])
            d0 = int(row[1])
            d1 = int(row[2])
            events.append((t, d0, d1))
    return events


def find_rising_edges(events, channel_index):
    """channel_index: 1 for D0, 2 for D1 (matches tuple position)."""
    times = []
    prev = events[0][channel_index]
    for ev in events[1:]:
        cur = ev[channel_index]
        if cur == 1 and prev == 0:
            times.append(ev[0])
        prev = cur
    return times


def match_pairs(d0_times, d1_times):
    """For each D0 rising, find first D1 rising before next D0 rising."""
    pairs = []
    unmatched = 0
    for i, t_d0 in enumerate(d0_times):
        t_bound = d0_times[i+1] if i+1 < len(d0_times) else float('inf')
        matched = None
        for t_d1 in d1_times:
            if t_d0 < t_d1 < t_bound:
                matched = t_d1
                break
        if matched is not None:
            pairs.append((t_d0, matched, (matched - t_d0) * 1e6))
        else:
            unmatched += 1
    return pairs, unmatched


def summarize(latencies_us):
    s = sorted(latencies_us)
    n = len(s)
    if n == 0:
        return
    print(f"n      = {n}")
    print(f"min    = {min(s):.2f} us")
    print(f"p25    = {s[n//4]:.2f} us")
    print(f"median = {s[n//2]:.2f} us")
    print(f"mean   = {sum(s)/n:.2f} us")
    print(f"p75    = {s[3*n//4]:.2f} us")
    if n >= 20:
        print(f"p95    = {s[int(0.95*n)]:.2f} us")
    print(f"max    = {max(s):.2f} us")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 extract_latency.py <input.csv> [<output.csv>]")
        sys.exit(1)

    in_path = sys.argv[1]
    events = parse_events(in_path)
    d0_times = find_rising_edges(events, 1)
    d1_times = find_rising_edges(events, 2)
    pairs, unmatched = match_pairs(d0_times, d1_times)

    print(f"Input: {in_path}")
    print(f"D0 risings: {len(d0_times)}")
    print(f"D1 risings: {len(d1_times)}")
    print(f"Matched pairs: {len(pairs)}")
    print(f"Unmatched D0 risings: {unmatched}")
    print()
    summarize([p[2] for p in pairs])

    if len(sys.argv) >= 3:
        out_path = sys.argv[2]
        with open(out_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['pair_index', 't_d0_seconds', 't_d1_seconds', 'latency_us'])
            for i, (t0, t1, lat) in enumerate(pairs, start=1):
                writer.writerow([i, f"{t0:.9f}", f"{t1:.9f}", f"{lat:.3f}"])
        print(f"\nWrote {len(pairs)} pairs to {out_path}")


if __name__ == '__main__':
    main()
