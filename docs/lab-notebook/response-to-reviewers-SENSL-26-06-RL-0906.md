# Response to Reviewers — SENSL-26-06-RL-0906

**"Wire-Level Interrupt-to-Decision Latency of On-Sensor MLC versus Host Inference on the NVIDIA Jetson Orin Nano: A Pre-Registered Measurement Study"**

We thank both reviewers for a thorough and technically demanding review. Every substantive point raised has been addressed, either by a correction or expansion in the manuscript, or — where a point concerns material outside the paper's 4-page limit — directly in this response. We address each point in order below, referencing the specific section of the revised manuscript where applicable.

---

## Response to Reviewer 1

### Point 1 — Data-rate / window-length confound

> *"The host pipeline consumes accelerometer data at 208 Hz... whereas the MLC operates at 26 Hz... This is a first-order confound, and it cannot be resolved by rephrasing the text. It requires a re-run experiment with the host decimated to a 26 Hz equivalent."*

**Response:** This concern is resolved directly, without a re-run. During this revision we identified that the MLC's actual configured output data rate is 104 Hz, not 26 Hz — the 26 Hz figure in the original submission was drawn from the `gyroscope_odr` field of the ST MEMS Studio export, a different register than the one governing the MLC's accelerometer-driven decision window. With the corrected rate, host window and MLC window are both 721.2 ms: `parity_core`'s `pc_step` implements a 2:1 decimation of the host sample stream, equalizing the two windows to a common period. The data-rate mismatch the reviewer identified does not exist in the actual experimental configuration; it was a reporting error in the original submission, now corrected.

**Manuscript changes:** §III.A (rate correction, with provenance note on the `gyroscope_odr` field), §III.B (decimation sentence), §V.C and Introduction contribution 3 (cadence figure corrected from the erroneous 26 Hz derivation to the verified 104 Hz window period).

---

### Point 2 — mlc-binary idle multimodality

> *"The control (MLC-binary) pipeline shows unexplained, load-dependent multimodality (slower at idle than under contention)... This anomaly... demands systematic investigation."*

**Response:** We conducted a targeted follow-up investigation testing process-affinity pinning and IRQ-routing as candidate causes. Per our pre-registration's standing rule (v7.13), analysis branches are timestamped in our Zenodo chain either before the data they interpret or explicitly labeled as post-hoc; here, the investigation's data were collected 2026-09-21, and the corresponding amendments (v7.12, DOI 10.5281/zenodo.22907481; correction v7.13, DOI 10.5281/zenodo.22907600) were formalized into the chain immediately afterward, on 2026-09-22. We label this analysis branch as post-hoc rather than prospectively pre-registered, consistent with our own disclosure standard.

- **Process affinity:** 232/232 trials with the process pinned to a fixed CPU core fell under 150 µs, versus 70.1% ≥150 µs in the original (unpinned) campaign — a highly significant difference in the *opposite* direction from what an affinity-based explanation would predict (Mann-Whitney p ≈ 1.8×10⁻⁷⁵, Hodges-Lehmann shift −184.4 µs). A same-session unpinned control block showed no difference from the pinned blocks (p = 0.673), ruling out session-to-session drift as a confound.
- **IRQ routing:** Confirmed via direct kernel interrogation that Tegra's chained GPIO IRQs are not steerable (`smp_affinity` writes return EIO); INT1 is fixed to CPU0 regardless of process placement. This candidate is excluded on architectural grounds, not just empirically.

We report this honestly as a **systematic negative result**, not a resolved anomaly: the root cause of the idle-session multimodality remains unidentified. We do not believe this affects the paper's primary conclusions, which rest on the unpinned confirmatory campaign data throughout, and we have added the multimodal-distribution caveat and candidate-mechanism discussion (bus arbitration, gpiod chardev poll state, MLC-cadence interaction) as a labeled exploratory finding.

**Manuscript changes:** §V.B (multimodal distribution, explicitly labeled exploratory). Full candidate-mechanism discussion, including the two now-excluded hypotheses and the three remaining untested candidates, is provided in the supplementary material (S3) referenced from this letter, since it did not fit within the 4-page limit alongside this revision's other required additions.

---

### Point 3 — Absence of a wire-level timing diagram

> *"For a 'wire-level' study, the absence of logic-analyzer traces, or a timing diagram showing INT1/D1 edges and the three I²C transactions, is a glaring omission. A single figure would have added enormous credibility."*

