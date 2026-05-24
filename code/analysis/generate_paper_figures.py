#!/usr/bin/env python3
"""
Generate publication-ready figures for IEEE Sensors Letters paper.

Figures generated:
- Figure 2: Accuracy comparison (w=25, w=75, w=200)
- Figure 3: Confusion matrices (2x2 per window)
- Figure 6: Latency percentiles (if latency data available)
"""

import csv
import json
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# Set style for publication
plt.rcParams['font.size'] = 10
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.linewidth'] = 1.0
plt.rcParams['lines.linewidth'] = 1.5
plt.rcParams['figure.dpi'] = 300

def load_silicon_csv(csv_path):
    """Load silicon_raw.csv: t_monotonic_s, mlc_src columns."""
    rows = []
    with open(csv_path) as f:
        r = csv.reader(f)
        while True:
            line = next(r)
            if line[0].startswith('t_monotonic'):
                break
        for row in r:
            if len(row) >= 2:
                try:
                    rows.append(int(row[1]))
                except ValueError:
                    continue
    return rows

def compute_metrics(silicon_rows, ground_truth):
    """Compute confusion matrix and metrics."""
    tp = fp = fn = tn = 0
    for i in range(min(len(silicon_rows), len(ground_truth))):
        if ground_truth[i] is None:
            continue
        mlc_class = 1 if silicon_rows[i] == 4 else 0
        gt_class = ground_truth[i]
        
        if mlc_class == 1 and gt_class == 1:
            tp += 1
        elif mlc_class == 1 and gt_class == 0:
            fp += 1
        elif mlc_class == 0 and gt_class == 1:
            fn += 1
        else:
            tn += 1
    
    total = tp + fp + fn + tn
    accuracy = (tp + tn) / total if total > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    return {
        'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
        'accuracy': accuracy, 'precision': precision, 'recall': recall, 'f1': f1,
        'total': total
    }

def generate_figure_2_accuracy():
    """Figure 2: Accuracy bar chart for w=25, w=75, w=200."""
    print("Generating Figure 2: Accuracy Comparison...")
    
    # Hardcode results from section9_gate analysis (yesterday's results)
    windows = ['w=25\n(75 samples)', 'w=75\n(75 samples)', 'w=200\n(200 samples)']
    accuracies = [99.959, 99.572, 99.913]
    colors = ['#2ecc71', '#f39c12', '#3498db']
    
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(windows, accuracies, color=colors, edgecolor='black', linewidth=1.5, alpha=0.85)
    
    # Add value labels on bars
    for bar, acc in zip(bars, accuracies):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                f'{acc:.2f}%', ha='center', va='bottom', fontsize=11, fontweight='bold')
    
    ax.set_ylabel('Accuracy (%)', fontsize=12, fontweight='bold')
    ax.set_xlabel('Window Length', fontsize=12, fontweight='bold')
    ax.set_title('Figure 2: Classification Accuracy by Window Length\n(§9 Parity Gate: S4-prime, S5, S6)', 
                 fontsize=13, fontweight='bold', pad=15)
    ax.set_ylim([99.0, 100.1])
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.axhline(y=99.959, color='green', linestyle=':', alpha=0.5, label='w=25 (Winner)')
    
    # Add legend
    ax.legend(['w=25 Winner (99.959%)'], loc='lower right', fontsize=10)
    
    # Add notes
    ax.text(0.5, 0.02, 'Still + Motion combined; zero false positives in still class (w=25)', 
            transform=ax.transAxes, ha='center', fontsize=9, style='italic', color='#555')
    
    fig.tight_layout()
    fig.savefig('paper/figures/figure_2_accuracy_comparison.png', dpi=300, bbox_inches='tight')
    print("✓ Figure 2 saved: paper/figures/figure_2_accuracy_comparison.png")
    plt.close()

def generate_figure_3_confusion_matrices():
    """Figure 3: Confusion matrices for each window length."""
    print("Generating Figure 3: Confusion Matrices...")
    
    # Hardcode confusion matrix data from section9_gate results
    cm_data = {
        'w=25': {'tp': 58599, 'fp': 0, 'fn': 48, 'tn': 58578},
        'w=75': {'tp': 58571, 'fp': 442, 'fn': 58, 'tn': 58129},
        'w=200': {'tp': 58565, 'fp': 34, 'fn': 68, 'tn': 58535}
    }
    
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    fig.suptitle('Figure 3: Confusion Matrices by Window Length\n(Motion vs Still Classification)', 
                 fontsize=13, fontweight='bold', y=1.02)
    
    for idx, (window, cm) in enumerate(cm_data.items()):
        ax = axes[idx]
        
        # Normalize for heatmap
        total = cm['tp'] + cm['fp'] + cm['fn'] + cm['tn']
        cm_norm = np.array([
            [cm['tn']/total, cm['fp']/total],
            [cm['fn']/total, cm['tp']/total]
        ])
        
        im = ax.imshow(cm_norm, cmap='Blues', aspect='auto', vmin=0, vmax=1)
        
        # Add text annotations
        ax.text(0, 0, f'TN\n{cm["tn"]}', ha='center', va='center', color='black', fontsize=10, fontweight='bold')
        ax.text(1, 0, f'FP\n{cm["fp"]}', ha='center', va='center', color='darkred', fontsize=10, fontweight='bold')
        ax.text(0, 1, f'FN\n{cm["fn"]}', ha='center', va='center', color='darkred', fontsize=10, fontweight='bold')
        ax.text(1, 1, f'TP\n{cm["tp"]}', ha='center', va='center', color='darkgreen', fontsize=10, fontweight='bold')
        
        ax.set_xticks([0, 1])
        ax.set_yticks([0, 1])
        ax.set_xticklabels(['Still', 'Motion'])
        ax.set_yticklabels(['Still', 'Motion'])
        ax.set_ylabel('Ground Truth', fontsize=11, fontweight='bold')
        if idx == 0:
            ax.set_ylabel('Ground Truth', fontsize=11, fontweight='bold')
        ax.set_xlabel('Predicted', fontsize=11, fontweight='bold')
        ax.set_title(f'{window}\nAcc: {((cm["tp"]+cm["tn"])/total*100):.2f}%', fontsize=11, fontweight='bold')
    
    fig.tight_layout()
    fig.savefig('paper/figures/figure_3_confusion_matrices.png', dpi=300, bbox_inches='tight')
    print("✓ Figure 3 saved: paper/figures/figure_3_confusion_matrices.png")
    plt.close()

if __name__ == '__main__':
    generate_figure_2_accuracy()
    generate_figure_3_confusion_matrices()
    print("\n✓ Phase 1 figures generated successfully")
    print("  - Figure 2: Accuracy Comparison")
    print("  - Figure 3: Confusion Matrices")
    print("\nNext: Generate Figure 4 (Latency) and Figure 6 (Percentiles)")
