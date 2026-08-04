"""The deterministic DCF default must read the filing history, not one year.

Before 2026-08-03 `compute_dcf` took its base FCF from the latest annual figure
and its five-year growth rate from that year's FCF change. A single
unrepresentative year therefore set both the level and the slope of the whole
projection. On the 2026-08-01 eight-name run that produced a $24.76 fair value
for KO against an $87.59 price, off a 2025 FCF roughly half the prior run-rate
grown at a rate measured between two depressed years.

Every assertion below is written to FAIL against that old behaviour, not merely
to pass against the new one — the `test_*_would_fail_on_single_year_basis`
cases pin the specific numbers the old path produced.
"""

import pytest

from mas_sector_system.valuation_engine import (
    _trend_revenue_growth,
    compute_dcf,
    compute_dcf_from_state,
    compute_dcf_with_argued_inputs,
    fcf_history_from_statements,
    normalize_base_fcf,
)


def _cell(value):
    return {"value": value, "end": None, "fy": None, "fp": "FY", "form": "10-K"}


def _series(pairs):
    """Build (cash_flow, income) annual_series from newest-first (fcf, revenue)."""
    cash_rows, income_rows = [], []
    for rank, (fcf, revenue) in enumerate(pairs):
        cash_rows.append({"rank": rank, "fy": 2025 - rank, "FreeCashFlow": _cell(fcf)})
        income_rows.append(
            {"rank": rank, "fy": 2025 - rank, "Revenues": _cell(revenue)}
        )
    return cash_rows, income_rows


# KO as filed: the two most recent years are depressed against a $9.5-11.3B
# run-rate, and revenue is flat-to-up throughout.
KO_HISTORY = [
    (5.296e9, 47.941e9),
    (4.741e9, 47.061e9),
    (9.752e9, 45.754e9),
    (9.532e9, 43.004e9),
    (11.259e9, 38.655e9),
]


def _ko_statements():
    cash_rows, income_rows = _series(KO_HISTORY)
    cash_flow = {
        "current_annual": {"FreeCashFlow": _cell(KO_HISTORY[0][0])},
        "prior_annual": {"FreeCashFlow": _cell(KO_HISTORY[1][0])},
        "annual_series": cash_rows,
    }
    income = {
        "current_annual": {"Revenues": _cell(KO_HISTORY[0][1])},
        "prior_annual": {"Revenues": _cell(KO_HISTORY[1][1])},
        "annual_series": income_rows,
    }
    return cash_flow, income


