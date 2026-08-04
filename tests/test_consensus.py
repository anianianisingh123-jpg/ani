"""Consensus forward estimates as a cross-check, not a second multiplier (VAL-20).

Forward EPS is derived as `price / forward_pe` — both observed — so the "no
invented figures" invariant holds. The hard part is not deriving it but knowing
when NOT to use it:

  * on a normalized base, consensus growth and the normalization price the same
    recovery, so applying both counts it twice (VAL-17's own argument), and
  * a free forward-P/E field is regularly stale, so a forward multiple the
    trailing pair does not corroborate must not produce a confident
    "the market disagrees with the filings" disclosure.
"""

from __future__ import annotations

import pytest

from mas_sector_system.consensus import (
    cash_conversion,
    consensus_cross_check,
    consensus_forward_eps,
    consensus_growth_for_year_one,
)


def _cell(value):
    return {"value": value}


def _state(*, price=100.0, forward_pe=20.0, trailing_pe=23.0, shares=1.0e9,
           net_income=5.0e9, fcf=4.0e9, revenue=20.0e9):
    rows_cf = [{"rank": r, "fy": 2025 - r, "FreeCashFlow": _cell(fcf)} for r in range(5)]
    rows_inc = [{"rank": r, "fy": 2025 - r, "Revenues": _cell(revenue)} for r in range(5)]
    return {
        "comps_engine": {
            "subject": {"price": price, "forward_pe": forward_pe, "trailing_pe": trailing_pe}
        },
        "cash_flow_statement": {
            "current_annual": {"FreeCashFlow": _cell(fcf)},
            "annual_series": rows_cf,
            "live_market": {"price": price, "shares_outstanding": shares},
        },
        "income_statement": {
            "current_annual": {"NetIncomeLoss": _cell(net_income), "Revenues": _cell(revenue)},
            "annual_series": rows_inc,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Deriving the estimate
# ─────────────────────────────────────────────────────────────────────────────

def test_forward_eps_is_price_over_forward_pe():
    block = consensus_forward_eps(_state(price=100.0, forward_pe=20.0))
    assert block["available"]
    assert block["forward_eps"] == pytest.approx(5.0)
    assert "price_over_forward_pe" in block["source"]


def test_implied_growth_comes_from_the_multiple_pair():
    """Price cancels, leaving the earnings ratio the market is using."""
    block = consensus_forward_eps(_state(trailing_pe=23.0, forward_pe=20.0))
    assert block["implied_eps_growth"] == pytest.approx(23.0 / 20.0 - 1.0)


def test_a_missing_forward_pe_degrades_quietly():
    block = consensus_forward_eps(_state(forward_pe=None))
    assert not block["available"]
    assert "forward P/E" in block["reason"]


@pytest.mark.parametrize("forward_pe", [1.0, 250.0])
def test_an_absurd_forward_pe_is_refused(forward_pe):
    assert not consensus_forward_eps(_state(forward_pe=forward_pe))["available"]


def test_an_implausible_implied_growth_is_rejected_as_a_signal():
    """NVDA's stored pair (41.0 trailing / 15.6 forward) implies +163%.

    That is a depressed-or-distorted trailing denominator, not a forecast.
    """
    block = consensus_forward_eps(_state(trailing_pe=41.0, forward_pe=15.6))
    assert block["available"]  # the EPS itself still derives
    assert block["implied_eps_growth"] is None
    assert "outside" in block["growth_reason"]


def test_cash_conversion_translates_earnings_to_cash():
    assert cash_conversion(_state(net_income=10e9, fcf=7e9)) == pytest.approx(0.7)
    # A ratio that implausible is a period mismatch, not a conversion rate.
    assert cash_conversion(_state(net_income=1e9, fcf=50e9)) is None


# ─────────────────────────────────────────────────────────────────────────────
# The double-count guard — the whole point
# ─────────────────────────────────────────────────────────────────────────────

def test_consensus_growth_is_refused_on_a_normalized_base():
    """mid_cycle already prices the recovery consensus growth measures."""
    growth, reason = consensus_growth_for_year_one(_state(), base_fcf_method="mid_cycle")
    assert growth is None
    assert "count it twice" in reason


def test_consensus_growth_is_applied_on_an_unnormalized_base():
    growth, reason = consensus_growth_for_year_one(_state(), base_fcf_method="ttm")
    assert growth == pytest.approx(23.0 / 20.0 - 1.0)
    assert "year 1" in reason


def test_year_one_growth_only_moves_the_first_year():
    """Later years must still run on the historical trend."""
    from mas_sector_system.valuation_engine import compute_dcf

    state = _state()
    result = compute_dcf(
        cash_flow=state["cash_flow_statement"],
        income=state["income_statement"],
        balance={},
        live_market={"price": 100.0, "shares_outstanding": 1.0e9},
        sector="Technology",
        year_one_growth=0.30,
    )
    projections = [p for p in result["projections"] if p["stage"] == "high_growth"]
    assert projections[0]["growth"] == pytest.approx(0.30)
    assert projections[0]["source"] == "consensus_forward"
    assert all(p["source"] == "historical_trend" for p in projections[1:])
    assert projections[1]["growth"] != pytest.approx(0.30)


# ─────────────────────────────────────────────────────────────────────────────
# The cross-check
# ─────────────────────────────────────────────────────────────────────────────

def test_agreement_is_reported_as_corroboration():
    state = _state(price=100.0, forward_pe=20.0, trailing_pe=23.0,
                   shares=1.0e9, net_income=5.0e9, fcf=4.0e9)
    # forward EPS 5.0 x 1e9 shares x 0.8 conversion = $4.0B, equal to the base.
    check = consensus_cross_check(state, engine_base_fcf=4.0e9, base_fcf_method="mid_cycle")
    assert check["available"]
    assert check["divergence_vs_engine_base"] == pytest.approx(0.0)
    assert not check["material"]
    assert "agree" in check["disclosure"]


def test_material_disagreement_is_put_in_front_of_the_writer():
    state = _state(price=100.0, forward_pe=20.0, trailing_pe=23.0,
                   shares=1.0e9, net_income=5.0e9, fcf=4.0e9)
    check = consensus_cross_check(state, engine_base_fcf=8.0e9, base_fcf_method="mid_cycle")
    assert check["material"]
    assert "disagree" in check["disclosure"]
    assert "say which one this thesis is taking" in check["disclosure"]


def test_an_uncorroborated_forward_multiple_produces_no_disclosure():
    """A stale forward P/E must not generate a confident disagreement claim."""
    state = _state(trailing_pe=41.0, forward_pe=15.6)
    check = consensus_cross_check(state, engine_base_fcf=96.0e9, base_fcf_method="mid_cycle")
    assert not check["available"]
    assert "not corroborated" in check["reason"]
    assert "disclosure" not in check


def test_cross_check_needs_shares_and_conversion_to_translate():
    state = _state(shares=None)
    check = consensus_cross_check(state, engine_base_fcf=4.0e9, base_fcf_method="ttm")
    assert not check["available"]
    assert "translate" in check["reason"]
