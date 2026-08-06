"""Company-specific cost of capital, computed from filings and market data.

Until 2026-08-03 every discount rate in this system was a sector constant:
Coca-Cola and a mid-cap staple got the same 9.0%, and no company attribute
touched it. That constant was doing more work than any argued input. On the
2026-08-01 run it was the single largest remaining driver of the gap between
the engine's fair value and the market — KO moves from -58% to -25% against
price on that change alone.

What is company-specific here, and where it comes from:

  effective tax rate   IncomeTaxExpenseBenefit / (NetIncomeLoss + tax)   filing
  cost of debt         InterestExpense / average total debt              filing
  capital structure    market cap (live) vs total debt (filing)          both
  levered beta         sector unlevered beta re-levered by actual D/E    both
  cost of equity       risk_free + beta x equity risk premium            CAPM

Three deliberate choices:

**Re-levered sector beta is the primary path, not observed beta.** An observed
beta needs a market-data vendor and cannot be recomputed from anything stored,
so a system built on it would silently fall back to the constant every time the
vendor was unreachable. Hamada re-levering uses the company's *own* capital
structure and *own* tax rate against a documented sector constant, so it is
reproducible from the filing plus a market cap. An observed beta is accepted as
an override when one is supplied.

**Financials do not get a WACC.** For a bank or an insurer, interest expense is
the cost of the deposit and policy float that *is* the business, not the cost of
financing it — JPM's interest expense over its total debt computes to 24%, which
is not a cost of debt, it is a line item being misread. Those archetypes get a
cost of equity only, which is what `_excess_return_on_equity` actually consumes.

**The result is floored and disclosed, never silently accepted.** A computed
WACC that lands under `WACC_FLOOR` would collapse the Gordon denominator
against a 2.5-3.0% terminal growth rate. It is floored, and the binding is
recorded rather than hidden.

Market inputs (`RISK_FREE_RATE`, `EQUITY_RISK_PREMIUM`) are stated constants
with a date, not estimates pulled at runtime. They are the two numbers a
reviewer is most likely to want to change, so they are overridable by
environment variable and always echoed in the output.
"""

from __future__ import annotations

import os
from typing import Any, Optional

# ── Market inputs ────────────────────────────────────────────────────────────
# Stated, dated, and overridable. As of 2026-08-03: 10Y US Treasury ~4.2%, and
# a 4.8% ERP is mid-range for the standard published estimates. Both are
# assumptions about the market, not about any company — which is exactly why
# they are here as named constants rather than buried in a formula.
RISK_FREE_RATE = float(os.getenv("MAS_RISK_FREE_RATE", "0.042"))
EQUITY_RISK_PREMIUM = float(os.getenv("MAS_EQUITY_RISK_PREMIUM", "0.048"))
MARKET_INPUTS_AS_OF = "2026-08-03"

# Floor matches ARGUED_INPUT_BOUNDS["wacc"][0] so a computed rate can never land
# somewhere the argued layer would reject. Ceiling likewise.
WACC_FLOOR = 0.05
WACC_CEILING = 0.20

# Unlevered (asset) betas by archetype. Sector constants — the one part of the
# calculation that is not company-specific — re-levered below by each company's
# own capital structure and tax rate.
SECTOR_UNLEVERED_BETA: dict[str, float] = {
    "general": 0.95,
    "software_saas": 1.05,
    # Semiconductors carry the highest asset beta in this universe: a deep
    # capex cycle, customer concentration, and demand that swings with the
    # inventory cycle. Routing NVDA and QCOM through `general` at 0.95 was the
    # measured cause of their +99% / +78% overvaluation on 2026-08-01.
    "semiconductor": 1.40,
    "asset_light": 0.95,
    "asset_heavy": 0.90,
    "asset_heavy_industrial": 0.95,
    "cyclical_commodity": 1.00,
    "midstream": 0.80,
    "utility": 0.45,
    "telecom": 0.65,
    "mature_dividend_payer": 0.60,
    "pre_profit_growth": 1.35,
    "equity_reit": 0.70,
    "reit_real_estate": 0.70,
    "mortgage_reit": 0.75,
    "bank_lender": 0.85,
    "insurance": 0.80,
}
DEFAULT_UNLEVERED_BETA = 0.95

