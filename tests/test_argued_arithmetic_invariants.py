"""Arithmetic invariants for the argued-DCF layer.

These are the two assertions that would have caught the FWD-07 review findings
before delivery. Both bugs shipped wrong numbers into client memos with a
confident disclosure attached, and every criterion in the 11-point rubric passed
them, because nothing in the rubric checks engine-internal arithmetic.

Findings, reproduced live on the 2026-07-30 baseline:

1. `delta_vs_default` was measured against the engine's fair value (engine base
   FCF) while every sensitivity case was recomputed on the *argued* base FCF. On
   KO, three parameters argued AT the engine default each reported +$17.31. The
   memo then named WACC the dominant lever when g_high was ~50% larger and
   pointed the other way.

2. The compounded corners took index [0] and [1] of every argued range. A lower
   WACC raises value while a lower g_high lowers it, so the two ends partly
   cancelled. On KO the case labelled `low_case` returned the HIGHER value, and
   the published band ($28.39–$33.94, width $5.55) was 3.1x narrower than the
   true compounded extreme ($23.56–$40.66, width $17.10) — while being disclosed
   as "wider than the analysis supports".
"""

from __future__ import annotations

import pytest

from mas_sector_system.valuation_engine import (
    _ffo_nav_case,
    _residual_income_case,
    compute_dcf_from_state,
    compute_dcf_with_argued_inputs,
)


def _cell(value, end):
    return {"value": value, "end": end, "form": "10-K"}


# KO's real filed cash-flow history from the 2026-07-30 run. Five years so
# `avg_5y` is available — the argued base-FCF method that exposed bug 1.
_KO_FCF_YEARS = [
    # (rank, fy, end, operating cash flow, capex)
    (0, 2025, "2025-12-31", 7408000000, 2112000000),
    (1, 2024, "2024-12-31", 6805000000, 2064000000),
    (2, 2023, "2023-12-31", 11599000000, 1852000000),
    (3, 2022, "2022-12-31", 11018000000, 1484000000),
    (4, 2021, "2021-12-31", 12625000000, 1367000000),
]


def _state() -> dict:
    """A KO-shaped state: the live case both bugs were found on."""
    series = [
        {
            "rank": rank,
            "fy": fy,
            "NetCashFromOperatingActivities": _cell(ocf, end),
            "CapitalExpenditures": _cell(capex, end),
        }
        for rank, fy, end, ocf, capex in _KO_FCF_YEARS
    ]
    current = series[0]
    prior = series[1]
    return {
        "ticker": "KO",
        "sector": "Consumer Staples",
        "cash_flow_statement": {
            "current_annual": {
                "NetCashFromOperatingActivities": current[
                    "NetCashFromOperatingActivities"
                ],
                "CapitalExpenditures": current["CapitalExpenditures"],
                "FreeCashFlow": _cell(5296000000, "2025-12-31"),
            },
            "prior_annual": {
                "NetCashFromOperatingActivities": prior[
                    "NetCashFromOperatingActivities"
                ],
                "CapitalExpenditures": prior["CapitalExpenditures"],
                "FreeCashFlow": _cell(4741000000, "2024-12-31"),
            },
            "annual_series": series,
            "live_market": {
                "price": 88.49,
                "market_cap": 380732538880.0,
                "shares_outstanding": 4302549243.0,
            },
        },
        "balance_sheet": {
            "current_annual": {
                "CashAndCashEquivalents": _cell(10800000000, "2025-12-31"),
                "TotalDebt": _cell(44144000000, "2025-12-31"),
            }
        },
        "income_statement": {
            "current_annual": {
                "Revenues": _cell(47940000000, "2025-12-31"),
                "NetIncomeLoss": _cell(13107000000, "2025-12-31"),
                "EPS_Diluted": _cell(3.04, "2025-12-31"),
                "WeightedAverageSharesDiluted": _cell(4302549243, "2025-12-31"),
            },
            "live_market": {
                "price": 88.49,
                "market_cap": 380732538880.0,
                "shares_outstanding": 4302549243.0,
            },
        },
        "canonical_metrics": {"by_id": {}},
    }


def _argued() -> dict:
    """KO's live accepted argument set (2026-07-30).

    `base_fcf_method=avg_5y` is what made the engine base FCF and the argued
    base FCF diverge, which is what surfaced bug 1.
    """
    return {
        "base_fcf_method": "avg_5y",
        "wacc": {"argued_range": [0.070, 0.085]},
        "g_high": {"argued_range": [0.020, 0.045]},
        # Argued AT the engine default on the live run — must move nothing.
        "g_terminal": {"argued_range": [0.025, 0.025]},
        "high_growth_years": {"argued_range": [5, 5]},
        "fade_years": {"argued_range": [5, 5]},
    }


