#!/usr/bin/env python3
import csv
import json
from pathlib import Path
import statistics

def load_saleae_csv(csv_path):
    edges = {'d0_rising': [], 'd2_falling': []}
    
    with open(csv_path) as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        
        prev_d0, prev_d2 = 0, 0
        for row in reader:
            if len(row) < 3:
                continue
            try:
                t = float(row[0])
                ch0 = int(row[1])
                ch2 = int(row[2])
            except ValueError:
                continue
            
            if ch0 == 1 and prev_d0 == 0:
                edges['d0_rising'].append(t)
            if ch2 == 0 and prev_d2 == 1:
                edges['d2_falling'].append(t)
            
            prev_d0 = ch0
            prev_d2 = ch2
    
    return edges

def compute_latencies(edges):
    latencies = []
    d0_rising = sorted(edges['d0_rising'])
    d2_falling = sorted(edges['d2_falling'])
    
    for d0_t in d0_rising:
        matching_falls = [t for t in d2_falling if t > d0_t]
        if matching_falls:
            d2_t = matching_falls[0]
            latency_us = (d2_t - d0_t) * 1e6
            if 0 < latency_us < 100000:
                latencies.append(latency_us)
    
    return latencies

def compute_stats(latencies):
    if not latencies:
        return None
    sorted_lat = sorted(latencies)
    n = len(latencies)
    return {
        'count': n,
        'mean': statistics.mean(latencies),
        'median': statistics.median(latencies),
        'stdev': statistics.stdev(latencies) if n > 1 else 0,
        'min': min(latencies),
        'max': max(latencies),
        'p25': sorted_lat[n // 4],
        'p75': sorted_lat[3 * n // 4],
        'p95': sorted_lat[int(0.95 * n)],
    }

def main():
    base_path = Path('data/training')
    sessions = ['2026-05-24-S4-prime', '2026-05-24-S5', '2026-05-24-S6']
    
    all_results = {}
    
    for session in sessions:
        session_path = base_path / session
        print(f"\n=== {session} ===")
        
        for state in ['still', 'motion']:
            state_path = session_path / state
            csv_file = state_path / 'saleae_timing.csv'
            
            if not csv_file.exists():
                print(f"  {state}: MISSING")
                continue
            
            edges = load_saleae_csv(csv_file)
            latencies = compute_latencies(edges)
            stats = compute_stats(latencies)
            
            if stats:
                print(f"  {state}: n={stats['count']}")
                print(f"    Median: {stats['median']:.2f} µs")
                print(f"    Mean: {stats['mean']:.2f} µs (σ={stats['stdev']:.2f})")
                print(f"    P25-P75: {stats['p25']:.2f}-{stats['p75']:.2f} µs")
                print(f"    P95: {stats['p95']:.2f} µs")
                
                all_results[f"{session}/{state}"] = {
                    'latencies': latencies,
                    'stats': stats
                }
    
    print(f"\n✓ Analyzed {len(all_results)} datasets")
    with open('code/analysis/latency_results.json', 'w') as f:
        output = {}
        for key, val in all_results.items():
            output[key] = val['stats']
        json.dump(output, f, indent=2)
    
    print("✓ Results saved: code/analysis/latency_results.json")

if __name__ == '__main__':
    main()
