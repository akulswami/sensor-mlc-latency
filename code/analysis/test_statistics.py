"""
test_statistics.py
==================

Unit tests for statistics.py. Validates each function against
scipy.stats (where a counterpart exists) and against analytic
baselines (for bootstrap CIs).

Run with:
    cd code/analysis
    python3 -m pytest test_statistics.py -v

Or directly:
    python3 test_statistics.py
"""

from __future__ import annotations

import sys

import numpy as np
from scipy import stats as scipy_stats

import statistics as mod  # the module under test


# Reproducibility seed for tests that use randomness.
TEST_SEED = 20260525


def _approx_equal(a: float, b: float, rel: float = 1e-6, abs_: float = 1e-9) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


# ---------------------------------------------------------------------------
# Mann-Whitney U
# ---------------------------------------------------------------------------


def test_mann_whitney_matches_scipy_greater():
    rng = np.random.default_rng(TEST_SEED)
    x = rng.normal(10.0, 1.0, size=100)
    y = rng.normal(8.0, 1.0, size=120)

    res = mod.mann_whitney_u(x, y, alternative="greater")
    ref = scipy_stats.mannwhitneyu(x, y, alternative="greater")

    assert _approx_equal(res.u_statistic, float(ref.statistic)), (
        f"U statistic: ours={res.u_statistic}, scipy={ref.statistic}"
    )
    assert _approx_equal(res.p_value, float(ref.pvalue)), (
        f"p_value: ours={res.p_value}, scipy={ref.pvalue}"
    )
    assert res.alternative == "greater"
    assert res.n_x == 100 and res.n_y == 120


def test_mann_whitney_matches_scipy_less():
    rng = np.random.default_rng(TEST_SEED + 1)
    x = rng.normal(5.0, 1.0, size=80)
    y = rng.normal(7.0, 1.0, size=90)

    res = mod.mann_whitney_u(x, y, alternative="less")
    ref = scipy_stats.mannwhitneyu(x, y, alternative="less")

    assert _approx_equal(res.u_statistic, float(ref.statistic))
    assert _approx_equal(res.p_value, float(ref.pvalue))


def test_mann_whitney_matches_scipy_two_sided():
    rng = np.random.default_rng(TEST_SEED + 2)
    x = rng.normal(0.0, 1.0, size=50)
    y = rng.normal(0.1, 1.0, size=50)

    res = mod.mann_whitney_u(x, y, alternative="two-sided")
    ref = scipy_stats.mannwhitneyu(x, y, alternative="two-sided")

    assert _approx_equal(res.u_statistic, float(ref.statistic))
    assert _approx_equal(res.p_value, float(ref.pvalue))


def test_mann_whitney_rejects_invalid_alternative():
    try:
        mod.mann_whitney_u([1, 2, 3], [4, 5, 6], alternative="wrong")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_mann_whitney_rejects_empty():
    try:
        mod.mann_whitney_u([], [1, 2, 3])
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Hodges-Lehmann
# ---------------------------------------------------------------------------


def test_hodges_lehmann_brute_force_small():
    # For small samples, validate against brute-force median of pairwise diffs.
    x = [1.0, 2.0, 3.0, 4.0]
    y = [0.5, 1.5, 2.5]
    diffs = []
    for xi in x:
        for yi in y:
            diffs.append(xi - yi)
    expected = float(np.median(diffs))
    actual = mod.hodges_lehmann(x, y)
    assert _approx_equal(actual, expected), f"HL: ours={actual}, brute={expected}"


def test_hodges_lehmann_shift_invariance():
    # HL(x, y) = HL(x+c, y) - c (it's a location estimator).
    rng = np.random.default_rng(TEST_SEED + 3)
    x = rng.normal(10.0, 2.0, size=50)
    y = rng.normal(8.0, 2.0, size=60)
    c = 5.0
    hl1 = mod.hodges_lehmann(x, y)
    hl2 = mod.hodges_lehmann(x + c, y)
    assert _approx_equal(hl2 - c, hl1, abs_=1e-9), (
        f"shift invariance violated: hl1={hl1}, hl2-c={hl2 - c}"
    )