# Interest expense is not a financing cost for these business models.
_NO_WACC_ARCHETYPES = {"bank_lender", "insurance", "mortgage_reit"}

# A computed cost of debt outside this range is a parse artefact, not a rate.
# The ceiling is 15%: JPM's interest expense over its total debt computes to
# 24.4%, which is deposit and float cost being misread as a financing rate, and
# no investment-grade issuer in this universe borrows above 15%.
_COST_OF_DEBT_BOUNDS = (0.005, 0.15)
_TAX_RATE_BOUNDS = (0.0, 0.50)
DEFAULT_TAX_RATE = 0.23


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _metric(state: dict, metric_id: str) -> Optional[float]:
    by_id = ((state.get("canonical_metrics") or {}).get("by_id") or {})
    record = by_id.get(metric_id)
    if isinstance(record, dict):
        return _num(record.get("value"))
    return None


def _line(statement: dict, period: str, name: str) -> Optional[float]:
    block = (statement or {}).get(period) or {}
    cell = block.get(name)
    if isinstance(cell, dict):
        return _num(cell.get("value"))
    return _num(cell)


def effective_tax_rate(income_statement: dict) -> tuple[float, str]:
    """Tax expense over pretax income, from the filed income statement.

    Pretax income is reconstructed as net income + tax expense rather than read
    from a separate tag: the pretax tag is the least consistently reported of
    the three, and the identity holds by construction.
    """
    tax = _line(income_statement, "current_annual", "IncomeTaxExpenseBenefit")
    net_income = _line(income_statement, "current_annual", "NetIncomeLoss")
    if tax is None or net_income is None:
        return DEFAULT_TAX_RATE, f"default {DEFAULT_TAX_RATE:.0%} (no filed tax line)"
    pretax = net_income + tax
    if pretax <= 0:
        return DEFAULT_TAX_RATE, f"default {DEFAULT_TAX_RATE:.0%} (pretax income <= 0)"
    rate = tax / pretax
    low, high = _TAX_RATE_BOUNDS
    if not (low <= rate <= high):
        return (
            DEFAULT_TAX_RATE,
            f"default {DEFAULT_TAX_RATE:.0%} (computed {rate:.1%} outside {low:.0%}-{high:.0%})",
        )
    return rate, "filed: tax expense / (net income + tax expense)"


def cost_of_debt(state: dict) -> tuple[Optional[float], str]:
    """Interest expense over average total debt, from filings.

    Averaged across the current and prior year because interest accrues over
    the period while debt is a point-in-time balance; using the closing balance
    alone overstates the rate for a company that levered up during the year.
    """
    interest = _metric(state, "interest_expense__current_annual")
    if interest is None:
        interest = _line(state.get("income_statement") or {}, "current_annual", "InterestExpense")
    current_debt = _metric(state, "total_debt__current_annual")
    prior_debt = _metric(state, "total_debt__prior_annual")

    if interest is None or current_debt is None:
        return None, "unavailable (no interest expense or total debt)"
    debts = [d for d in (current_debt, prior_debt) if d and d > 0]
    if not debts:
        return None, "unavailable (no positive total debt)"
    average_debt = sum(debts) / len(debts)
    rate = abs(interest) / average_debt
    low, high = _COST_OF_DEBT_BOUNDS
    if not (low <= rate <= high):
        return None, f"rejected ({rate:.1%} outside {low:.1%}-{high:.0%}; likely a tag mismatch)"
    basis = "average of current and prior" if len(debts) == 2 else "current only"
    return rate, f"filed: interest expense / total debt ({basis})"


def levered_beta(unlevered: float, debt_to_equity: float, tax_rate: float) -> float:
    """Hamada: beta_L = beta_U x (1 + (1 - t) x D/E)."""
    return unlevered * (1.0 + (1.0 - tax_rate) * max(0.0, debt_to_equity))