def _judgment() -> dict:
    result = compute_dcf_with_argued_inputs(_state(), _argued())
    if result.get("method") != "multi_stage_fcf_dcf":
        pytest.skip(f"fixture did not route to an FCF DCF: {result.get('method')}")
    if not (result.get("sensitivities") or []):
        pytest.skip("fixture produced no sensitivities")
    return result


# ── Invariant 1: an unmoved parameter moves nothing ──────────────────────────

def test_parameter_argued_at_engine_default_has_zero_delta():
    """A parameter whose argued midpoint equals the engine default cannot move
    fair value. This is true under *any* definition of "delta vs default" — a
    parameter that did not move reporting movement is incoherent."""
    judgment = _judgment()
    offenders = []
    for s in judgment["sensitivities"]:
        if s["parameter"] == "base_fcf_method":
            continue  # not a DCF dial; measured engine-FV → neutral-FV by design
        default, midpoint = s.get("engine_default"), s.get("argued_midpoint")
        if default is None or midpoint is None:
            continue
        if abs(float(midpoint) - float(default)) > 1e-12:
            continue
        delta = s.get("delta_vs_default")
        if delta is not None and abs(delta) > 1e-6:
            offenders.append((s["parameter"], default, midpoint, delta))

    assert not offenders, (
        "parameters argued at the engine default reported non-zero movement "
        f"(the FWD-07 KO bug): {offenders}"
    )


def test_sensitivity_baseline_is_the_argued_base_fcf_not_the_engine_fv():
    """The delta reference must be the neutral case — same base FCF as the
    argued cases, every parameter at the engine default."""
    judgment = _judgment()
    neutral = judgment.get("neutral_case") or {}
    neutral_fv = neutral.get("fair_value_per_share")
    assert isinstance(neutral_fv, (int, float)), "neutral_case must carry a fair value"

    for s in judgment["sensitivities"]:
        if s["parameter"] == "base_fcf_method":
            continue
        fv, delta = s.get("fair_value_per_share"), s.get("delta_vs_default")
        if not isinstance(fv, (int, float)) or not isinstance(delta, (int, float)):
            continue
        assert fv - delta == pytest.approx(neutral_fv, rel=1e-9), (
            f"{s['parameter']}: delta measured from {fv - delta}, "
            f"expected the neutral case {neutral_fv}"
        )


def test_base_fcf_method_is_reported_when_it_moves_the_valuation():
    """The base-FCF choice was the single largest lever on KO and was invisible
    to the writer because it never got a row."""
    judgment = _judgment()
    engine_fv = (judgment.get("base_engine") or {}).get("fair_value_per_share")
    neutral_fv = (judgment.get("neutral_case") or {}).get("fair_value_per_share")
    if not isinstance(engine_fv, (int, float)) or not isinstance(neutral_fv, (int, float)):
        pytest.skip("fixture lacks both reference fair values")
    if abs(neutral_fv - engine_fv) <= 1e-9:
        pytest.skip("argued base FCF matched the engine base FCF — no row expected")

    rows = [s for s in judgment["sensitivities"] if s["parameter"] == "base_fcf_method"]
    assert rows, "base_fcf_method changed the valuation but got no sensitivity row"
    assert rows[0]["delta_vs_default"] == pytest.approx(neutral_fv - engine_fv, rel=1e-9)


# ── Invariant 2: the compounded band must bracket every single-parameter case ─

