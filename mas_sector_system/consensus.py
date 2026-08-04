"""Consensus forward estimates, derived from market data — never from the model.

The design contract (§5.3) is that the system may use a *consensus* forward
estimate but the LLM never supplies one: forward EPS is derived arithmetically
as `price / forward_pe`, both of which are observed. That keeps the "no invented
figures" invariant intact while giving the valuation something forward-looking
to stand on instead of pure history.

**Why this is a cross-check and usually not a growth input.**

VAL-17 made the DCF base `mid_cycle` — the median FCF margin over five years
applied to current revenue — precisely so that one unrepresentative year cannot
set the level. Consensus forward EPS growth measures the change from *trailing*
earnings to next year's. On a company whose trailing year was depressed, both
numbers are pricing the same recovery: KO's base was normalized $5.30B → $10.21B,
and its trailing-to-forward P/E (28.81 → 24.84) implies ~16% earnings growth for
the same reason. Applying that growth on top of that base counts the recovery
twice. This is the identical trap VAL-17 avoided by taking growth off revenue
rather than off FCF.

So the rule here is:

  base is `ttm` (nothing normalized)  → consensus sets the year-1 growth rate
  base is normalized (mid_cycle etc.) → consensus is a LEVEL cross-check only

The cross-check is the more valuable half. Two independent estimates of
normalized forward earning power — one from five years of filings, one from what
the market is paying for next year — either agree, which is corroboration, or
they don't, which is the single most useful thing an analyst can be told. On KO
they disagree sharply: the filings say ~$10.2B is normal, consensus implies the
market does not expect a return to that level next year.
"""

from __future__ import annotations

from typing import Any, Optional

# Outside these the forward P/E is not a usable consensus signal.
_FORWARD_PE_BOUNDS = (3.0, 100.0)
# Implied growth beyond this is an artefact of a distorted trailing year, not an
# estimate. Consensus one-year EPS growth above ~50% for a large cap is nearly
# always a depressed trailing denominator rather than a real forecast, and that
# is exactly the case where the trailing/forward pair cannot be trusted as a
# level either. Measured on the 2026-08-01 slices, a looser +100% bound admitted
# NVDA (+163%), QCOM (+106%), CRM (+99%) and CVX (+93%) — none of which is a
# credible consensus estimate. Only KO (+16%) survives, and that is the honest
# outcome: the free forward-P/E field is unreliable for most of this universe.
_IMPLIED_GROWTH_BOUNDS = (-0.40, 0.50)
# Divergence beyond this between the filing-normalized base and the
# consensus-implied level is worth putting in front of the writer.
_MATERIAL_DIVERGENCE = 0.20


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def consensus_forward_eps(state: dict) -> dict[str, Any]:
    """Forward EPS and implied growth, derived from price and forward P/E.

    Returns a self-describing block. `available` is False with a stated reason
    whenever any input is missing — this must degrade quietly, because forward
    P/E comes from a free market-data source that is regularly absent.
    """
    subject = ((state.get("comps_engine") or {}).get("subject") or {})
    price = _num(subject.get("price"))
    forward_pe = _num(subject.get("forward_pe"))
    trailing_pe = _num(subject.get("trailing_pe"))

    block: dict[str, Any] = {
        "available": False,
        "source": "consensus_forward_eps_from_price_over_forward_pe",
        "price": price,
        "forward_pe": forward_pe,
        "trailing_pe": trailing_pe,
    }

    if price is None or forward_pe is None:
        block["reason"] = "no forward P/E or price on the comps subject row"
        return block
    low, high = _FORWARD_PE_BOUNDS
    if not (low <= forward_pe <= high):
        block["reason"] = f"forward P/E {forward_pe:.1f} outside {low:.0f}-{high:.0f}"
        return block

    forward_eps = price / forward_pe
    block["forward_eps"] = forward_eps
    block["available"] = True

    # Implied growth from the P/E pair rather than from a filed EPS: both
    # multiples are struck on the same price, so the price cancels and what is
    # left is purely the earnings ratio the market is using.
    if trailing_pe and trailing_pe > 0:
        implied = (trailing_pe / forward_pe) - 1.0
        lo, hi = _IMPLIED_GROWTH_BOUNDS
        if lo <= implied <= hi:
            block["implied_eps_growth"] = implied
        else:
            block["implied_eps_growth"] = None
            block["growth_reason"] = (
                f"implied growth {implied:.0%} outside {lo:.0%}-{hi:.0%}; the "
                "trailing multiple is distorted, so the pair is not a usable "
                "growth signal"
            )
    else:
        block["implied_eps_growth"] = None
        block["growth_reason"] = "no trailing P/E to pair with"
    return block


