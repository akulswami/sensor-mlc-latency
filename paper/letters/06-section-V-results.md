# §V. Results

The confirmatory campaign collected 4,860 candidate trials across 81 blocks of 300 s; 4,770 (98.15%) satisfied the pre-registered inclusion criteria. All blocks achieved 100% jetson_clocks effectiveness under MAXN_SUPER_JC. Per-cell latency distributions appear in **Fig. 1**; summary statistics in **Table I**.

## V.A Confirmatory tests

**H1' (host < MLC at idle): SUPPORTED.** Host idle median (321.7 µs) is 359 µs below MLC bank-switch idle (681.5 µs), a 2.1× host speedup. The Hodges-Lehmann shift is ΔHL = −359.3 µs, 95% bootstrap CI [−373.6, −352.5] (10,000 iterations); Mann-Whitney p = 1.87 × 10⁻¹⁷⁰, rejected at the Holm-Bonferroni threshold across the {H1', H2', H3', H6', H7'} family.

**H2' (host < MLC under I²C contention): SUPPORTED.** With three concurrent i2c_hammer processes on bus 7, host median rises to 574.5 µs and MLC to 1,325.4 µs; the shift grows to ΔHL = −753.2 µs [−760.0, −746.7] (2.3× advantage), p = 2.33 × 10⁻¹⁷⁰.

**H3' (MLC degrades more than host): SUPPORTED.** The Δ-of-Δ contrast is +391.1 µs [+372.8, +400.0], p = 1.00 × 10⁻⁴. The MLC degrades by +611.7 µs (+90%, idle→contention) versus the host's +249.2 µs (+78%): the MLC's three-transaction I²C read protocol amplifies the contention penalty.

**H5' (CPU stress null for host latency): SUPPORTED.** Host median rises only from 321.7 µs (idle) to 345.0 µs (stress); a TOST against the pre-registered ±30 µs margin gives +23.3 µs, 90% CI [+22.7, +23.7] ⊂ [−30, +30]. Equivalence is declared; a 208 Hz polling loop does not contend with stress-ng for CPU time.

**H6' (CPU stress positive for energy): SUPPORTED.** Mean VDD_IN (INA3221 via tegrastats) rises from 5,206 mW (idle) to 8,626 mW (stress): +3,420 mW [+3,410, +3,429], exceeding the pre-registered +1,000 mW threshold threefold. The power axis distinguishes CPU stress unambiguously where the latency axis (H5') cannot.

**H7' (MLC stability degrades under contention): FALSIFIED, direction opposite.** The fraction of stimulus windows with exactly one D1 rising edge is 97.22% (525/540) at idle versus 98.89% (534/540) under contention, a +1.67 percentage-point *increase* rather than the predicted decrease. Fisher's exact test in the pre-registered direction gives p = 0.9874 (two-sided p = 0.0755). H7' is formally falsified in pre-registration v7.10 [4]. I²C contention slows the MLC pipeline (H2', H3') but does not degrade the silicon's classifier reliability.

## V.B Multimodal latency distributions

**Fig. 1** reveals multimodal structure in both MLC pipelines. The mlc/idle distribution is bimodal (mean 866.6 µs exceeds median 681.5 µs, with p95 reaching 1,780.7 µs), and mlc-binary/idle shows three modes near 60, 240, and 470 µs. Under contention and stress both collapse to tighter distributions, consistent with idle-state variance reflecting the kernel/I²C scheduler's full timing-edge variability when not load-pinned. We report this as exploratory; the mechanism requires kernel-level (ftrace) instrumentation beyond this study's scope.

## V.C MLC decision cadence

Inter-trial D0 (INT1) gaps (n = 3,086) cluster sharply at integer multiples of T = 706.5 ms with empty inter-peak bins. T is consistent with approximately one-quarter of the MLC's 75-sample, 26 Hz window period (2.885 s / 4 = 0.721 s; empirical peak 0.7065 s, a ~2% difference). In this configuration, the quantization is consistent with the MLC updating only on its internal window-cadence clock rather than the host read path; we did not find it described in ST application notes [2] or the LSM6DSOX datasheet.

## V.D Exclusion rates

No cell exceeded the pre-registered 10% exclusion ceiling (highest: mlc/idle, 2.78%). The dominant exclusion category (68 of 90 trials) was multiple D1 edges per window, attributable to the 706.5 ms cadence interacting with stimulus-window boundaries. The single-rising-edge inclusion requirement is, by construction, the same criterion as the H7' classifier-stability outcome (Section V.A); the per-cell included and stable-window counts are one measurement reported on two axes.
