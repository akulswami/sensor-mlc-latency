"""
statistics.py
=============

Statistical analysis module for the sensor-mlc-latency latency experiment.

Implements the tests specified in pre-registration §12 (statistical
analysis plan), §6.3 (effect-size definitions), and v7 Change 5
(hypothesis priority for the IEEE Sensors Letters submission).

This module is pure offline analysis code. It does not depend on the
Jetson, the Saleae, or any project-specific binary. Inputs are NumPy
arrays of per-trial latency values (in microseconds) extracted from
the Saleae traces by `extract_latency_v7.py` (Gate 6).

Pre-registered tests
--------------------

- H1, H3 (one-sided Mann-Whitney U):
    `mann_whitney_u(x, y, alternative='greater')`
    Reports U statistic and one-sided p-value.

- H2 (stratified bootstrap of difference of medians):
    `bootstrap_difference_of_medians(x_stress_pairs, x_nostress_pairs)`
    Two-sample-of-two-groups: each "pair" is (host_latencies,
    mlc_latencies) under one stress level. Computes
    (Δ_stress - Δ_nostress) where Δ = median(host) - median(mlc),
    via stratified bootstrap. Returns one-sided p-value (greater).

- H4 (TOST via bootstrap of median difference):
    `tost_bootstrap(x_stress, x_nostress, low=-50, high=50)`
    Bootstrap CI of (median(x_stress) - median(x_nostress)) and
    boolean equivalence verdict (CI contained in [low, high]).
    Per §6.3 the bound is ±50 µs.

- Effect sizes (all comparisons):
    `hodges_lehmann(x, y)` returns point estimate
    `hodges_lehmann_bootstrap_ci(x, y)` returns 95% bootstrap CI

- Multiple-comparison correction:
    `holm_bonferroni(p_values, alpha=0.05)` returns adjusted p-values
    and reject decisions across the family {H1, H2, H3, H4}.

All bootstrap functions default to 10,000 resamples per §12.1 and §12.3.

Validation
----------

Each function has a counterpart in `test_statistics.py` that compares
its output against `scipy.stats` on synthetic inputs. The bootstrap
functions are validated against analytic distributions where available
(e.g. CI on the median of a known normal distribution).

References
----------

- Hodges, J. L., & Lehmann, E. L. (1963). Estimates of location based
  on rank tests. Annals of Mathematical Statistics, 34(2), 598-611.
- Mann, H. B., & Whitney, D. R. (1947). On a test of whether one of
  two random variables is stochastically larger than the other.
- Schuirmann, D. J. (1987). A comparison of the two one-sided tests
  procedure and the power approach for assessing the equivalence of
  average bioavailability. Journal of Pharmacokinetics and
  Biopharmaceutics, 15(6), 657-680.
- Holm, S. (1979). A simple sequentially rejective multiple test
  procedure. Scandinavian Journal of Statistics, 6(2), 65-70.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy import stats as scipy_stats


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MannWhitneyResult:
    """Result of a one-sided Mann-Whitney U test.

    Attributes
    ----------
    u_statistic : float
        Mann-Whitney U statistic (using the same convention as
        scipy.stats.mannwhitneyu: U_1, the rank-sum-based statistic
        for the first sample).
    p_value : float
        One-sided p-value under the specified alternative.
    alternative : str
        One of 'less', 'greater', 'two-sided'. Echoed for transparency.
    n_x : int
    n_y : int
        Sample sizes of the two groups.
    """
    u_statistic: float
    p_value: float
    alternative: str
    n_x: int
    n_y: int


@dataclass
class BootstrapCIResult:
    """A point estimate and a bootstrap CI.

    Attributes
    ----------
    point : float
        Point estimate of the statistic on the observed data.
    ci_low : float
        Lower bound of the (1-alpha) percentile bootstrap CI.
    ci_high : float
        Upper bound of the (1-alpha) percentile bootstrap CI.
    n_boot : int
        Number of bootstrap resamples used.
    confidence : float
        Confidence level (e.g. 0.95).
    """
    point: float
    ci_low: float
    ci_high: float
    n_boot: int
    confidence: float


@dataclass
class BootstrapDifferenceResult:
    """Result of a stratified bootstrap on a difference of statistics
    between two groups of two-sample pairs (H2 test).

    Attributes
    ----------
    point : float
        Observed difference (Δ_stress - Δ_nostress).
    ci_low, ci_high : float
        95% CI on the difference.
    p_value : float
        One-sided bootstrap p-value (greater): the proportion of
        bootstrap resamples for which the resampled difference is
        less than or equal to zero.
    n_boot : int
    """
    point: float
    ci_low: float
    ci_high: float
    p_value: float
    n_boot: int


@dataclass
class TOSTResult:
    """Result of a TOST (two one-sided tests) equivalence test.

    Attributes
    ----------
    point : float
        Observed difference of medians (median(x_stress) -
        median(x_nostress)).
    ci_low, ci_high : float
        90% bootstrap CI on the difference (TOST conventionally uses
        the (1-2*alpha) CI; for alpha=0.05 this is the 90% CI).
        If this CI is contained in [low_bound, high_bound], we declare
        equivalence at alpha = 0.05.
    low_bound, high_bound : float
        The equivalence bounds, in the same units as x.
    equivalent : bool
        True iff ci_low >= low_bound AND ci_high <= high_bound.
    p_lower : float
        Bootstrap p-value for H0: diff <= low_bound (one-sided greater).
    p_upper : float
        Bootstrap p-value for H0: diff >= high_bound (one-sided less).
    p_value : float
        max(p_lower, p_upper); equivalence is declared if p_value 
        alpha.
    n_boot : int
    """
    point: float
    ci_low: float
    ci_high: float
    low_bound: float
    high_bound: float
    equivalent: bool
    p_lower: float
    p_upper: float
    p_value: float
    n_boot: int


@dataclass
class HolmBonferroniResult:
    """Result of Holm-Bonferroni multiple-comparison correction.

    Attributes
    ----------
    raw_p_values : np.ndarray
        Input p-values, unchanged.
    adjusted_p_values : np.ndarray
        Holm-Bonferroni adjusted p-values, in the same order as input.
    reject : np.ndarray (bool)
        Whether each hypothesis is rejected at alpha (family-wise).
    alpha : float
    """
    raw_p_values: np.ndarray
    adjusted_p_values: np.ndarray
    reject: np.ndarray
    alpha: float


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def mann_whitney_u(
    x: Sequence[float],
    y: Sequence[float],
    alternative: str = "greater",
) -> MannWhitneyResult:
    """One-sided (or two-sided) Mann-Whitney U test.

    Used for H1 and H3 per pre-reg §12.1. The convention follows
    `scipy.stats.mannwhitneyu`: U_1 is the U statistic computed on the
    first sample; alternative='greater' tests H1: x stochastically
    greater than y (i.e. P(x > y) > 0.5).

    Parameters
    ----------
    x, y : array-like of float
        Two independent samples.
    alternative : {'less', 'greater', 'two-sided'}
        Direction of the test. For H1 in the pre-reg, the alternative
        is median(latency_MLC) < median(latency_host), which means
        x=latency_MLC, y=latency_host, alternative='less'. For H3,
        x=latency_host_stress, y=latency_host_nostress, alternative
        ='greater'.

    Returns
    -------
    MannWhitneyResult
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size == 0 or y.size == 0:
        raise ValueError("Both samples must be non-empty.")
    if alternative not in ("less", "greater", "two-sided"):
        raise ValueError(f"alternative must be one of less, greater, "
                         f"two-sided; got {alternative!r}")

    res = scipy_stats.mannwhitneyu(x, y, alternative=alternative)
    return MannWhitneyResult(
        u_statistic=float(res.statistic),
        p_value=float(res.pvalue),
        alternative=alternative,
        n_x=int(x.size),
        n_y=int(y.size),
    )