def test_reported_corners_really_are_the_compounded_extremes():
    """The band claims each parameter is set to whichever end of its argued
    range moves value down (low) or up (high). Then no combination of range
    ends can fall outside it.

    Brute-force all 2^N combinations and assert the reported corners are the
    true min and max. This is what catches non-sign-aware selection: the live
    KO run reported [28.39, 33.94] while the real extremes were [23.56, 40.66],
    because taking index [0] of every range paired a *low* WACC (optimistic)
    with a *low* g_high (pessimistic) and let them cancel.

    Note this cannot be tested against the single-parameter sensitivities —
    those hold the other parameters at engine defaults, not at argued values,
    so they live in a different reference frame and may legitimately fall
    outside the band.
    """
    import itertools

    from mas_sector_system.valuation_engine import (
        _normalized_base_fcf,
        _recompute_dcf_case,
        compute_dcf_from_state,
    )

    state, argued = _state(), _argued()
    judgment = _judgment()
    rng = judgment.get("fair_value_range") or {}
    low, high = rng.get("low"), rng.get("high")
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        pytest.skip("no argued range produced")

    base = compute_dcf_from_state(state)
    assumptions = base.get("assumptions") or {}
    normalized_fcf, applied_method, _ = _normalized_base_fcf(
        state, str(argued.get("base_fcf_method") or "ttm")
    )

    params = ["wacc", "g_high", "g_terminal", "high_growth_years", "fade_years"]
    ends = {}
    for p in params:
        entry = argued.get(p)
        rng_p = (entry or {}).get("argued_range") if isinstance(entry, dict) else None
        ends[p] = list(rng_p) if rng_p else [assumptions.get(p), assumptions.get(p)]

    observed = []
    for combo in itertools.product(*(ends[p] for p in params)):
        kwargs = dict(zip(params, combo))
        kwargs["wacc"] = float(kwargs["wacc"])
        kwargs["g_high"] = float(kwargs["g_high"])
        # Same Gordon clamp the engine applies to each corner.
        kwargs["g_terminal"] = max(
            0.0, min(float(kwargs["g_terminal"]), kwargs["wacc"] - 0.015)
        )
        kwargs["high_growth_years"] = int(kwargs["high_growth_years"])
        kwargs["fade_years"] = int(kwargs["fade_years"])
        case = _recompute_dcf_case(
            base,
            base_fcf=normalized_fcf,
            base_fcf_method=applied_method,
            **kwargs,
        )
        fv = case.get("fair_value_per_share")
        if isinstance(fv, (int, float)):
            observed.append(fv)

    if not observed:
        pytest.skip("no corner combination produced a fair value")

    true_low, true_high = min(observed), max(observed)
    tol = max(abs(true_low), abs(true_high)) * 1e-9

    assert low <= true_low + tol, (
        f"reported low {low} is above the true compounded minimum {true_low} — "
        "corners are not sign-aware (the FWD-07 KO bug)"
    )
    assert high >= true_high - tol, (
        f"reported high {high} is below the true compounded maximum {true_high} — "
        "corners are not sign-aware (the FWD-07 KO bug)"
    )


def test_compounded_band_is_at_least_as_wide_as_the_central_case_spread():
    """Sanity companion: the band must contain the central case."""
    judgment = _judgment()
    rng = judgment.get("fair_value_range") or {}
    low, base, high = rng.get("low"), rng.get("base"), rng.get("high")
    if not all(isinstance(v, (int, float)) for v in (low, base, high)):
        pytest.skip("no argued range produced")
    assert low <= high, f"corners are inverted: low={low} > high={high}"
    tol = max(abs(low), abs(high)) * 1e-9
    assert low - tol <= base <= high + tol, (
        f"central case {base} sits outside its own band [{low}, {high}]"
    )


# ── The same invariants on non-FCF methods ──────────────────────────────────

def _financial_state(archetype: str) -> dict:
    state = {
        "ticker": "TEST",
        "sector": "Financials",
        "canonical_metrics": {"archetype": archetype, "by_id": {}},
        "income_statement": {
            "current_annual": {
                "NetIncomeLoss": _cell(12_000_000_000, "2025-12-31"),
                "WeightedAverageSharesDiluted": _cell(1_000_000_000, "2025-12-31"),
                "FFO": _cell(6_000_000_000, "2025-12-31"),
            },
            "live_market": {
                "price": 120.0,
                "market_cap": 120_000_000_000,
                "shares_outstanding": 1_000_000_000,
            },
        },
        "balance_sheet": {
            "current_annual": {
                "StockholdersEquity": _cell(80_000_000_000, "2025-12-31")
            }
        },
        "cash_flow_statement": {},
    }
    if archetype == "equity_reit":
        state["sector"] = "Real Estate"
    return state