**Response:** We agree, and built the requested figure — reproduced below. It shows the measured D0 (INT1) and D1 (decision) wire-level edges for one representative trial (trial 43), annotated with the measured D0→D1 gap (481.8 µs), D0 pulse width (9.01 ms), and D1 pulse width (3.24 µs), alongside a clearly-separated schematic panel depicting the three-transaction I²C bank-switch sequence (write `FUNC_CFG_ACCESS`, read `MLC0_SRC`, write `FUNC_CFG_ACCESS` back) that occurs inside that interval. The schematic panel is explicitly labeled as such and is not drawn to a measured timescale, since our instrumentation captures D0/D1/D2 at the wire level but does not separately trace the I²C bus (SDA/SCL) itself — consistent with the subtractive-comparison methodology already described in §VI.A, where the mlc-minus-mlc-binary latency difference is used to isolate I²C read overhead precisely because it does not require a direct bus trace.

IEEE Sensors Letters enforces a strict 4-page limit. Incorporating this revision's other required additions — the rate correction, the expanded discussion addressing both reviewers' remaining points, the INT1 configuration disclosure, and the corrected percentile statistics — left no remaining page budget to add a new figure without displacing other required content. We tested this empirically rather than assuming it: compacting the figure by up to 45% in height (merging and shrinking panels while confirming legibility at actual print resolution) still did not bring the manuscript under 4 pages in combination with the other required changes, and no combination of trimming existing accepted text was sufficient to make room either, due to a fixed pagination threshold in the bibliography's keep-together formatting that further compaction could not cross.

The underlying evidence this figure illustrates remains fully present in the manuscript in textual and tabular form: Fig. 1(c) isolates the I²C read overhead via the mlc-minus-mlc-binary subtractive comparison (§VI.A), and the three-transaction sequence is specified with register-level detail and cited against AN5259 (§III.B, §VI.D). We present the actual figure here rather than only describing it, and would be glad to incorporate it into the manuscript itself, including at the cost of trimming further discussion text, if the editor or reviewer judges its in-text inclusion necessary despite the page constraint.

![Fig. R1. One representative trial (trial 43, block mlc001). (a) Measured D0 (INT1), D1 (decision), and D2 (servo PWM) wire-level edges: D0→D1 gap 481.8 µs, D0 pulse 9.01 ms, D1 pulse 3.24 µs — illustrative single-trial timing, not a campaign statistic. (b) The three-transaction I²C bank-switch read occurring inside that gap (write FUNC_CFG_ACCESS, read MLC0_SRC, write FUNC_CFG_ACCESS back); schematic only — no SDA/SCL capture exists for this trial, so the sequence is not drawn to a measured timescale.](../../paper/figures/figure_timing_diagram.png)

*Fig. R1. One representative trial (trial 43, block mlc001). (a) Measured D0 (INT1), D1 (decision), and D2 (servo PWM) wire-level edges: D0→D1 gap 481.8 µs, D0 pulse 9.01 ms, D1 pulse 3.24 µs — illustrative single-trial timing, not a campaign statistic. (b) The three-transaction I²C bank-switch read occurring inside that gap (write `FUNC_CFG_ACCESS`, read `MLC0_SRC`, write `FUNC_CFG_ACCESS` back); schematic only — no SDA/SCL capture exists for this trial, so the sequence is not drawn to a measured timescale.*

---

### Point 4 — n=532 vs. n=534 discrepancy (mlc/i2c-contention)

> *"In Table 1, the MLC/I²C-contention cell is reported as n = 532... However, Section V.A (H7′) reports 534/540... Either the inclusion count and the stability count are based on different criteria... or Table I contains an error."*

**Response:** These are two different, correctly-applied criteria, not an error. n = 532 is the **latency-included** count (540 candidate trials minus 8 exclusions: 5 multiple-D1-edge trials, 2 multiple-D0-before-D1 trials, 1 no-D1 trial), used throughout Table I and the confirmatory latency statistics. n = 534 (540 minus 6 exclusions) is the **single-D1-rising-edge stability count**, which is the specific criterion H7′ tests. The two counts differ because they answer different questions from an overlapping but non-identical set of exclusion categories. Both criteria and both resulting counts are now stated explicitly in the manuscript.

**Manuscript changes:** §III.D and §V.D now state both the inclusion criterion and the stability criterion explicitly, with the exclusion breakdown, resolving the ambiguity directly.

---

### Point 5 — No host-vs-MLC energy comparison

