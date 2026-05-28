# §IV. Methodology and Statistical Treatment

## IV.A Pre-registration discipline

All hypotheses, exclusion criteria, statistical tests, and multiplicity-correction strategies were specified in a public, version-controlled pre-registration document with externally-timestamped Zenodo DOIs [REF-PREREG]. The current pre-registration chain contains twelve substantive amendments (v6.1 through v7.10) plus the original protocol commits (v2–v5). Every amendment was minted as a Zenodo release on the same calendar day as its corresponding git tag, providing an audit-defensible timestamp ordering.

Three pre-registered hypotheses were formally falsified during this study; each falsification is preserved on the public record:

- **H1** (median MLC < median host, no stress; v5): falsified at the 59-block btest scale; direction reversed (host median 351 µs vs MLC median 761 µs). Recorded in pre-registration v7.5 (Zenodo DOI 10.5281/zenodo.20389914), which simultaneously: (a) retired H2 as vacuously false (no MLC advantage to amplify), (b) restated H3 (CPU stress raises host latency) as a control with reversed expectation (becoming H5' = equivalence), (c) restated H4 (MLC decoupled from CPU load) as a control on the energy axis (becoming H6'), and (d) introduced the H1'-H6' family as the new pre-registered hypothesis set, with mlc-binary as a third pipeline.
- **H4'** (mlc idle energy < host idle energy, v7.5): falsified by the long-duration jc-effective smoke at blocks b700-b703; the apples-to-apples gap collapsed to −32 mW, well within the ±50 mW noise floor. Recorded in v7.6 (Zenodo DOI 10.5281/zenodo.20400025), which simultaneously introduced the `MAXN_SUPER_JC` nvpmodel as the required measurement configuration and added H7' (classifier-stability) as a secondary outcome.
- **H7'** (MLC classifier stability degrades under I²C contention, v7.6): falsified by the confirmatory campaign data; the observed direction is opposite to the prediction (stability is slightly *higher* under contention than at idle, two-sided Fisher p = 0.076 marginal). Recorded in v7.10 (Zenodo DOI 10.5281/zenodo.20420866).

Additionally, one pre-registered prediction (not a hypothesis) was falsified: v7.5 Change 1 predicted a smaller energy delta under nvpmodel mode 3 "because the baseline is near maximum CPU frequency." The H6' result (+3,420 mW under mode 3, comparable to the btest-scale finding) refuted this. The falsified prediction is recorded in `data/processed/confirmatory-2026-05-26/h6_energy_results.json`.

The discipline produced two ancillary methodological discoveries that we believe transfer:

1. **jc-effectiveness as a measurement-validity check.** During the long-duration smoke, the default nvpmodel 25W mode (mode 1) was empirically observed to re-assert `CPU_A78_MIN_FREQ = 729600` non-deterministically, even after `sudo jetson_clocks` had pinned min == max == 1728 MHz. The reassertion was undetectable without per-block `tegrastats` analysis. A custom `MAXN_SUPER_JC` nvpmodel (ID 3, defined in v7.6) and a post-hoc `jc_eff` ≥ 99% threshold together close this measurement-condition validity gap.

2. **Window-quantization-aware exclusion classification.** The MLC silicon fires INT1 at a quantized 706.5 ms cadence (§V.C); under bus contention, this cadence interacts with stimulus-window boundaries to produce `multiple_d1_in_window` exclusions. v7.6 Change 4 amended §11 of the protocol to classify such exclusions as classifier-instability observations (reported as data), distinct from measurement defects (which would trigger a campaign stop). Without this distinction, the i2c-contention cells of the confirmatory campaign would have triggered the §11 stop-condition despite producing scientifically valid measurements.

## IV.B Statistical tests and multiplicity correction

Each hypothesis is matched to a pre-registered test:

- **H1', H2'** (stochastic ordering between two independent samples): one-sided Mann-Whitney U test with `alternative='less'`. Effect estimate: Hodges-Lehmann shift with 95% percentile-bootstrap CI (10,000 resamples).
- **H3'** (interaction contrast, "(Δ_MLC − Δ_host) > 0 µs"): bootstrap of the contrast statistic. Computed by re-using the pre-registered §12 H2 bootstrap function with the MLC and host arguments swapped — an algebraic identity that yields the Δ-of-Δ distribution without writing a new test. 10,000 resamples; 95% percentile-bootstrap CI; p-value from the empirical resample distribution.
- **H5'** (equivalence within ±30 µs): TOST (two one-sided tests) on the median difference, bootstrap-based, 10,000 resamples, α = 0.05 on each side. The 90% CI on the median difference must lie strictly within [−30, +30] µs to declare equivalence.
- **H6'** (energy difference > 1,000 mW): Mann-Whitney U on VDD_IN samples, with 1/10 subsampling to reduce within-block autocorrelation in 100 ms-cadence INA3221 readings (lag-1 autocorrelation: 0.72 idle, 0.98 stress). Bootstrap CI on the diff-of-means (10,000 resamples on subsampled data). The +1,000 mW threshold is pre-registered as the "operationally meaningful" floor for distinguishing CPU stress from idle on a 25 W platform.
- **H7'** (stability ordering): two-by-two Fisher's exact test, one-sided in the pre-registered direction. Chi-square is reported as a reference statistic but Fisher's exact is the headline test because unstable counts per cell (6–15 of 540) fall in the regime where the chi-square asymptotic approximation can be inaccurate.

Multiplicity correction across the {H1', H2', H3', H6', H7'} family is by Holm-Bonferroni at family-wise α = 0.05. H5' uses TOST equivalence (90% CI vs ±30 µs margin) rather than a directional p-value test and is reported alongside the corrected family rather than within it; the H5' TOST p-values would in any case fall below the Holm threshold if included. Pre-registration v7.5 Change 9 specified a 6-hypothesis Holm correction across {H1', ..., H6'}; the analysis here applies Holm to the 5-hypothesis family that uses one-sided p-value tests and reports H5' equivalence separately. This refinement is an analysis-side methodological choice, not a pre-registered specification.

## IV.C What pre-registration did and did not do

Pre-registration prevented selective hypothesis reporting: H1 was falsified at btest scale (v7.5), but the public record contains both the falsification and the subsequent reframed hypothesis set. The falsification is not retroactively suppressed; it sits in the chain.

Pre-registration did not prevent honest methodological discoveries during the experiment. Three substantive corrections (the jc-effectiveness measurement-validity gap, the window-quantization exclusion-classification gap, and the block-order seed re-derivation in v7.8) were made during the study and are recorded as amendments with their motivating empirical evidence. Each amendment is dated before the confirmatory data it affects; in cases where this ordering was ambiguous (the v7.9 procedural disclosure on `extract_latency_v7.py` mlc-binary support), the ambiguity itself was disclosed.

Pre-registration is not a substitute for analysis hygiene. Trial-level exclusion criteria, per-block configuration verification, and per-cell rate-checking against the 10% ceiling remain necessary. What pre-registration does provide is a forcing function for those checks to be specified in advance and for any post-hoc modification to be recorded with a timestamp that pre-dates any data that could motivate the modification.