def hodges_lehmann(x: Sequence[float], y: Sequence[float]) -> float:
    """Hodges-Lehmann estimator: median of all pairwise differences
    (x_i - y_j).

    For large n*m this is O(n*m) memory; consider chunked computation
    if n*m exceeds available memory. For n=m=500 (typical for this
    experiment), n*m=250,000 floats = 2 MB, fine.

    Parameters
    ----------
    x, y : array-like of float

    Returns
    -------
    float
        Median of pairwise differences.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size == 0 or y.size == 0:
        raise ValueError("Both samples must be non-empty.")
    diffs = x[:, None] - y[None, :]
    return float(np.median(diffs))


def hodges_lehmann_bootstrap_ci(
    x: Sequence[float],
    y: Sequence[float],
    n_boot: int = 10_000,
    confidence: float = 0.95,
    rng: np.random.Generator | None = None,
) -> BootstrapCIResult:
    """Hodges-Lehmann point estimate with percentile bootstrap CI.

    Per pre-reg §12.3: 10,000 resamples, 95% CI. Resampling is done
    independently within each group (stratified bootstrap of the two
    samples).

    Parameters
    ----------
    x, y : array-like of float
    n_boot : int
        Number of bootstrap resamples (default 10,000 per §12.3).
    confidence : float
        Confidence level (default 0.95 per §12.3).
    rng : np.random.Generator, optional
        For reproducibility. If None, uses np.random.default_rng().

    Returns
    -------
    BootstrapCIResult
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if rng is None:
        rng = np.random.default_rng()

    point = hodges_lehmann(x, y)

    boot_estimates = np.empty(n_boot, dtype=float)
    nx, ny = x.size, y.size
    for i in range(n_boot):
        xb = x[rng.integers(0, nx, size=nx)]
        yb = y[rng.integers(0, ny, size=ny)]
        boot_estimates[i] = hodges_lehmann(xb, yb)

    alpha = 1.0 - confidence
    ci_low = float(np.percentile(boot_estimates, 100 * alpha / 2))
    ci_high = float(np.percentile(boot_estimates, 100 * (1 - alpha / 2)))

    return BootstrapCIResult(
        point=point,
        ci_low=ci_low,
        ci_high=ci_high,
        n_boot=n_boot,
        confidence=confidence,
    )