def _ko_dcf():
    cash_flow, income = _ko_statements()
    return compute_dcf(
        cash_flow=cash_flow,
        income=income,
        balance={},
        live_market={"price": 87.59, "shares_outstanding": 4.3e9},
        sector="Consumer Staples",
        ticker="KO",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Base FCF
# ─────────────────────────────────────────────────────────────────────────────

def test_base_fcf_is_normalized_over_history_not_the_latest_year():
    result = _ko_dcf()
    inputs = result["inputs"]

    assert inputs["base_fcf_method"] == "mid_cycle"
    assert inputs["fcf_history_years"] == 5
    # median FCF margin (21.3%) applied to current revenue ($47.941B).
    assert inputs["base_fcf_annual"] == pytest.approx(10.21e9, rel=0.01)
    # The trailing figure is retained, not discarded — the writer needs both.
    assert inputs["trailing_fcf_annual"] == pytest.approx(5.296e9)


def test_base_fcf_would_fail_on_single_year_basis():
    """Pins the old behaviour: base == latest annual FCF."""
    inputs = _ko_dcf()["inputs"]
    assert inputs["base_fcf_annual"] != pytest.approx(5.296e9), (
        "base FCF fell back to the single latest year — the pre-2026-08-03 bug"
    )
    assert inputs["base_fcf_annual"] > 1.5 * 5.296e9


def test_normalization_is_disclosed_when_it_moves_the_number():
    result = _ko_dcf()
    disclosure = [w for w in result["warnings"] if "representative" in w]
    assert disclosure, f"no normalization disclosure in {result['warnings']}"
    assert "mid_cycle" in disclosure[0]


def test_a_stable_company_is_left_alone():
    """NVDA's margin has been ~44-46% for three years: normalization is a no-op.

    A default that only moves unrepresentative years is the point; one that
    re-bases everything would penalize genuine growth (the `avg_5y` failure
    mode called out in VALUATION_ICL_DESIGN §4.6).
    """
    nvda = [
        (96.68e9, 215.94e9),
        (60.85e9, 130.50e9),
        (27.02e9, 60.92e9),
        (3.81e9, 26.97e9),
        (8.13e9, 26.91e9),
    ]
    cash_rows, income_rows = _series(nvda)
    result = compute_dcf(
        cash_flow={
            "current_annual": {"FreeCashFlow": _cell(nvda[0][0])},
            "prior_annual": {"FreeCashFlow": _cell(nvda[1][0])},
            "annual_series": cash_rows,
        },
        income={
            "current_annual": {"Revenues": _cell(nvda[0][1])},
            "prior_annual": {"Revenues": _cell(nvda[1][1])},
            "annual_series": income_rows,
        },
        balance={},
        live_market={"price": 200.75, "shares_outstanding": 24.4e9},
        sector="Semiconductors",
        ticker="NVDA",
    )
    base = result["inputs"]["base_fcf_annual"]
    assert base == pytest.approx(96.68e9, rel=0.03)
    # avg_5y would have anchored NVDA at ~$39.3B against a $96B run-rate.
    assert base > 2.0 * 39.3e9


# ─────────────────────────────────────────────────────────────────────────────
# Growth rate
# ─────────────────────────────────────────────────────────────────────────────

def test_growth_comes_from_the_revenue_trend_not_one_years_fcf_change():
    assumptions = _ko_dcf()["assumptions"]
    assert assumptions["g_high_source"].startswith("revenue_cagr")
    # revenue CAGR 47.941/38.655 over four years = +5.5%.
    assert assumptions["g_high"] == pytest.approx(0.055, abs=0.003)


def test_growth_would_fail_on_single_year_basis():
    """Pins the old behaviour: g_high == latest FCF YoY (+11.7% for KO).

    That figure was measured between two depressed years, which is exactly why
    a one-year growth signal cannot carry a five-year projection.
    """
    assumptions = _ko_dcf()["assumptions"]
    assert assumptions["g_high"] != pytest.approx(0.117, abs=0.002), (
        "g_high fell back to one-year FCF YoY — the pre-2026-08-03 bug"
    )
    assert assumptions["g_high_source"] != "fcf_yoy"


def _history(pairs):
    cash_rows, income_rows = _series(pairs)
    return fcf_history_from_statements(
        {"annual_series": cash_rows}, {"annual_series": income_rows}
    )


def test_trend_growth_refuses_short_or_gappy_history():
    assert _trend_revenue_growth([]) == (None, None)
    # Two years is not a trend.
    assert _trend_revenue_growth(_history(KO_HISTORY[:2])) == (None, None)
    # A missing revenue year disqualifies the CAGR rather than skipping a year.
    cash_rows, income_rows = _series(KO_HISTORY)
    income_rows[2].pop("Revenues")
    history = fcf_history_from_statements(
        {"annual_series": cash_rows}, {"annual_series": income_rows}
    )
    assert _trend_revenue_growth(history) == (None, None)


# ─────────────────────────────────────────────────────────────────────────────
# Backward compatibility and the neutral-basis invariant
# ─────────────────────────────────────────────────────────────────────────────

def test_callers_without_history_keep_the_single_year_behaviour():
    """`annual_series` is optional; a caller holding only current/prior must work."""
    result = compute_dcf(
        cash_flow={
            "current_annual": {"FreeCashFlow": _cell(1.0e9)},
            "prior_annual": {"FreeCashFlow": _cell(0.8e9)},
        },
        income={
            "current_annual": {"Revenues": _cell(5.0e9)},
            "prior_annual": {"Revenues": _cell(4.0e9)},
        },
        balance={},
        live_market={"price": 10.0, "shares_outstanding": 1.0e8},
        sector="Technology",
    )
    inputs, assumptions = result["inputs"], result["assumptions"]
    assert inputs["base_fcf_method"] == "ttm"
    assert inputs["base_fcf_annual"] == pytest.approx(1.0e9)
    assert assumptions["g_high_source"] == "fcf_yoy"
    assert assumptions["g_high"] == pytest.approx(0.25)
    assert result["fair_value_per_share"] is not None


def test_engine_always_records_the_basis_it_used():
    """The argued path reads this to build its neutral reference.

    Without it, an unargued case rebases to `ttm` while the engine case sits on
    `mid_cycle`, and every sensitivity delta is measured across two different
    bases — the bug FWD-07-FIX killed on KO and QCOM.
    """
    for result in (_ko_dcf(),):
        assert result["inputs"].get("base_fcf_method")
        assert result["assumptions"].get("base_fcf_method")
        assert result["inputs"]["base_fcf_method"] == (
            result["assumptions"]["base_fcf_method"]
        )


def test_unargued_base_keeps_the_neutral_case_on_the_engine_basis():
    """Arguing a parameter must not silently rebase the neutral reference.

    The argued path recomputes every case on its own base FCF and measures
    deltas against `neutral_case`. If an unargued `base_fcf_method` resolved to
    `ttm` while the engine sat on `mid_cycle`, those deltas would again be
    measured across two different bases — the FWD-07-FIX bug. Here the model
    argues WACC only, at a range centred on the engine default, so the neutral
    case must land exactly on the engine value and the WACC delta must be zero.
    """
    cash_flow, income = _ko_statements()
    state = {
        "ticker": "KO",
        "sector": "Consumer Staples",
        "cash_flow_statement": {
            **cash_flow,
            "live_market": {"price": 87.59, "shares_outstanding": 4.3e9},
        },
        "income_statement": income,
        "balance_sheet": {},
        "canonical_metrics": {"archetype": "mature_dividend_payer"},
    }
    base = compute_dcf_from_state(state)
    engine_fv = base["fair_value_per_share"]
    assert isinstance(engine_fv, float), "fixture must produce a real fair value"
    assert base["inputs"]["base_fcf_method"] == "mid_cycle"

    result = compute_dcf_with_argued_inputs(
        state, {"wacc": {"argued_range": [0.085, 0.095]}}
    )
    neutral_fv = (result.get("neutral_case") or {}).get("fair_value_per_share")
    assert neutral_fv == pytest.approx(engine_fv), (
        "neutral case rebased away from the engine basis"
    )
    assert result["inputs"]["base_fcf_method"] == "mid_cycle"

    wacc_rows = [
        s for s in (result.get("sensitivities") or []) if s["parameter"] == "wacc"
    ]
    assert wacc_rows and wacc_rows[0]["delta_vs_default"] == pytest.approx(0.0)


def test_normalize_base_fcf_is_the_one_implementation():
    """Both the default and the argued path must resolve a method identically."""
    cash_flow, income = _ko_statements()
    history = fcf_history_from_statements(cash_flow, income)
    trailing = 5.296e9

    engine_base = compute_dcf(
        cash_flow=cash_flow,
        income=income,
        balance={},
        live_market={"price": 87.59, "shares_outstanding": 4.3e9},
        sector="Consumer Staples",
    )["inputs"]["base_fcf_annual"]

    argued_base, applied, _ = normalize_base_fcf(history, trailing, "mid_cycle")
    assert applied == "mid_cycle"
    assert argued_base == pytest.approx(engine_base)

    # And an argued method genuinely moves off that basis.
    avg5, applied5, _ = normalize_base_fcf(history, trailing, "avg_5y")
    assert applied5 == "avg_5y"
    assert avg5 == pytest.approx(8.116e9, rel=0.01)
    assert avg5 != pytest.approx(engine_base)