def test_hodges_lehmann_recovers_location_shift():
    # Two normal samples with known shift; HL should recover it within bootstrap CI.
    rng = np.random.default_rng(TEST_SEED + 4)
    x = rng.normal(100.0, 5.0, size=500)
    y = rng.normal(95.0, 5.0, size=500)
    hl = mod.hodges_lehmann(x, y)
    # True shift is 5; HL of large samples should be close.
    assert abs(hl - 5.0) < 0.5, f"HL = {hl}, expected near 5.0"


# ---------------------------------------------------------------------------
# Hodges-Lehmann bootstrap CI
# ---------------------------------------------------------------------------


def test_hl_bootstrap_ci_covers_true_shift():
    # 95% CI from 10k bootstrap should contain the true shift in most cases.
    # We run a single trial; this is a regression test, not a coverage proof.
    rng = np.random.default_rng(TEST_SEED + 5)
    x = rng.normal(100.0, 5.0, size=500)
    y = rng.normal(95.0, 5.0, size=500)
    res = mod.hl_bootstrap_ci_wrapper(x, y)
    # True shift 5.0 should be inside.
    assert res.ci_low <= 5.0 <= res.ci_high, (
        f"True shift 5.0 not in CI [{res.ci_low}, {res.ci_high}]"
    )
    # CI should be narrow given large n.
    assert (res.ci_high - res.ci_low) < 2.0, (
        f"CI too wide: [{res.ci_low}, {res.ci_high}]"
    )


def hl_bootstrap_ci_wrapper(x, y):
    """Wrapper that pins seed for reproducible tests."""
    return mod.hodges_lehmann_bootstrap_ci(
        x, y, n_boot=10_000, confidence=0.95,
        rng=np.random.default_rng(TEST_SEED + 100),
    )

# Patch module reference so the test can call it via mod.
mod.hl_bootstrap_ci_wrapper = hl_bootstrap_ci_wrapper


def test_hl_bootstrap_ci_default_n_boot():
    rng = np.random.default_rng(TEST_SEED + 6)
    x = rng.normal(0.0, 1.0, size=50)
    y = rng.normal(0.0, 1.0, size=50)
    res = mod.hodges_lehmann_bootstrap_ci(
        x, y, rng=np.random.default_rng(TEST_SEED + 7)
    )
    assert res.n_boot == 10_000, f"default n_boot should be 10000, got {res.n_boot}"
    assert res.confidence == 0.95


def test_hl_bootstrap_ci_reproducibility():
    rng = np.random.default_rng(TEST_SEED + 8)
    x = rng.normal(0.0, 1.0, size=30)
    y = rng.normal(0.5, 1.0, size=30)
    r1 = mod.hodges_lehmann_bootstrap_ci(
        x, y, n_boot=1000, rng=np.random.default_rng(42)
    )
    r2 = mod.hodges_lehmann_bootstrap_ci(
        x, y, n_boot=1000, rng=np.random.default_rng(42)
    )
    assert _approx_equal(r1.ci_low, r2.ci_low), "RNG not reproducible (ci_low)"
    assert _approx_equal(r1.ci_high, r2.ci_high), "RNG not reproducible (ci_high)"


# ---------------------------------------------------------------------------
# bootstrap_difference_of_medians (H2)
# ---------------------------------------------------------------------------


