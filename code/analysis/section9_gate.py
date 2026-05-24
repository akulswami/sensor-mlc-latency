#!/usr/bin/env python3
"""
Section 9: Window length selection via parity gate.

Loads S4-prime (w=75), S5 (w=25), S6 (w=200) silicon classifiers.
Computes per-window accuracy on still+motion combined.
Selects final window: max(accuracy), ties broken by depth (min wins).
"""
import csv
from pathlib import Path

def load_silicon_csv(csv_path):
    """Load silicon_raw.csv: t_monotonic_s, mlc_src columns."""
    rows = []
    with open(csv_path) as f:
        r = csv.reader(f)
        # Skip comment lines
        while True:
            line = next(r)
            if line[0].startswith('t_monotonic'):
                break
        # Now read data
        for row in r:
            if len(row) >= 2:
                try:
                    rows.append({
                        'timestamp': float(row[0]),
                        'mlc_src': int(row[1])
                    })
                except ValueError:
                    continue
    return rows

def load_accel_csv(csv_path):
    """Load accel.csv: timestamp, x, y, z columns."""
    rows = []
    with open(csv_path) as f:
        r = csv.reader(f)
        next(r)  # skip header
        for row in r:
            if len(row) >= 4:
                try:
                    rows.append({
                        'timestamp': float(row[0]),
                        'x': float(row[1]),
                        'y': float(row[2]),
                        'z': float(row[3])
                    })
                except ValueError:
                    continue
    return rows

def compute_motion_label(accel_rows, window_size=75):
    """Compute ground truth motion vs still using sliding variance.
    
    Still: low variance (< 0.01 g^2 per axis)
    Motion: high variance (>= 0.01 g^2 per axis, any axis)
    """
    labels = []
    for i in range(len(accel_rows)):
        start = max(0, i - window_size // 2)
        end = min(len(accel_rows), i + window_size // 2)
        window = accel_rows[start:end]
        
        if len(window) < window_size // 4:
            labels.append(None)
            continue
        
        xs = [w['x'] for w in window]
        ys = [w['y'] for w in window]
        zs = [w['z'] for w in window]
        
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        mean_z = sum(zs) / len(zs)
        
        var_x = sum((x - mean_x)**2 for x in xs) / len(xs)
        var_y = sum((y - mean_y)**2 for y in ys) / len(ys)
        var_z = sum((z - mean_z)**2 for z in zs) / len(zs)
        
        is_motion = (var_x >= 0.01 or var_y >= 0.01 or var_z >= 0.01)
        labels.append(1 if is_motion else 0)
    
    return labels

def compute_accuracy(silicon_rows, ground_truth_labels):
    """Compare MLC source output (0=still, 4=motion) vs ground truth."""
    if len(silicon_rows) != len(ground_truth_labels):
        print(f"  WARNING: row count mismatch ({len(silicon_rows)} vs {len(ground_truth_labels)})")
    
    correct = 0
    total = 0
    for i in range(min(len(silicon_rows), len(ground_truth_labels))):
        if ground_truth_labels[i] is None:
            continue
        mlc_class = 1 if silicon_rows[i]['mlc_src'] == 4 else 0  # 4=motion, else=still
        if mlc_class == ground_truth_labels[i]:
            correct += 1
        total += 1
    
    return correct / total if total > 0 else 0.0

def run_gate(session_dir, window_name):
    """Run §9 gate on one session (still + motion combined)."""
    session_path = Path(session_dir)
    
    still_accel = load_accel_csv(session_path / 'still' / 'accel.csv')
    still_silicon = load_silicon_csv(session_path / 'still' / 'silicon_raw.csv')
    
    motion_accel = load_accel_csv(session_path / 'motion' / 'accel.csv')
    motion_silicon = load_silicon_csv(session_path / 'motion' / 'silicon_raw.csv')
    
    all_accel = still_accel + motion_accel
    all_silicon = still_silicon + motion_silicon
    
    print(f"\n{window_name}:")
    print(f"  Still: {len(still_accel)} accel, {len(still_silicon)} silicon")
    print(f"  Motion: {len(motion_accel)} accel, {len(motion_silicon)} silicon")
    print(f"  Total: {len(all_accel)} accel, {len(all_silicon)} silicon")
    
    ground_truth = compute_motion_label(all_accel)
    acc = compute_accuracy(all_silicon, ground_truth)
    
    valid_labels = sum(1 for x in ground_truth if x is not None)
    correct = int(acc * valid_labels)
    print(f"  Accuracy: {acc:.4f} ({correct} / {valid_labels} correct)")
    
    return acc

results = {}
results['w25'] = run_gate('data/training/2026-05-24-S5', 'w=25 (S5)')
results['w75'] = run_gate('data/training/2026-05-24-S4-prime', 'w=75 (S4-prime)')
results['w200'] = run_gate('data/training/2026-05-24-S6', 'w=200 (S6)')

print("\n=== §9 Gate Results ===")
for w in ['w25', 'w75', 'w200']:
    print(f"{w}: {results[w]:.4f}")

winner = max(results.items(), key=lambda x: x[1])
print(f"\nWINNER: {winner[0]} with accuracy {winner[1]:.4f}")