def cash_conversion(state: dict) -> Optional[float]:
    """Free cash flow per dollar of net income, from the filing.

    Used to translate a consensus *earnings* estimate into the *cash flow* the
    DCF actually discounts. A company that converts 70 cents of every earnings
    dollar into free cash should not have its consensus EPS read as FCF.
    """
    from .valuation_engine import fcf_history_from_statements

    history = fcf_history_from_statements(
        state.get("cash_flow_statement") or {}, state.get("income_statement") or {}
    )
    income = (state.get("income_statement") or {}).get("current_annual") or {}
    net_income_cell = income.get("NetIncomeLoss")
    net_income = _num(
        net_income_cell.get("value") if isinstance(net_income_cell, dict) else net_income_cell
    )
    if not history or not net_income or net_income <= 0:
        return None
    current = next((row for row in history if row["rank"] == 0), None)
    if not current:
        return None
    ratio = float(current["fcf"]) / net_income
    # A ratio outside this range is a mismatched period or a one-off, not a
    # durable conversion rate.
    return ratio if 0.1 <= ratio <= 3.0 else None


def consensus_cross_check(
    state: dict, *, engine_base_fcf: Optional[float], base_fcf_method: str
) -> dict[str, Any]:
    """Compare the filing-normalized base against the consensus-implied level.

    This is the half of the forward estimate that earns its keep. Two
    independent readings of normalized forward earning power: agreement is
    corroboration, disagreement is the most useful thing the writer can be told.
    """
    forward = consensus_forward_eps(state)
    result: dict[str, Any] = {"forward": forward, "applied_as": "cross_check"}
    if not forward.get("available"):
        result["available"] = False
        return result

    # If the trailing/forward pair was already rejected as a growth signal, the
    # forward EPS behind it is no more trustworthy as a *level*. Observed on the
    # 2026-08-01 slices: NVDA's forward P/E of 15.6 against 41.0 trailing implies
    # earnings nearly tripling, and reading that as consensus produced a $251B
    # forward FCF against a $96B run-rate. Free market-data forward multiples are
    # regularly stale or wrong; one bad field must not generate a confident
    # "the market disagrees with the filings" disclosure.
    if forward.get("implied_eps_growth") is None:
        result["available"] = False
        result["reason"] = (
            "forward multiple not corroborated by the trailing pair "
            f"({forward.get('growth_reason')}) — not used as a level either"
        )
        return result

    shares = _num(
        ((state.get("cash_flow_statement") or {}).get("live_market") or {}).get(
            "shares_outstanding"
        )
    )
    conversion = cash_conversion(state)
    if not shares or conversion is None or engine_base_fcf in (None, 0):
        result["available"] = False
        result["reason"] = (
            "cannot translate consensus EPS to a cash-flow level "
            f"(shares={bool(shares)}, cash_conversion={conversion is not None})"
        )
        return result

    implied_fcf = forward["forward_eps"] * shares * conversion
    divergence = (implied_fcf / float(engine_base_fcf)) - 1.0
    result.update(
        {
            "available": True,
            "shares_outstanding": shares,
            "cash_conversion": conversion,
            "consensus_implied_fcf": implied_fcf,
            "engine_base_fcf": engine_base_fcf,
            "base_fcf_method": base_fcf_method,
            "divergence_vs_engine_base": divergence,
            "material": abs(divergence) >= _MATERIAL_DIVERGENCE,
        }
    )
    if result["material"]:
        direction = "above" if divergence > 0 else "below"
        result["disclosure"] = (
            f"Consensus cross-check: forward EPS of "
            f"{forward['forward_eps']:.2f} implies about "
            f"${implied_fcf / 1e9:.2f}B of free cash flow next year at the "
            f"filed {conversion:.0%} cash conversion — {abs(divergence):.0%} "
            f"{direction} the {base_fcf_method} base of "
            f"${float(engine_base_fcf) / 1e9:.2f}B this valuation discounts. "
            "The filings and the market disagree about normal earning power; "
            "say which one this thesis is taking and why."
        )
    else:
        result["disclosure"] = (
            f"Consensus cross-check: consensus-implied forward free cash flow "
            f"is within {abs(divergence):.0%} of the {base_fcf_method} base "
            "— the filings and the market agree on normal earning power."
        )
    return result


def consensus_growth_for_year_one(
    state: dict, *, base_fcf_method: str
) -> tuple[Optional[float], str]:
    """Consensus-implied growth, but ONLY when the base was not normalized.

    On a normalized base the consensus expectation and the normalization are
    pricing the same recovery, so applying both counts it twice. Returns
    `(None, reason)` in that case rather than silently declining.
    """
    if base_fcf_method != "ttm":
        return None, (
            f"not applied: the base is {base_fcf_method}-normalized, which "
            "already prices the recovery that consensus growth measures — "
            "applying both would count it twice. Used as a level cross-check."
        )
    forward = consensus_forward_eps(state)
    if not forward.get("available"):
        return None, f"not applied: {forward.get('reason')}"
    growth = forward.get("implied_eps_growth")
    if growth is None:
        return None, f"not applied: {forward.get('growth_reason')}"
    return growth, (
        f"year 1 grown at the consensus-implied {growth:+.1%} "
        f"(trailing P/E {forward['trailing_pe']:.1f} vs forward "
        f"{forward['forward_pe']:.1f}); later years at the historical trend"
    )