def test_h2_bootstrap_detects_difference():
    # Setup: under stress, host pipeline is slower; MLC is the same.
    # Therefore Δ_stress > Δ_nostress, and the test should reject.
    rng = np.random.default_rng(TEST_SEED + 9)
    n = 500
    mlc_nostress = rng.normal(500.0, 50.0, size=n)
    mlc_stress = rng.normal(500.0, 50.0, size=n)   # same dist
    host_nostress = rng.normal(700.0, 100.0, size=n)
    host_stress = rng.normal(1200.0, 200.0, size=n)  # much slower under stress

    res = mod.bootstrap_difference_of_medians(
        x_stress_host=host_stress,
        x_stress_mlc=mlc_stress,
        x_nostress_host=host_nostress,
        x_nostress_mlc=mlc_nostress,
        n_boot=2000,
        rng=np.random.default_rng(TEST_SEED + 10),
    )
    assert res.point > 0, f"point should be positive, got {res.point}"
    assert res.p_value < 0.01, f"p_value should be tiny, got {res.p_value}"
    assert res.ci_low > 0, f"95% CI should be entirely positive: [{res.ci_low}, {res.ci_high}]"


def test_h2_bootstrap_under_null():
    # Setup: no stress effect; H2 null should not be rejected.
    rng = np.random.default_rng(TEST_SEED + 11)
    n = 500
    mlc_nostress = rng.normal(500.0, 50.0, size=n)
    mlc_stress = rng.normal(500.0, 50.0, size=n)
    host_nostress = rng.normal(700.0, 100.0, size=n)
    host_stress = rng.normal(700.0, 100.0, size=n)  # no stress effect

    res = mod.bootstrap_difference_of_medians(
        x_stress_host=host_stress,
        x_stress_mlc=mlc_stress,
        x_nostress_host=host_nostress,
        x_nostress_mlc=mlc_nostress,
        n_boot=2000,
        rng=np.random.default_rng(TEST_SEED + 12),
    )
    # Under null, point should be near 0 (could be slightly positive or negative)
    # p_value should NOT be small.
    assert abs(res.point) < 50.0, f"point should be small, got {res.point}"
    # p_value > 0.05 (not rejecting null)
    assert res.p_value > 0.05, f"p_value should be > 0.05 under null, got {res.p_value}"


# ---------------------------------------------------------------------------
# TOST equivalence (H4)
# ---------------------------------------------------------------------------


def test_tost_declares_equivalence_when_small_difference():
    # Two samples with nearly identical medians; should declare equivalence.
    rng = np.random.default_rng(TEST_SEED + 13)
    n = 500
    x = rng.normal(500.0, 30.0, size=n)
    y = rng.normal(502.0, 30.0, size=n)  # 2 us shift, well inside ±50 us

    res = mod.tost_bootstrap(
        x, y, low_bound=-50.0, high_bound=50.0, alpha=0.05,
        n_boot=2000, rng=np.random.default_rng(TEST_SEED + 14),
    )
    assert res.equivalent, (
        f"Should declare equivalence: CI=[{res.ci_low}, {res.ci_high}], "
        f"bounds=[{res.low_bound}, {res.high_bound}]"
    )
    assert res.p_value < 0.05, f"TOST p-value should be < 0.05, got {res.p_value}"


def test_tost_rejects_equivalence_when_large_difference():
    # Two samples with large difference; should NOT declare equivalence.
    rng = np.random.default_rng(TEST_SEED + 15)
    n = 500
    x = rng.normal(500.0, 30.0, size=n)
    y = rng.normal(600.0, 30.0, size=n)  # 100 us shift, outside ±50 us

    res = mod.tost_bootstrap(
        x, y, low_bound=-50.0, high_bound=50.0, alpha=0.05,
        n_boot=2000, rng=np.random.default_rng(TEST_SEED + 16),
    )
    assert not res.equivalent, (
        f"Should NOT declare equivalence: CI=[{res.ci_low}, {res.ci_high}]"
    )
    # p_value should be high (failing one of the one-sided tests)
    assert res.p_value > 0.05, f"TOST p-value should be > 0.05, got {res.p_value}"