> *"The paper measures energy only as a manipulation check for CPU stress... and never compares host-inference energy vs. MLC-inference energy... The conclusion that the host is the better choice at 'only 359 µs earlier at idle' cannot be evaluated without the energy axis."*

**Response:** We evaluated host-vs-MLC energy at the Jetson platform-power level (INA3221, VDD_CPU_GPU_CV and VDD_IN rails):

> Jetson platform power (VDD_CPU_GPU_CV) differs between host and MLC pipelines by +31.1 mW [27.8, 34.4] at idle (p ≈ 8.4×10⁻⁹²) and +7.3 mW under I²C contention (p ≈ 5.5×10⁻⁸). This comparison was added post-hoc in response to review; per the pre-registration's standing rule (v7.13), it is labeled as such rather than presented as part of the original confirmatory design. Under CPU stress, the 95% CI spans [−28.8, 14.6] mW and includes zero despite p ≈ 1.4×10⁻⁸ — expected at this sample size, where the Mann-Whitney U test is sensitive to distributional differences beyond central tendency; the confidence interval, not the p-value, is the practically relevant statistic here. VDD_IN replicates the idle effect at +37.3 mW [33.2, 41.4].

These are whole-platform power measurements, not an isolated host-classifier-vs-MLC comparison — the sensor's own current draw is not separately instrumented, and we did not repeat measurements on a representative MCU-class host (e.g., STM32); both are natural directions for follow-on work rather than achievable within this revision's window. We did not pursue direct sensor-level current measurement (e.g., via a Nordic PPK2) within the revision window; the platform-level comparison above directly answers the reviewer's core concern that no host-vs-MLC energy comparison previously existed.

The full numbers, including all three conditions and both power rails, are provided in the project's supplementary material (S2), referenced from the manuscript's linked code/data repository, since the full comparison did not fit within the 4-page limit as in-text prose alongside this revision's other required additions.

**Manuscript changes:** None in-text beyond what is already noted (H6′ remains the CPU-stress manipulation check, unchanged and now explicitly distinguished from this comparison — see Reviewer 2, Point 5, below).

---

## Response to Reviewer 2

### Point 1 — Is INT1 configured identically across pipelines?

> *"Clearly state whether INT1 is configured identically during host, MLC and mlc-binary experiments."*

**Response:** It is not, by design, and this is now stated explicitly: the host pipeline sets `INT1_CTRL = 0x01` (accelerometer DRDY, 208 Hz), interrupting on every sample; the mlc and mlc-binary pipelines set `INT1_CTRL = 0x00` and instead route the MLC's decision-ready signal to INT1 via `MD1_CFG = 0x02`. This asymmetry is intrinsic to each pipeline's decision source (raw sample vs. embedded classifier output) and is now disclosed directly rather than left implicit.

**Manuscript changes:** §III.B, new paragraph.

---

### Point 2 — Report p95, p99, and max for every cell

> *"Report p95, p99 and maximum latency for every cell, not only medians/IQRs. This is particularly important given the multimodal distributions."*

**Response:** A full percentile table (n, median, p25, p75, p95, p99, max, and mean for all nine pipeline×condition cells) is provided in the project's supplementary material (S1), computed with a single canonical method (linear interpolation, the numpy default) applied consistently throughout. During this revision we identified and corrected an internal inconsistency: the originally submitted Table I used a different interpolation convention (nearest-rank) than subsequent analysis used elsewhere, producing small discrepancies in several p25/p75/p95 values (on the order of 0.1–2 µs). This has been corrected throughout the manuscript for internal consistency; Table I's IQR values in the revised manuscript now match the canonical method used in the supplementary percentile table.

**Manuscript changes:** Table I values corrected for method consistency; full p95/p99/max table in supplementary material (S1), referenced from the manuscript's linked repository.

---

### Point 3 — Logarithmic or common-axis figure for Fig. 1

> *"Consider reporting latency on a logarithmic or common y-axis in an additional figure; the different scales in Fig. 1 make direct visual comparison difficult."*

**Response:** Fig. 1 has been redrawn with a single shared log-scale y-axis across all three pipeline panels, replacing the original three independently-capped linear axes. Box position is now directly comparable across panels without per-panel capping or "outliers above cap" text annotations — every data point is shown in-frame at true scale.

**Manuscript changes:** Fig. 1 replaced; caption updated to describe the shared-axis, no-capping presentation.

---

### Point 4 — Are the three I²C transactions necessarily required?