def compute_cost_of_capital(
    state: dict,
    *,
    archetype: str,
    sector_default_wacc: float,
    observed_beta: Optional[float] = None,
) -> dict[str, Any]:
    """Company-specific WACC (or cost of equity for financials).

    Returns a fully self-describing block: every rate, every input that
    produced it, where each came from, and whether the result is company
    specific or fell back to the sector constant.
    """
    warnings: list[str] = []
    archetype = archetype or "general"
    unlevered = SECTOR_UNLEVERED_BETA.get(archetype, DEFAULT_UNLEVERED_BETA)

    # Read the observed beta off the state when a caller did not pass one, so a
    # new call site cannot silently drop back to the re-levered path.
    if observed_beta is None:
        for statement in ("income_statement", "balance_sheet", "cash_flow_statement"):
            live = (state.get(statement) or {}).get("live_market")
            if isinstance(live, dict) and live.get("beta") is not None:
                observed_beta = _num(live.get("beta"))
                break

    tax_rate, tax_source = effective_tax_rate(state.get("income_statement") or {})

    market_cap = _num(
        ((state.get("cash_flow_statement") or {}).get("live_market") or {}).get("market_cap")
    )
    if market_cap is None:
        market_cap = _metric(state, "market_cap__current_annual")
    total_debt = _metric(state, "total_debt__current_annual")

    result: dict[str, Any] = {
        "risk_free_rate": RISK_FREE_RATE,
        "equity_risk_premium": EQUITY_RISK_PREMIUM,
        "market_inputs_as_of": MARKET_INPUTS_AS_OF,
        "archetype": archetype,
        "unlevered_beta": unlevered,
        "tax_rate": tax_rate,
        "tax_rate_source": tax_source,
        "sector_default_wacc": sector_default_wacc,
        "warnings": warnings,
    }

    if market_cap is None or market_cap <= 0:
        warnings.append(
            "No market capitalization available — cannot weight the capital "
            "structure; fell back to the sector-default discount rate."
        )
        result.update(
            {
                "wacc": sector_default_wacc,
                "cost_of_equity": None,
                "basis": "sector_default",
            }
        )
        return result

    debt = total_debt if (total_debt and total_debt > 0) else 0.0
    debt_to_equity = (debt / market_cap) if market_cap else 0.0

    if observed_beta is not None and 0.1 <= float(observed_beta) <= 3.0:
        beta = float(observed_beta)
        beta_source = "observed (market data)"
    else:
        if observed_beta is not None:
            warnings.append(
                f"Observed beta {observed_beta} outside 0.1-3.0 — re-levered the "
                "sector unlevered beta instead."
            )
        beta = levered_beta(unlevered, debt_to_equity, tax_rate)
        beta_source = (
            f"re-levered sector unlevered beta {unlevered:.2f} at D/E "
            f"{debt_to_equity:.2f} and tax {tax_rate:.1%}"
        )
        # The re-levered path is only as granular as the archetype, and
        # `general` is the catch-all. Measured on the 2026-08-01 slices: NVDA
        # and QCOM both key to `general` and re-lever to 0.95 / 1.02, which puts
        # NVDA at +99% against market. With an observed beta near 2.05 it lands
        # at -11%. That is not a rounding difference, so say so out loud rather
        # than shipping a confident discount rate built on the wrong risk.
        if archetype == "general":
            warnings.append(
                f"Beta re-levered from the CATCH-ALL `general` archetype "
                f"({unlevered:.2f} unlevered). No observed beta was available, "
                "and `general` spans business models with very different risk — "
                "treat the discount rate as the weakest input in this valuation."
            )

    equity_cost = RISK_FREE_RATE + beta * EQUITY_RISK_PREMIUM
    result.update(
        {
            "beta": beta,
            "beta_source": beta_source,
            "debt_to_equity_market": debt_to_equity,
            "market_cap": market_cap,
            "total_debt": debt,
            "cost_of_equity": equity_cost,
        }
    )

    # Financials: interest expense is the cost of the float that *is* the
    # business. A WACC built on it is meaningless, and these archetypes value on
    # residual income against cost of equity anyway.
    if archetype in _NO_WACC_ARCHETYPES:
        result.update(
            {
                "wacc": None,
                "basis": "cost_of_equity_only",
                "note": (
                    "Financial archetype: no WACC computed. Interest expense is "
                    "an operating cost of funds here, not a financing cost. The "
                    "residual-income model discounts at cost of equity."
                ),
            }
        )
        return result

    debt_cost, debt_source = cost_of_debt(state)
    if debt_cost is None:
        if debt > 0:
            warnings.append(
                f"Cost of debt {debt_source} — treated the company as "
                "all-equity financed for discounting, which understates the "
                "tax shield and slightly overstates WACC."
            )
        weight_equity, weight_debt = 1.0, 0.0
        after_tax_debt_cost = None
        wacc_raw = equity_cost
    else:
        total_capital = market_cap + debt
        weight_equity = market_cap / total_capital
        weight_debt = debt / total_capital
        after_tax_debt_cost = debt_cost * (1.0 - tax_rate)
        wacc_raw = weight_equity * equity_cost + weight_debt * after_tax_debt_cost

    wacc = min(WACC_CEILING, max(WACC_FLOOR, wacc_raw))
    if abs(wacc - wacc_raw) > 1e-9:
        warnings.append(
            f"Computed WACC {wacc_raw:.2%} clamped to {wacc:.2%} "
            f"(bounds {WACC_FLOOR:.0%}-{WACC_CEILING:.0%}). Below the floor the "
            "Gordon denominator collapses against terminal growth."
        )

    result.update(
        {
            "cost_of_debt_pretax": debt_cost,
            "cost_of_debt_source": debt_source,
            "cost_of_debt_after_tax": after_tax_debt_cost,
            "weight_equity": weight_equity,
            "weight_debt": weight_debt,
            "wacc_before_clamp": wacc_raw,
            "wacc": wacc,
            "basis": "company_specific",
        }
    )
    return result