def test_tost_rejects_invalid_bounds():
    try:
        mod.tost_bootstrap(
            [1, 2, 3], [4, 5, 6], low_bound=50.0, high_bound=-50.0
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Holm-Bonferroni
# ---------------------------------------------------------------------------


def test_holm_bonferroni_matches_scipy():
    # scipy.stats.false_discovery_control has a 'by' method but not Holm
    # directly; instead use statsmodels.stats.multitest.multipletests
    # which IS the reference. But we want minimal deps, so we validate
    # against the textbook formula directly.
    p = [0.01, 0.04, 0.03, 0.005]
    alpha = 0.05
    res = mod.holm_bonferroni(p, alpha=alpha)
    # Holm-Bonferroni: sort p ascending: [0.005, 0.01, 0.03, 0.04]
    # Compare against alpha/(m), alpha/(m-1), alpha/(m-2), alpha/(m-3)
    # = 0.0125, 0.01667, 0.025, 0.05
    # 0.005 < 0.0125: reject
    # 0.01 < 0.01667: reject
    # 0.03 > 0.025: STOP; do not reject this or any later
    # So expected reject: [True, False, False, True]
    # (in original order: p was [0.01, 0.04, 0.03, 0.005])
    # 0.01 is the 2nd smallest -> reject
    # 0.04 is the 4th smallest -> not reject (after stop)
    # 0.03 is the 3rd smallest -> not reject (stopped at this index)
    # 0.005 is the smallest -> reject
    expected_reject = [True, False, False, True]
    actual_reject = res.reject.tolist()
    assert actual_reject == expected_reject, (
        f"reject mismatch: ours={actual_reject}, expected={expected_reject}"
    )


def test_holm_bonferroni_adjusted_p_values():
    # Adjusted p for k-th smallest = min over j<=k of p_(j) * (m-j+1), capped at 1.
    # p sorted: [0.005, 0.01, 0.03, 0.04]
    # m = 4
    # adj_(1) = 0.005 * 4 = 0.02
    # adj_(2) = max(0.02, 0.01 * 3) = max(0.02, 0.03) = 0.03
    # adj_(3) = max(0.03, 0.03 * 2) = max(0.03, 0.06) = 0.06
    # adj_(4) = max(0.06, 0.04 * 1) = max(0.06, 0.04) = 0.06
    p = [0.01, 0.04, 0.03, 0.005]
    res = mod.holm_bonferroni(p, alpha=0.05)
    # Map sorted adjusted back to original order:
    # original: [0.01, 0.04, 0.03, 0.005] -> ranks (smallest=0): [1, 3, 2, 0]
    # adj_sorted: [0.02, 0.03, 0.06, 0.06]
    # So:
    # original[0] = 0.01 -> rank 1 -> adj 0.03
    # original[1] = 0.04 -> rank 3 -> adj 0.06
    # original[2] = 0.03 -> rank 2 -> adj 0.06
    # original[3] = 0.005 -> rank 0 -> adj 0.02
    expected = np.array([0.03, 0.06, 0.06, 0.02])
    np.testing.assert_allclose(res.adjusted_p_values, expected, rtol=1e-9)


def test_holm_bonferroni_no_rejection_when_all_large():
    p = [0.5, 0.6, 0.7, 0.8]
    res = mod.holm_bonferroni(p, alpha=0.05)
    assert not res.reject.any(), "No hypothesis should be rejected"


def test_holm_bonferroni_all_rejected_when_all_tiny():
    p = [1e-6, 1e-6, 1e-6, 1e-6]
    res = mod.holm_bonferroni(p, alpha=0.05)
    assert res.reject.all(), "All hypotheses should be rejected"


def test_holm_bonferroni_rejects_invalid_p():
    try:
        mod.holm_bonferroni([0.5, 1.5, 0.3])
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


def run_all_tests():
    tests = [
        name for name in dir(sys.modules[__name__]) if name.startswith("test_")
    ]
    passed, failed = [], []
    for name in tests:
        fn = getattr(sys.modules[__name__], name)
        try:
            fn()
            passed.append(name)
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed.append((name, str(e)))
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ERROR {name}: {type(e).__name__}: {e}")

    print(f"\n{len(passed)} passed, {len(failed)} failed.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