> *"Clarify whether the three I2C operations are necessarily required for every application or whether software architecture, cached bank state, SPI access, interrupt configuration, or different LSM6DSOX-family devices can change this overhead."*

**Response:** We address each of the five variables named:

- **Software architecture / cached bank state:** The three-transaction bank-switch cost reflects this implementation's choice to restore the user bank after every `MLC0_SRC` read, not an unconditional silicon requirement. An application that tolerates remaining in the embedded-function bank between reads, or that caches bank state and defers the switch-back until a user-bank register is actually needed, could avoid at least one of the three transactions; we did not implement or measure this variant.
- **SPI access:** Attempted on this platform before an unrelated hardware bring-up failure led us to adopt I²C (pre-registration amendment, 2026-05-01). SPI would reduce the fixed per-transaction protocol overhead of I²C register reads generally, but we did not measure this pipeline over SPI and report no quantified speedup.
- **Different LSM6DSOX-family devices:** Successor parts (LSM6DSV16X, LSM6DSO32X) retain the same MLC and bank-switched register architecture (§II.A), so the overhead is not specific to this part and should recur on those as well.
- **Interrupt configuration:** We find no basis in AN5259, the datasheet, or our own measurements for a claim that interrupt configuration changes this overhead, and make none.

**Manuscript changes:** §VI.D expanded to cover the software-architecture/cached-bank-state, SPI, and successor-parts points explicitly, within the page budget; the interrupt-configuration point (for which our answer is that we found no basis for a claim either way) is addressed here rather than in-text, since it did not fit within the 4-page limit alongside the other required additions.

---

### Point 5 — H6 vs. a genuine host/MLC energy comparison

> *"H6 measures increased Jetson input power under CPU stress; it does not demonstrate an energy comparison between the host classifier and the MLC. Please make this distinction explicit."*

**Response:** This distinction is now explicit. H6′ remains, unchanged, the CPU-stress manipulation check: a single-condition comparison (stress vs. non-stress) confirming that the CPU-stress condition registers on the power axis, independent of pipeline. The newly added post-hoc comparison (see our response to Reviewer 1, Point 5, above) separately measures host-vs-MLC platform power across all three conditions — idle, contention, and stress — and is the comparison that directly answers this reviewer's request. Both are now clearly distinguished in the manuscript text and in the supplementary material.

**Manuscript changes:** §V.A (H6′ description clarified as a manipulation check); energy-comparison distinction stated in the supplementary material (S2) referenced from the repository.

---

### Point 6 — Graphical abstract wording

> *"The graphical abstract should likewise be worded carefully so that the 2.1–2.3× result is understood as the measured D0-to-D1 configuration rather than universal on-sensor-versus-host inference performance."*

**Response:** The graphical abstract headline has been rescoped to name the specific platform and protocol rather than implying a general claim:

> *"On the LSM6DSOX (I²C, Jetson Orin Nano), host inference is 2.1–2.3× faster than the on-sensor MLC; the I²C bank-switch read protocol, not classification, dominates."*

**Manuscript changes:** `make_graphical_abstract.py`, title text.

---

## Additional corrections made during this revision

In the course of addressing the points above, we identified and corrected the following, none of which were raised directly by either reviewer:

1. **MLC operating rate:** Corrected from an erroneous 26 Hz (drawn from the wrong register in the original MEMS Studio export) to the verified 104 Hz configured rate, at all four sites in the manuscript where it appeared (Introduction, §II.A, §III.A, §V.C), with the derived 706.5 ms cadence figure and its "one-quarter of the window period" explanation corrected accordingly.
2. **Headline speedup scoping:** The original submission stated the 2.1–2.3× speedup held "under every tested condition." We found this did not hold under CPU stress (measured ratio 1.58–1.6×) and corrected the claim to be scoped accurately to idle and I²C-contention conditions, with the stress-condition result now stated and explained separately (§VI.A).
3. **Percentile-computation method:** Corrected an internal inconsistency between the interpolation method used in the originally submitted Table I and the method used elsewhere in the analysis, as noted above (Reviewer 2, Point 2).

We disclose these here in the interest of full transparency about all changes made between submissions, consistent with the pre-registration integrity standard the paper itself argues for.

---

*[Draft for review — verify the figure embed path once placed in the repository, and confirm before submission whether ScholarOne's Step 6 supports a general supplementary-material upload distinct from this response file; if not, S1/S2/S3 content referenced above should be attached to this document directly rather than left as an external repository link.]*