def bootstrap_difference_of_medians(
    x_stress_host: Sequence[float],
    x_stress_mlc: Sequence[float],
    x_nostress_host: Sequence[float],
    x_nostress_mlc: Sequence[float],
    n_boot: int = 10_000,
    rng: np.random.Generator | None = None,
) -> BootstrapDifferenceResult:
    """Stratified bootstrap of (Δ_stress - Δ_nostress) for H2.

    Per pre-reg §12.1 H2: stratified bootstrap (10,000 resamples) of
    (Δ_stress − Δ_no-stress); one-sided p-value (greater) from the
    bootstrap distribution.

    Δ = median(latency_host) − median(latency_MLC) per §6.3.

    Each stress level has TWO samples (host and MLC); each bootstrap
    iteration independently resamples all four samples (stratified by
    {condition, pipeline}), then computes the difference of differences.

    Parameters
    ----------
    x_stress_host : array-like
        Host-pipeline per-trial latencies under stress.
    x_stress_mlc : array-like
        MLC-pipeline per-trial latencies under stress.
    x_nostress_host : array-like
        Host-pipeline per-trial latencies under no stress.
    x_nostress_mlc : array-like
        MLC-pipeline per-trial latencies under no stress.
    n_boot : int
    rng : np.random.Generator, optional

    Returns
    -------
    BootstrapDifferenceResult
    """
    x_stress_host = np.asarray(x_stress_host, dtype=float)
    x_stress_mlc = np.asarray(x_stress_mlc, dtype=float)
    x_nostress_host = np.asarray(x_nostress_host, dtype=float)
    x_nostress_mlc = np.asarray(x_nostress_mlc, dtype=float)
    if rng is None:
        rng = np.random.default_rng()

    def diff_of_medians(sh, sm, nh, nm):
        delta_stress = np.median(sh) - np.median(sm)
        delta_nostress = np.median(nh) - np.median(nm)
        return delta_stress - delta_nostress

    point = diff_of_medians(
        x_stress_host, x_stress_mlc, x_nostress_host, x_nostress_mlc
    )

    boot_estimates = np.empty(n_boot, dtype=float)
    nsh = x_stress_host.size
    nsm = x_stress_mlc.size
    nnh = x_nostress_host.size
    nnm = x_nostress_mlc.size
    for i in range(n_boot):
        sh = x_stress_host[rng.integers(0, nsh, size=nsh)]
        sm = x_stress_mlc[rng.integers(0, nsm, size=nsm)]
        nh = x_nostress_host[rng.integers(0, nnh, size=nnh)]
        nm = x_nostress_mlc[rng.integers(0, nnm, size=nnm)]
        boot_estimates[i] = diff_of_medians(sh, sm, nh, nm)

    # One-sided p-value (greater): proportion of bootstrap resamples
    # with diff <= 0. Add a +1 / (n_boot+1) correction for the observed
    # value, following standard bootstrap-test practice; without it, a
    # zero-count tail underestimates the p-value.
    p_value = float((np.sum(boot_estimates <= 0) + 1) / (n_boot + 1))

    ci_low = float(np.percentile(boot_estimates, 2.5))
    ci_high = float(np.percentile(boot_estimates, 97.5))

    return BootstrapDifferenceResult(
        point=point,
        ci_low=ci_low,
        ci_high=ci_high,
        p_value=p_value,
        n_boot=n_boot,
    )