@pytest.mark.parametrize(
    ("archetype", "argued"),
    [
        (
            "bank_lender",
            {
                "cost_of_equity": {"argued_range": [0.09, 0.09]},
                "sustainable_roe": {"argued_range": [0.13, 0.17]},
                "fade_roe": {"argued_range": [0.08, 0.10]},
                "fade_years": {"argued_range": [8, 12]},
                "plowback": {"argued_range": [0.35, 0.65]},
            },
        ),
        (
            "insurance",
            {
                "cost_of_equity": {"argued_range": [0.09, 0.09]},
                "sustainable_roe": {"argued_range": [0.20, 0.30]},
                "fade_roe": {"argued_range": [0.08, 0.10]},
                "fade_years": {"argued_range": [7, 10]},
                "plowback": {"argued_range": [0.25, 0.55]},
            },
        ),
        (
            "equity_reit",
            {
                "ffo_multiple": {"argued_range": [18.0, 22.0]},
                "cap_rate": {"argued_range": [0.05, 0.05]},
                "nav_discount": {"argued_range": [-0.10, 0.10]},
            },
        ),
    ],
)
def test_non_fcf_parameter_at_engine_default_has_zero_delta(archetype, argued):
    state = _financial_state(archetype)
    base = compute_dcf_from_state(state)
    # Set one dial exactly to the actual engine default, irrespective of the
    # fixture's sector-derived value.
    parameter = "cost_of_equity" if archetype != "equity_reit" else "cap_rate"
    default = base["assumptions"][parameter]
    argued[parameter] = {"argued_range": [default, default]}
    judgment = compute_dcf_with_argued_inputs(state, argued)
    row = next(s for s in judgment["sensitivities"] if s["parameter"] == parameter)
    assert row["delta_vs_default"] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize(
    ("archetype", "argued"),
    [
        (
            "bank_lender",
            {
                "cost_of_equity": {"argued_range": [0.08, 0.11]},
                "sustainable_roe": {"argued_range": [0.12, 0.19]},
                "fade_roe": {"argued_range": [0.07, 0.11]},
                "fade_years": {"argued_range": [6, 10]},
                "plowback": {"argued_range": [0.30, 0.70]},
            },
        ),
        (
            "equity_reit",
            {
                "ffo_multiple": {"argued_range": [16.0, 24.0]},
                "cap_rate": {"argued_range": [0.04, 0.07]},
                "nav_discount": {"argued_range": [-0.15, 0.20]},
            },
        ),
    ],
)
def test_non_fcf_reported_corners_are_true_combination_extremes(archetype, argued):
    import itertools

    state = _financial_state(archetype)
    judgment = compute_dcf_with_argued_inputs(state, argued)
    base = judgment["base_engine"]
    defaults = {
        key: value
        for key, value in base["assumptions"].items()
        if key in argued
    }
    recompute = (
        (lambda **kwargs: _residual_income_case(base, **kwargs))
        if archetype == "bank_lender"
        else (lambda **kwargs: _ffo_nav_case(base, **kwargs))
    )
    values = []
    parameters = list(argued)
    for combo in itertools.product(
        *(argued[p]["argued_range"] for p in parameters)
    ):
        kwargs = dict(defaults)
        kwargs.update(dict(zip(parameters, combo)))
        values.append(recompute(**kwargs)["fair_value_per_share"])

    fair_range = judgment["fair_value_range"]
    assert fair_range["low"] == pytest.approx(min(values), rel=1e-12)
    assert fair_range["high"] == pytest.approx(max(values), rel=1e-12)


def test_non_fcf_disclosure_only_fires_for_actual_fcf_arguments():
    state = _financial_state("bank_lender")
    native = compute_dcf_with_argued_inputs(
        state, {"cost_of_equity": {"argued_range": [0.08, 0.10]}}
    )
    assert not any(
        "Argued FCF inputs not applied" in warning
        for warning in native.get("clamp_warnings") or []
    )

    legacy = compute_dcf_with_argued_inputs(
        state, {"wacc": {"argued_range": [0.08, 0.10]}}
    )
    assert any(
        "Argued FCF inputs not applied" in warning
        for warning in legacy.get("clamp_warnings") or []
    )


# ── Invariant 3: a case never fails silently ─────────────────────────────────
#
# Added after the FWD-01b non-FCF paths landed. `_residual_income_case` and
# `_ffo_nav_case` guarded on missing inputs by returning the base unchanged —
# `equity_value=None`, `errors=[]`, and a trailing warning stating the model had
# run. `_excess_return_on_equity` then reported success having computed nothing.
# Producing neither a number nor a reason is the failure mode this whole review
# exists to eliminate, so it gets an invariant of its own.

def test_residual_income_reports_a_reason_when_it_cannot_compute():
    from mas_sector_system.valuation_engine import _residual_income_case

    base = {"inputs": {"book_equity": None, "shares": 3e9}, "errors": []}
    out = _residual_income_case(
        base, cost_of_equity=0.09, sustainable_roe=0.15,
        fade_roe=0.09, fade_years=10, plowback=0.5,
    )
    assert out.get("equity_value") is None
    assert out.get("errors"), "computed nothing and reported no reason"


def test_residual_income_still_values_equity_without_a_share_count():
    """Equity value does not depend on share count — only per-share does."""
    from mas_sector_system.valuation_engine import _residual_income_case

    base = {"inputs": {"book_equity": 300e9, "shares": None}, "errors": []}
    out = _residual_income_case(
        base, cost_of_equity=0.09, sustainable_roe=0.1667,
        fade_roe=0.09, fade_years=10, plowback=0.5,
    )
    assert isinstance(out.get("equity_value"), float), out.get("errors")
    assert out.get("fair_value_per_share") is None
    assert any("share count" in w.lower() for w in out.get("warnings") or [])


def test_ffo_nav_reports_a_reason_when_it_cannot_compute():
    from mas_sector_system.valuation_engine import _ffo_nav_case

    for inputs in (
        {"ffo": None, "shares": 1e9},
        {"ffo": 4e9, "shares": None},
    ):
        out = _ffo_nav_case(
            {"inputs": inputs, "errors": []},
            ffo_multiple=20.0, cap_rate=0.05, nav_discount=0.0,
        )
        assert out.get("fair_value_per_share") is None
        assert out.get("errors"), f"silent failure on {inputs}"
