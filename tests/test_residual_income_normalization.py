"""Sustainable ROE is normalized over the filing history, not the last year (VAL-21).

The residual-income path (banks, insurers, mortgage REITs) held
`sustainable_roe` at the trailing year's NI/equity and projected it flat for
ten years. That is the one-year-anchor defect VAL-17 removed from the FCF path,
left standing on exactly the archetypes that never touch an FCF DCF.

The asymmetry these tests pin down is the whole design: normalization must be
inert on a stable franchise and decisive on a cyclical one. If it moved JPM it
would be over-fitting; if it left PGR alone it would be doing nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mas_sector_system.valuation_engine import (  # noqa: E402
    normalize_sustainable_roe,
    roe_history_from_statements,
)


def _line(value, fy):
    return {"value": value, "fy": fy, "fp": "FY", "form": "10-K"}


def _statements(pairs):
    """pairs: [(rank, fy, net_income, equity)] → (income, balance) statements."""
    return (
        {
            "annual_series": [
                {"rank": r, "fy": fy, "NetIncomeLoss": _line(ni, fy)}
                for r, fy, ni, _ in pairs
            ]
        },
        {
            "annual_series": [
                {"rank": r, "fy": fy, "StockholdersEquity": _line(eq, fy)}
                for r, fy, _, eq in pairs
            ]
        },
    )


# PGR's real ROE series off the stored 2026-08-01 slice, newest rank first.
PGR_ROES = [0.373, 0.331, 0.192, 0.045, 0.184]
# JPM's, same slice. A genuinely stable franchise.
JPM_ROES = [0.157, 0.170, 0.151, 0.129, 0.164]


def _from_roes(roes, equity=1_000.0):
    return _statements([(i, 2025 - i, roe * equity, equity) for i, roe in enumerate(roes)])


def test_roe_history_aligns_by_rank_not_fiscal_year():
    """`fy` is unreliable — three JPM balance rows carry fy 2025 on the real slice.

    Alignment must use the producer's explicit rank, the same contract
    `fcf_history_from_statements` relies on.
    """
    income, balance = _statements(
        [(0, 2025, 100.0, 1000.0), (1, 2025, 80.0, 800.0), (2, 2025, 60.0, 600.0)]
    )
    hist = roe_history_from_statements(income, balance)
    assert [row["rank"] for row in hist] == [0, 1, 2]
    assert [round(row["roe"], 4) for row in hist] == [0.10, 0.10, 0.10]


def test_rows_missing_either_side_are_dropped_not_synthesized():
    income, balance = _statements([(0, 2025, 100.0, 1000.0), (1, 2024, 90.0, 900.0)])
    del balance["annual_series"][1]["StockholdersEquity"]
    hist = roe_history_from_statements(income, balance)
    assert len(hist) == 1, "a period with no book equity has no ROE — omit it"


def test_negative_equity_year_is_dropped_rather_than_producing_huge_roe():
    """Negative book equity makes ROE meaningless, not large."""
    income, balance = _statements([(0, 2025, 100.0, 1000.0), (1, 2024, 50.0, -200.0)])
    hist = roe_history_from_statements(income, balance)
    assert [row["rank"] for row in hist] == [0]


def test_normalization_is_inert_on_a_stable_bank():
    """JPM: 15.7 / 17.0 / 15.1 / 12.9 / 16.4 — the median IS the trailing year.

    A normalizer that moved this would be inventing a cycle that isn't there.
    """
    income, balance = _from_roes(JPM_ROES)
    hist = roe_history_from_statements(income, balance)
    roe, method, warnings = normalize_sustainable_roe(hist, JPM_ROES[0])
    assert roe == pytest.approx(0.157, abs=1e-6)
    assert method == "mid_cycle_5y"
    assert not warnings, "a stable franchise should not raise a normalization flag"


def test_normalization_cuts_a_peak_year_on_a_cyclical_insurer():
    """PGR: the engine was running a 37.3% hard-market peak for ten years."""
    income, balance = _from_roes(PGR_ROES)
    hist = roe_history_from_statements(income, balance)
    roe, method, warnings = normalize_sustainable_roe(hist, PGR_ROES[0])
    assert roe == pytest.approx(0.192, abs=1e-6), "median of the 5-year history"
    assert roe < PGR_ROES[0], "must not keep the peak"
    assert method == "mid_cycle_5y"
    assert warnings and "not mid-cycle" in warnings[0]


def test_median_ignores_the_outlier_year_that_a_mean_would_absorb():
    """PGR's 4.5% year is why this is a median, not an average."""
    income, balance = _from_roes(PGR_ROES)
    hist = roe_history_from_statements(income, balance)
    median, _, _ = normalize_sustainable_roe(hist, PGR_ROES[0], "mid_cycle")
    mean, _, _ = normalize_sustainable_roe(hist, PGR_ROES[0], "avg")
    assert median < mean, "one loss year should not drag the normalization up"
    assert mean == pytest.approx(sum(PGR_ROES) / len(PGR_ROES), abs=1e-6)


def test_thin_history_falls_back_to_trailing_loudly():
    """Two periods is not a normalization. Say so rather than pretending."""
    income, balance = _from_roes([0.30, 0.10])
    hist = roe_history_from_statements(income, balance)
    roe, method, warnings = normalize_sustainable_roe(hist, 0.30)
    assert roe == 0.30 and method == "trailing"
    assert warnings and "2 annual period" in warnings[0]


def test_no_history_at_all_falls_back_to_trailing_loudly():
    roe, method, warnings = normalize_sustainable_roe([], 0.22)
    assert roe == 0.22 and method == "trailing"
    assert warnings and "no usable ROE history" in warnings[0]


def test_explicit_trailing_request_is_silent():
    """An argued `trailing` choice is a decision, not a data failure."""
    income, balance = _from_roes(PGR_ROES)
    hist = roe_history_from_statements(income, balance)
    roe, method, warnings = normalize_sustainable_roe(hist, 0.373, "trailing")
    assert roe == 0.373 and method == "trailing" and not warnings