def tost_bootstrap(
    x: Sequence[float],
    y: Sequence[float],
    low_bound: float = -50.0,
    high_bound: float = 50.0,
    alpha: float = 0.05,
    n_boot: int = 10_000,
    rng: np.random.Generator | None = None,
) -> TOSTResult:
    """TOST equivalence test via bootstrap of the median difference.

    Per pre-reg §12.1 H4 and §6.3: equivalence test against ±50 µs bound.
    TOST procedure: equivalence is declared at level alpha if the
    (1 - 2*alpha) bootstrap CI of (median(x) - median(y)) is contained
    in [low_bound, high_bound].

    For alpha = 0.05, this is the 90% CI (NOT the 95% CI). Both bounds
    must be cleared simultaneously, which is the "two one-sided tests"
    structure.

    Parameters
    ----------
    x : array-like
        First sample (e.g. MLC under stress).
    y : array-like
        Second sample (e.g. MLC under no stress).
    low_bound, high_bound : float
        Equivalence bounds (in same units as x and y).
        Per §6.3: ±50 µs for H4. Defaults match.
    alpha : float
        Significance level (default 0.05). The CI used is (1 - 2*alpha).
    n_boot : int
    rng : np.random.Generator, optional

    Returns
    -------
    TOSTResult
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if low_bound >= high_bound:
        raise ValueError(f"low_bound ({low_bound}) must be < high_bound "
                         f"({high_bound})")
    if rng is None:
        rng = np.random.default_rng()

    point = float(np.median(x) - np.median(y))

    boot_diffs = np.empty(n_boot, dtype=float)
    nx, ny = x.size, y.size
    for i in range(n_boot):
        xb = x[rng.integers(0, nx, size=nx)]
        yb = y[rng.integers(0, ny, size=ny)]
        boot_diffs[i] = np.median(xb) - np.median(yb)

    # (1 - 2*alpha) CI for the TOST procedure.
    ci_low = float(np.percentile(boot_diffs, 100 * alpha))
    ci_high = float(np.percentile(boot_diffs, 100 * (1 - alpha)))

    # TOST: equivalence declared iff CI is contained in [low_bound, high_bound].
    equivalent = (ci_low >= low_bound) and (ci_high <= high_bound)

    # One-sided p-values for each bound.
    # H0_lower: diff <= low_bound (alt: diff > low_bound; "passes lower bound")
    # H0_upper: diff >= high_bound (alt: diff < high_bound; "passes upper bound")
    p_lower = float((np.sum(boot_diffs <= low_bound) + 1) / (n_boot + 1))
    p_upper = float((np.sum(boot_diffs >= high_bound) + 1) / (n_boot + 1))
    p_value = max(p_lower, p_upper)

    return TOSTResult(
        point=point,
        ci_low=ci_low,
        ci_high=ci_high,
        low_bound=low_bound,
        high_bound=high_bound,
        equivalent=equivalent,
        p_lower=p_lower,
        p_upper=p_upper,
        p_value=p_value,
        n_boot=n_boot,
    )


def holm_bonferroni(
    p_values: Sequence[float],
    alpha: float = 0.05,
) -> HolmBonferroniResult:
    """Holm-Bonferroni step-down multiple-comparison correction.

    Per pre-reg §12.2: family-wise α = 0.05 across {H1, H2, H3, H4}.

    The Holm-Bonferroni procedure:
    1. Sort p-values in ascending order: p_(1) <= p_(2) <= ... <= p_(m).
    2. Find the smallest i such that p_(i) > alpha / (m - i + 1).
    3. Reject hypotheses 1, ..., i-1; do not reject i, ..., m.

    The adjusted p-value for the k-th smallest raw p-value is
    min_{j <= k}(p_(j) * (m - j + 1)), capped at 1.

    Parameters
    ----------
    p_values : array-like of float
        Raw p-values, one per hypothesis in the family.
    alpha : float
        Family-wise significance level (default 0.05 per §12.2).

    Returns
    -------
    HolmBonferroniResult
    """
    p = np.asarray(p_values, dtype=float)
    m = p.size
    if m == 0:
        raise ValueError("p_values must be non-empty.")
    if not np.all((p >= 0) & (p <= 1)):
        raise ValueError("p_values must all be in [0, 1].")

    # Sort, remember original order to map back.
    order = np.argsort(p)
    p_sorted = p[order]

    # Adjusted p-values in sorted order: cumulative max of p_(k) * (m - k + 1)
    # where k is 1-indexed, capped at 1.
    factors = m - np.arange(m, dtype=float)  # m, m-1, ..., 1
    adj_sorted = np.minimum(np.maximum.accumulate(p_sorted * factors), 1.0)

    # Map back to original positions.
    adjusted = np.empty_like(p)
    adjusted[order] = adj_sorted
    reject = adjusted < alpha

    return HolmBonferroniResult(
        raw_p_values=p,
        adjusted_p_values=adjusted,
        reject=reject,
        alpha=alpha,
    )
