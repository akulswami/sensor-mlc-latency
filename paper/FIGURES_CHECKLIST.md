# IEEE Sensors Letters Paper: Required Figures

## Paper Structure (§1–§7)

### §1–§3: Introduction & Design
**No figures required** (methodology is text-focused)

---

### §4–§5: Methods & Apparatus
**Figure 1: Apparatus Diagram** ✓ COMPLETE
- File: `paper/figures/apparatus_ai_generated_v2_final.png`
- Shows: Jetson, servo rig (±90°), LSM6DSOX, PCA9685, Saleae Logic Pro 8
- Status: Publication-ready

---

### §6: Results

#### **Figure 2: Accuracy Comparison (§9 Gate Results)**
- **Data source**: `data/training/2026-05-24-S{4-prime,5,6}/**/silicon_raw.csv`
- **Content**: Bar chart showing accuracy for w=25, w=75, w=200
  - Still class accuracy (%)
  - Motion class accuracy (%)
  - Overall accuracy (%)
  - Error counts (false positives, false negatives)
- **Visual**: 3 bars (one per window), color-coded, with error annotations
- **Reference**: code/analysis/section9_gate.py (produces accuracy metrics)
- **Status**: DATA AVAILABLE, FIGURE NEEDED

#### **Figure 3: Confusion Matrix or Classification Breakdown (§9 Gate)**
- **Data source**: Same silicon_raw.csv from S4-prime/S5/S6
- **Content**: 2×2 confusion matrices (Still vs Motion) for each window length
  - True Positives (TP), False Positives (FP)
  - False Negatives (FN), True Negatives (TN)
  - Per-class precision, recall, F1-score
- **Visual**: 3 heatmaps side-by-side (w=25, w=75, w=200)
- **Status**: DATA AVAILABLE, FIGURE NEEDED

#### **Figure 4: Latency Distribution (MLC vs Host, No Stress)**
- **Data source**: `data/training/2026-05-24-S*/*/saleae.sal` (timing edges)
- **Content**: Histogram or box plot of wire-level latency for each pipeline
  - MLC latency (median, percentiles: 25th, 75th, 95th)
  - Host latency (median, percentiles: 25th, 75th, 95th)
  - Distribution shape (PDF/CDF)
- **Visual**: Side-by-side histograms or overlaid CDFs (MLC vs Host)
- **Status**: DATA AVAILABLE (Saleae captures), NEEDS EXTRACTION & PLOTTING

#### **Figure 5: Latency Under CPU Stress (Main Result)**
- **Data source**: Would require stress-ng runs (NOT YET COLLECTED)
- **Content**: Latency comparison matrix:
  - Rows: MLC, Host
  - Columns: No stress, stress-ng (matrixprod, 6 cores)
  - Heatmap or bar chart showing latency in each condition
  - Highlight decoupling effect (MLC stress-resistant, Host stress-sensitive)
- **Status**: BLOCKED — Stress experiment not yet run

#### **Figure 6: Latency Percentiles Summary (Secondary Outcomes)**
- **Data source**: Same Saleae captures as Figure 4
- **Content**: Table or bar chart of percentiles (p25, p50, p75, p95) for:
  - MLC (no stress)
  - Host (no stress)
  - Optionally: MLC (stress), Host (stress) if Figure 5 data available
- **Status**: DATA AVAILABLE, FIGURE NEEDED

---

### §7: Discussion
**No figures required** (discussion uses results from §6)

---

## Figure Summary Table

| Figure | Title | Data Source | Status | Priority |
|--------|-------|-------------|--------|----------|
| 1 | Apparatus: Motion-vs-Still Servo Rig | Photos + AI | ✓ DONE | — |
| 2 | Accuracy Comparison (w=25/75/200) | S4-prime/S5/S6 silicon_raw.csv | DATA READY | HIGH |
| 3 | Confusion Matrices (§9 Gate) | S4-prime/S5/S6 silicon_raw.csv | DATA READY | HIGH |
| 4 | Latency Distribution (No Stress) | S4-prime/S5/S6 saleae.sal | DATA READY | HIGH |
| 5 | Latency Under CPU Stress | NOT COLLECTED YET | BLOCKED | CRITICAL |
| 6 | Latency Percentiles Summary | S4-prime/S5/S6 saleae.sal | DATA READY | MEDIUM |

---

## Creation Order

### PHASE 1: Results Figures (Ready Now)
1. **Figure 2**: Accuracy bar chart (code/analysis/section9_gate.py has metrics)
2. **Figure 3**: Confusion matrices (extend section9_gate.py)
3. **Figure 4**: Latency histogram/CDF (extract from saleae.sal via code/analysis/extract_latency_v2.py)
4. **Figure 6**: Latency percentiles table (derived from Figure 4 data)

### PHASE 2: Critical Blocker
5. **Figure 5**: Stress latency comparison — REQUIRES running full latency experiment under stress-ng

---

## Notes

- **Saleae Logic .sal files**: Binary format, requires Saleae Logic software or python-saleae library to extract timing edges
- **Alternative**: Extract rising edges (INT1, solenoid) and compute latency deltas from session.json timestamps
- **Section9_gate.py**: Already computes accuracy; can be extended to output confusion matrices and visualizations
- **Latency extraction**: code/analysis/extract_latency_v2.py may need updating for current data format

