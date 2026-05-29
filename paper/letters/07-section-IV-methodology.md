# §IV. Methodology and Statistical Treatment

## IV.A Pre-registration

All hypotheses, exclusion criteria, statistical tests, and multiplicity-correction strategies were specified in a public, version-controlled pre-registration with externally-timestamped Zenodo DOIs [4]. The chain contains 12 substantive amendments (v6.1–v7.10); each was minted as a Zenodo release on the same calendar day as its git tag, giving an audit-defensible timestamp ordering.

## IV.B Statistical tests and multiplicity correction

Each hypothesis is matched to a pre-registered test. H1' and H2' (stochastic ordering of two independent samples) use a one-sided Mann-Whitney U test, with the Hodges-Lehmann shift and a 95% percentile-bootstrap CI (10,000 resamples) as the effect estimate [5], [6]. H3' (the interaction contrast Δ_MLC − Δ_host > 0) bootstraps the contrast statistic (10,000 resamples). H5' (equivalence within ±30 µs) uses TOST [7]: the 90% CI on the median difference must lie strictly within [−30, +30] µs. H6' (energy difference > 1,000 mW) uses Mann-Whitney U on VDD_IN samples with 1/10 subsampling to reduce the autocorrelation of 100 ms-cadence INA3221 readings. H7' (stability ordering) uses a one-sided Fisher's exact test, chosen over chi-square because the per-cell unstable counts (6–15 of 540) fall where the chi-square asymptotic approximation is unreliable.

Multiplicity correction across the {H1', H2', H3', H6', H7'} family is by Holm-Bonferroni at family-wise α = 0.05 [8]. H5' uses TOST equivalence rather than a directional p-value and is reported alongside the family rather than within it; this is an analysis-side refinement of the v7.5 specification, which had named a six-hypothesis Holm family.