def format_cost_of_capital(block: dict[str, Any]) -> str:
    """One-line-per-component summary for the valuation prompt and audit log."""
    if not block:
        return ""
    if block.get("basis") == "sector_default":
        return (
            f"Discount rate: {block['wacc']:.2%} — SECTOR DEFAULT, not company "
            f"specific ({'; '.join(block.get('warnings') or [])})"
        )

    lines = []
    equity_cost = block.get("cost_of_equity")
    if block.get("basis") == "cost_of_equity_only":
        lines.append(
            f"Cost of equity: {equity_cost:.2%} = risk-free {block['risk_free_rate']:.2%} "
            f"+ beta {block['beta']:.2f} x ERP {block['equity_risk_premium']:.2%}"
        )
        lines.append(f"  beta: {block['beta_source']}")
        lines.append(f"  {block.get('note', '')}")
        return "\n".join(l for l in lines if l.strip())

    lines.append(
        f"WACC: {block['wacc']:.2%} — COMPANY SPECIFIC, computed from filings "
        f"(sector default would have been {block['sector_default_wacc']:.2%})"
    )
    lines.append(
        f"  cost of equity {equity_cost:.2%} = risk-free "
        f"{block['risk_free_rate']:.2%} + beta {block['beta']:.2f} x ERP "
        f"{block['equity_risk_premium']:.2%}"
    )
    lines.append(f"  beta: {block['beta_source']}")
    if block.get("cost_of_debt_pretax") is not None:
        lines.append(
            f"  cost of debt {block['cost_of_debt_pretax']:.2%} pre-tax, "
            f"{block['cost_of_debt_after_tax']:.2%} after tax at "
            f"{block['tax_rate']:.1%} — {block['cost_of_debt_source']}"
        )
        lines.append(
            f"  weights: {block['weight_equity']:.1%} equity / "
            f"{block['weight_debt']:.1%} debt at market"
        )
    lines.append(f"  tax rate {block['tax_rate']:.1%} — {block['tax_rate_source']}")
    lines.append(
        f"  market inputs as of {block['market_inputs_as_of']} "
        "(risk-free and ERP are stated assumptions, not live quotes)"
    )
    for warning in block.get("warnings") or []:
        lines.append(f"  NOTE: {warning}")
    return "\n".join(lines)
