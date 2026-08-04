"""Company-specific cost of capital (VAL-19).

Until 2026-08-03 the discount rate was a sector constant — Coca-Cola and every
other staple got 9.0%, and no company attribute touched it. These cases pin the
inputs that now make it company-specific, and the guardrails that keep a
computed rate from breaking the Gordon denominator.
"""

from __future__ import annotations

import pytest

from mas_sector_system.cost_of_capital import (
    DEFAULT_TAX_RATE,
    EQUITY_RISK_PREMIUM,
    RISK_FREE_RATE,
    SECTOR_UNLEVERED_BETA,
    WACC_CEILING,
    WACC_FLOOR,
    compute_cost_of_capital,
    cost_of_debt,
    effective_tax_rate,
    format_cost_of_capital,
    levered_beta,
)


def _cell(value):
    return {"value": value}


def _state(
    *,
    market_cap=100e9,
    total_debt=20e9,
    prior_debt=None,
    interest=0.8e9,
    net_income=10e9,
    tax=3e9,
    beta=None,
):
    metrics = {"total_debt__current_annual": _cell(total_debt)}
    if prior_debt is not None:
        metrics["total_debt__prior_annual"] = _cell(prior_debt)
    if interest is not None:
        metrics["interest_expense__current_annual"] = _cell(interest)
    live = {"price": 50.0, "market_cap": market_cap}
    if beta is not None:
        live["beta"] = beta
    return {
        "canonical_metrics": {"by_id": metrics},
        "income_statement": {
            "current_annual": {
                "NetIncomeLoss": _cell(net_income),
                "IncomeTaxExpenseBenefit": _cell(tax),
            }
        },
        "cash_flow_statement": {"live_market": live},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Inputs, each from the filing
# ─────────────────────────────────────────────────────────────────────────────

def test_tax_rate_comes_from_the_filed_income_statement():
    rate, source = effective_tax_rate(
        {"current_annual": {"NetIncomeLoss": _cell(77.0), "IncomeTaxExpenseBenefit": _cell(23.0)}}
    )
    assert rate == pytest.approx(0.23)
    assert "filed" in source


@pytest.mark.parametrize(
    "net_income,tax",
    [(-50.0, 3.0), (10.0, -20.0), (10.0, 15.0)],  # pretax<=0, negative rate, 60%
)
def test_an_implausible_tax_rate_falls_back_rather_than_propagating(net_income, tax):
    rate, source = effective_tax_rate(
        {"current_annual": {"NetIncomeLoss": _cell(net_income), "IncomeTaxExpenseBenefit": _cell(tax)}}
    )
    assert rate == DEFAULT_TAX_RATE
    assert "default" in source


def test_cost_of_debt_averages_the_two_debt_balances():
    """Interest accrues over the period; closing debt alone overstates the rate."""
    rate, source = cost_of_debt(_state(interest=1.0e9, total_debt=30e9, prior_debt=10e9))
    assert rate == pytest.approx(1.0e9 / 20e9)
    assert "average" in source


def test_a_bank_like_interest_ratio_is_rejected_not_used():
    """JPM's interest expense over its total debt computes to ~24%.

    That is deposit and float cost being misread as a financing rate. It must
    be refused rather than propagated into a discount rate.
    """
    rate, source = cost_of_debt(_state(interest=81.3e9, total_debt=332.7e9))
    assert rate is None
    assert "rejected" in source


def test_levered_beta_is_hamada():
    assert levered_beta(1.0, 0.0, 0.25) == pytest.approx(1.0)
    assert levered_beta(1.0, 1.0, 0.25) == pytest.approx(1.75)
    assert levered_beta(0.6, 0.5, 0.20) == pytest.approx(0.6 * (1 + 0.8 * 0.5))


# ─────────────────────────────────────────────────────────────────────────────
# The assembled rate
# ─────────────────────────────────────────────────────────────────────────────

def test_wacc_is_company_specific_and_shows_its_work():
    block = compute_cost_of_capital(
        _state(), archetype="mature_dividend_payer", sector_default_wacc=0.09
    )
    assert block["basis"] == "company_specific"
    assert block["wacc"] != 0.09
    # Every component that produced the number is present and self-describing.
    for key in (
        "cost_of_equity",
        "cost_of_debt_pretax",
        "cost_of_debt_after_tax",
        "weight_equity",
        "weight_debt",
        "beta",
        "beta_source",
        "tax_rate",
        "tax_rate_source",
        "risk_free_rate",
        "equity_risk_premium",
    ):
        assert block.get(key) is not None, key
    assert block["weight_equity"] + block["weight_debt"] == pytest.approx(1.0)

    expected_equity = RISK_FREE_RATE + block["beta"] * EQUITY_RISK_PREMIUM
    assert block["cost_of_equity"] == pytest.approx(expected_equity)


def test_two_companies_in_one_sector_get_different_rates():
    """The whole point: the rate must respond to company attributes."""
    low_debt = compute_cost_of_capital(
        _state(total_debt=1e9), archetype="general", sector_default_wacc=0.09
    )
    high_debt = compute_cost_of_capital(
        _state(total_debt=80e9), archetype="general", sector_default_wacc=0.09
    )
    assert low_debt["wacc"] != high_debt["wacc"]
    assert high_debt["beta"] > low_debt["beta"], "more leverage, higher equity beta"


def test_an_observed_beta_overrides_the_relevered_sector_beta():
    relevered = compute_cost_of_capital(
        _state(), archetype="general", sector_default_wacc=0.09
    )
    observed = compute_cost_of_capital(
        _state(beta=2.05), archetype="general", sector_default_wacc=0.09
    )
    assert observed["beta"] == pytest.approx(2.05)
    assert "observed" in observed["beta_source"]
    assert observed["wacc"] > relevered["wacc"]


def test_an_absurd_observed_beta_is_refused_and_disclosed():
    block = compute_cost_of_capital(
        _state(beta=47.0), archetype="general", sector_default_wacc=0.09
    )
    assert block["beta"] != 47.0
    assert any("outside" in w for w in block["warnings"])


def test_the_catch_all_archetype_warns_that_the_rate_is_the_weak_input():
    """NVDA and QCOM both key to `general`; re-levering there put NVDA +99%."""
    block = compute_cost_of_capital(
        _state(), archetype="general", sector_default_wacc=0.09
    )
    assert any("CATCH-ALL" in w for w in block["warnings"])
    # ...and not when the archetype is specific, or the warning is just noise.
    specific = compute_cost_of_capital(
        _state(), archetype="utility", sector_default_wacc=0.09
    )
    assert not any("CATCH-ALL" in w for w in specific["warnings"])


# ─────────────────────────────────────────────────────────────────────────────
# Guardrails
# ─────────────────────────────────────────────────────────────────────────────

def test_a_computed_rate_is_floored_so_the_gordon_denominator_survives():
    """A very low-beta, all-equity name must not discount below the floor."""
    block = compute_cost_of_capital(
        _state(market_cap=500e9, total_debt=0.0, interest=None),
        archetype="utility",
        sector_default_wacc=0.09,
    )
    assert block["wacc"] >= WACC_FLOOR
    assert block["wacc"] <= WACC_CEILING


def test_a_clamped_rate_says_so():
    import mas_sector_system.cost_of_capital as coc

    original = coc.RISK_FREE_RATE
    coc.RISK_FREE_RATE = 0.001  # force the raw rate under the floor
    try:
        block = coc.compute_cost_of_capital(
            _state(total_debt=0.0, interest=None),
            archetype="utility",
            sector_default_wacc=0.09,
        )
        assert block["wacc"] == pytest.approx(WACC_FLOOR)
        assert any("clamped" in w for w in block["warnings"])
    finally:
        coc.RISK_FREE_RATE = original


def test_financials_get_a_cost_of_equity_and_no_wacc():
    """Interest expense is the cost of the float that IS the business."""
    for archetype in ("bank_lender", "insurance", "mortgage_reit"):
        block = compute_cost_of_capital(
            _state(), archetype=archetype, sector_default_wacc=0.09
        )
        assert block["wacc"] is None, archetype
        assert block["cost_of_equity"] is not None
        assert block["basis"] == "cost_of_equity_only"


def test_no_market_cap_falls_back_to_the_sector_constant_and_discloses_it():
    block = compute_cost_of_capital(
        {"canonical_metrics": {"by_id": {}}, "income_statement": {}},
        archetype="general",
        sector_default_wacc=0.09,
    )
    assert block["basis"] == "sector_default"
    assert block["wacc"] == 0.09
    assert any("market capitalization" in w for w in block["warnings"])


def test_every_archetype_has_an_unlevered_beta():
    from mas_sector_system.archetype import ARCHETYPES

    missing = [a for a in ARCHETYPES if a not in SECTOR_UNLEVERED_BETA]
    assert missing == [], f"archetypes with no unlevered beta: {missing}"


def test_the_summary_names_the_basis_a_reader_needs():
    block = compute_cost_of_capital(
        _state(), archetype="mature_dividend_payer", sector_default_wacc=0.09
    )
    text = format_cost_of_capital(block)
    assert "COMPANY SPECIFIC" in text
    assert "sector default would have been 9.00%" in text
    assert "risk-free" in text and "beta" in text and "cost of debt" in text
