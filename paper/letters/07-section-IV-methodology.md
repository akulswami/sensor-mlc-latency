# §IV. Methodology and Statistical Treatment

## IV.A Pre-registration discipline

All hypotheses, exclusion criteria, statistical tests, and multiplicity-correction strategies were specified in a public, version-controlled pre-registration with externally-timestamped Zenodo DOIs [4]. The chain contains twelve substantive amendments (v6.1–v7.10); each was minted as a Zenodo release on the same calendar day as its git tag, giving an audit-defensible timestamp ordering.

Three pre-registered hypotheses were formally falsified during the study, and each falsification is preserved on the public record rather than retroactively suppressed:

- **H1** (median MLC < median host, no stress) was falsified at the 59-block pilot scale with the direction reversed (host 351 µs vs MLC 761 µs); pre-registration v7.5 recorded this and introduced the reframed H1'–H6' family with mlc-binary as a third pipeline.
- **H4'** (MLC idle energy < host idle energy) was falsified once measured under a jc-effective configuration: the gap collapsed to −32 mW, within the ±50 mW noise floor (v7.6, which also introduced the MAXN_SUPER_JC nvpmodel).
- **H7'** (MLC stability degrades under contention) was falsified by the confirmatory data, with the observed direction opposite to the prediction (v7.10).

## IV.B Statistical tests and multiplicity correction

Each hypothesis is matched to a pre-registered test. H1' and H2' (stochastic ordering of two independent samples) use a one-sided Mann-Whitney U test, with the Hodges-Lehmann shift and a 95% percentile-bootstrap CI (10,000 resamples) as the effect estimate [6, 7, 8]. H3' (the interaction contrast Δ_MLC − Δ_host > 0) bootstraps the contrast statistic (10,000 resamples). H5' (equivalence within ±30 µs) uses TOST [9]: the 90% CI on the median difference must lie strictly within [−30, +30] µs. H6' (energy difference > 1,000 mW) uses Mann-Whitney U on VDD_IN samples with 1/10 subsampling to reduce the autocorrelation of 100 ms-cadence INA3221 readings. H7' (stability ordering) uses a one-sided Fisher's exact test, chosen over chi-square because the per-cell unstable counts (6–15 of 540) fall where the chi-square asymptotic approximation is unreliable [10].

Multiplicity correction across the {H1', H2', H3', H6', H7'} family is by Holm-Bonferroni at family-wise α = 0.05 [11]. H5' uses TOST equivalence rather than a directional p-value and is reported alongside the family rather than within it; this is an analysis-side refinement of the v7.5 specification, which had named a six-hypothesis Holm family.

## IV.C Scope of the discipline

Pre-registration prevented selective reporting — the H1 falsification sits permanently in the chain alongside the reframed hypotheses — but it did not preclude honest methodological corrections during the study. Each correction (notably a CPU-frequency measurement-validity check and a window-quantization-aware exclusion rule) is recorded as a dated amendment preceding the data it affects. Pre-registration is not a substitute for analysis hygiene; it is a forcing function that requires those checks to be specified in advance and any later change to carry a timestamp that pre-dates the data motivating it.
