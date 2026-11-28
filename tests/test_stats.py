"""Statistics in make_report.py checked against independently known values."""

import math

import pytest

import make_report as mr


def test_wilson_matches_reference_values():
    # Reference: Newcombe (1998), Table I, 81/263 -> 0.2553 .. 0.3662
    lo, hi = mr.wilson(81, 263)
    assert lo == pytest.approx(0.2553, abs=5e-4)
    assert hi == pytest.approx(0.3662, abs=5e-4)


def test_wilson_edge_cases_stay_inside_unit_interval():
    assert mr.wilson(0, 0) == (None, None)
    lo, hi = mr.wilson(0, 50)
    assert lo == 0.0 and 0 < hi < 0.1
    lo, hi = mr.wilson(50, 50)
    assert 0.9 < lo < 1.0 and hi == pytest.approx(1.0)


def test_fisher_exact_matches_r():
    # R: fisher.test(matrix(c(3, 1, 1, 3), 2))$p.value == 0.4857143 (Fisher's tea test)
    assert mr.fisher_exact_two_sided(3, 1, 1, 3) == pytest.approx(0.4857143, rel=1e-6)
    # R: fisher.test(matrix(c(10, 2, 3, 15), 2))$p.value == 0.0005367241
    assert mr.fisher_exact_two_sided(10, 2, 3, 15) == pytest.approx(0.0005367241, rel=1e-5)


def test_poisson_cdf():
    # P(X < 1 | lambda=2) = e^-2
    assert mr.poisson_cdf_below(1, 2.0) == pytest.approx(math.exp(-2))
    # P(X < 3 | lambda=1) = e^-1 (1 + 1 + 1/2)
    assert mr.poisson_cdf_below(3, 1.0) == pytest.approx(math.exp(-1) * 2.5)


def test_negative_binomial_is_wider_than_poisson():
    mean = 35.0
    p_pois = mr.poisson_cdf_below(15, mean)
    p_nb = mr.negbin_cdf_below(15, mean, var=3 * mean)
    assert p_nb > p_pois * 10  # overdispersion fattens the low-depth tail
    # with variance == mean it collapses to Poisson
    assert mr.negbin_cdf_below(15, mean, var=mean) == pytest.approx(p_pois)


def test_negative_binomial_sums_to_one():
    total = mr.negbin_cdf_below(2000, 30.0, 90.0)
    assert total == pytest.approx(1.0, abs=1e-9)


def test_f1_interval_contains_point_estimate_and_is_deterministic():
    tp, fn, fp = 950, 50, 30
    r, p = tp / (tp + fn), tp / (tp + fp)
    f1 = 2 * p * r / (p + r)
    a = mr.f1_interval(tp, fn, tp, fp)
    b = mr.f1_interval(tp, fn, tp, fp)
    assert a == b  # fixed seed
    assert a[0] < f1 < a[1]
    assert a[1] - a[0] < 0.05


@pytest.mark.parametrize(
    "ref,alt,expected",
    [
        ("C", "A", "C>A"),
        ("G", "T", "C>A"),  # 8-oxoG signature, both strands
        ("C", "T", "C>T"),
        ("G", "A", "C>T"),  # deamination / transition
        ("A", "G", "T>C"),
        ("T", "C", "T>C"),
        ("a", "c", "T>G"),
    ],
)
def test_snv_class_collapses_to_pyrimidine_strand(ref, alt, expected):
    assert mr.snv_class(ref, alt) == expected
