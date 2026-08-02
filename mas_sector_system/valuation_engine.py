"""Deterministic valuation helpers for deep-dive agents.

DCF and peer comps are computed in Python from SEC statements + yfinance.
LLM nodes narrate these numbers — they do not invent the core math.
"""

from __future__ import annotations

from copy import deepcopy
from statistics import median
from typing import Any, Optional


ARGUED_INPUT_BOUNDS: dict[str, tuple[float, float]] = {
    "wacc": (0.05, 0.20),
    "g_terminal": (0.0, 0.035),
    "g_high": (-0.10, 0.40),
    "high_growth_years": (3, 10),
    "fade_years": (2, 10),
    # For justified_multiple these are peer-median multipliers. Absolute
    # metric bounds are applied as a second clamp below.
    "justified_multiple": (0.25, 3.0),
}

_MULTIPLE_ABSOLUTE_BOUNDS: dict[str, tuple[float, float]] = {
    "forward_pe": (3.0, 100.0),
    "trailing_pe": (3.0, 150.0),
    "ev_ebitda": (2.0, 60.0),
    "price_sales": (0.2, 40.0),
}

_MULTIPLE_TO_COMPS_KEY = {
    "forward_pe": "forward_pe",
    "trailing_pe": "trailing_pe",
    "ev_ebitda": "ev_to_ebitda",
    "price_sales": "price_to_sales",
}

_ALLOWED_EVIDENCE_ROOTS = {
    "canonical_metrics",
    "income_statement",
    "balance_sheet",
    "cash_flow_statement",
    "comps_engine",
    "dcf_engine",
    "business_overview",
    "macro_regime_assessment",
    "management_assessment",
    "capital_allocation_assessment",
}

_BASE_FCF_METHODS = {"ttm", "avg_3y", "avg_5y", "mid_cycle"}


# Default peer sets by sector keyword (uppercase match against state["sector"]).
SECTOR_PEERS: dict[str, list[str]] = {
    "SEMICONDUCTOR": ["AMD", "AVGO", "INTC", "TSM", "QCOM", "AMAT"],
    "TECHNOLOGY": ["AAPL", "MSFT", "GOOGL", "AMZN", "META"],
    "SOFTWARE": ["MSFT", "ORCL", "CRM", "ADBE", "NOW", "INTU"],
    "FINANCIAL": ["JPM", "BAC", "WFC", "GS", "MS", "C"],
    "BANK": ["JPM", "BAC", "WFC", "USB", "PNC"],
    "ENERGY": ["XOM", "CVX", "COP", "SLB", "EOG"],
    "HEALTHCARE": ["UNH", "JNJ", "LLY", "PFE", "ABBV"],
    "CONSUMER": ["AMZN", "WMT", "COST", "HD", "MCD"],
    "INDUSTRIAL": ["CAT", "DE", "HON", "GE", "UPS"],
}

# Sector → (WACC, terminal growth). Explicit defaults so DCF never refuses.
SECTOR_WACC: dict[str, tuple[float, float]] = {
    "SEMICONDUCTOR": (0.10, 0.03),
    "TECHNOLOGY": (0.09, 0.03),
    "SOFTWARE": (0.09, 0.03),
    "FINANCIAL": (0.09, 0.025),
    "BANK": (0.09, 0.025),
    "ENERGY": (0.10, 0.02),
    "HEALTHCARE": (0.08, 0.03),
    "DEFAULT": (0.09, 0.025),
}


def _sector_key(sector: str) -> str:
    s = (sector or "").upper()
    for key in SECTOR_PEERS:
        if key in s:
            return key
    for key in SECTOR_WACC:
        if key != "DEFAULT" and key in s:
            return key
    return "DEFAULT"


def default_peers_for_sector(sector: str, *, subject: Optional[str] = None) -> list[str]:
    key = _sector_key(sector)
    peers = list(SECTOR_PEERS.get(key) or ["AAPL", "MSFT", "GOOGL", "AMZN"])
    subj = (subject or "").strip().upper()
    return [p for p in peers if p != subj][:6]


def _line_value(period_block: Any, *keys: str) -> Optional[float]:
    """Pull a numeric value from a statement period dict."""
    if not isinstance(period_block, dict):
        return None
    for key in keys:
        cell = period_block.get(key)
        if isinstance(cell, dict) and cell.get("value") is not None:
            try:
                return float(cell["value"])
            except (TypeError, ValueError):
                continue
        if isinstance(cell, (int, float)) and not isinstance(cell, bool):
            return float(cell)
    return None


def _period(statement: Any, name: str) -> dict:
    if not isinstance(statement, dict):
        return {}
    block = statement.get(name)
    return block if isinstance(block, dict) else {}


def _live_market_from_state(state: dict) -> dict[str, Any]:
    for stmt_key in ("income_statement", "balance_sheet", "cash_flow_statement"):
        stmt = state.get(stmt_key) or {}
        if isinstance(stmt, dict) and isinstance(stmt.get("live_market"), dict):
            lm = stmt["live_market"]
            if lm.get("price") is not None or lm.get("market_cap") is not None:
                return lm
    return {}


def extract_fcf_series(cash_flow: dict) -> dict[str, Optional[float]]:
    out: dict[str, Optional[float]] = {}
    for period in (
        "current_annual",
        "prior_annual",
        "current_quarter",
        "prior_quarter",
    ):
        p = _period(cash_flow, period)
        fcf = _line_value(p, "FreeCashFlow")
        if fcf is None:
            ocf = _line_value(p, "NetCashFromOperatingActivities")
            capex = _line_value(p, "CapitalExpenditures")
            if ocf is not None and capex is not None:
                fcf = ocf - abs(capex)
        out[period] = fcf
    return out


def fcf_history(state: dict) -> list[dict[str, Any]]:
    """Return filing-derived annual FCF and revenue, newest first.

    Rows are aligned by the producer's explicit rank. Negative FCF is retained.
    Missing ranks are omitted rather than synthesized.
    """
    cash_rows = (state.get("cash_flow_statement") or {}).get("annual_series") or []
    income_rows = (state.get("income_statement") or {}).get("annual_series") or []
    income_by_rank = {
        row.get("rank"): row
        for row in income_rows
        if isinstance(row, dict) and isinstance(row.get("rank"), int)
    }
    history: list[dict[str, Any]] = []
    for cash_row in cash_rows:
        if not isinstance(cash_row, dict) or not isinstance(cash_row.get("rank"), int):
            continue
        rank = cash_row["rank"]
        fcf = _line_value(cash_row, "FreeCashFlow")
        if fcf is None:
            ocf = _line_value(cash_row, "NetCashFromOperatingActivities")
            capex = _line_value(cash_row, "CapitalExpenditures")
            if ocf is not None and capex is not None:
                fcf = ocf - abs(capex)
        if fcf is None:
            continue
        income_row = income_by_rank.get(rank) or {}
        history.append(
            {
                "rank": rank,
                "fy": cash_row.get("fy") or income_row.get("fy"),
                "fcf": float(fcf),
                "revenue": _line_value(income_row, "Revenues"),
            }
        )
    history.sort(key=lambda row: row["rank"])
    return history


def _evidence_value(state: dict, field_id: str) -> Any:
    if not isinstance(field_id, str) or not field_id.strip():
        return None
    parts = field_id.strip().split(".")
    if parts[0] not in _ALLOWED_EVIDENCE_ROOTS:
        return None
    current: Any = state
    for index, part in enumerate(parts):
        if isinstance(current, dict):
            if part in current:
                current = current[part]
                continue
            if parts[0] == "canonical_metrics":
                by_id = current.get("by_id")
                if isinstance(by_id, dict) and part in by_id:
                    current = by_id[part]
                    continue
            if part == "peer_rows" and isinstance(
                current.get("candidate_rows") or current.get("peers"), list
            ):
                current = current.get("candidate_rows") or current["peers"]
                continue
            return None
        if isinstance(current, list):
            match = next(
                (
                    item
                    for item in current
                    if isinstance(item, dict)
                    and str(item.get("ticker") or item.get("id") or item.get("rank"))
                    == part
                ),
                None,
            )
            if match is None:
                return None
            current = match
            continue
        if index < len(parts):
            return None
    if isinstance(current, dict) and "value" in current:
        current = current.get("value")
    return current


def _has_resolvable_evidence(state: dict, evidence: Any) -> bool:
    if not isinstance(evidence, list) or not evidence:
        return False
    return any(_evidence_value(state, field_id) is not None for field_id in evidence)


def _default_value(engine_default: dict, parameter: str) -> Any:
    if parameter == "base_fcf_method":
        return "ttm"
    assumptions = engine_default.get("assumptions")
    if isinstance(assumptions, dict) and parameter in assumptions:
        return assumptions[parameter]
    return engine_default.get(parameter)


# Parameters expressed as decimal rates (0.11 == 11%). An LLM asked for "a
# defensible WACC" will sometimes answer 11 and sometimes 0.11 — observed live
# on 2026-07-29, where NVDA returned wacc=[11,13] and g_high=[20,30] while CRM
# and JPM returned proper decimals in the same batch. Clamping 11 to the 0.20
# ceiling silently produced a 20% WACC and a 40% growth rate, destroying every
# argument in that run. Normalising is strictly better than clamping: a rate
# above 1.0 cannot be a real discount or growth rate, so it is a unit error.
_RATE_PARAMETERS = frozenset({"wacc", "g_high", "g_terminal"})


def _normalize_rate_scale(
    value: Any, *, parameter: str, warnings: list[str]
) -> Any:
    """Convert a percent-scale rate (11) to decimal (0.11); pass others through."""
    if parameter not in _RATE_PARAMETERS:
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number != number or abs(number) <= 1.0:
        return value
    converted = number / 100.0
    warnings.append(
        f"{parameter} interpreted as a percentage: {number} → {converted} "
        "(rates must be decimals; a value above 1.0 cannot be a real rate)"
    )
    return converted


def _clamp_number(
    value: Any,
    *,
    parameter: str,
    bounds: tuple[float, float],
    integer: bool,
    warnings: list[str],
) -> Optional[float | int]:
    value = _normalize_rate_scale(value, parameter=parameter, warnings=warnings)
    try:
        number = float(value)
    except (TypeError, ValueError):
        warnings.append(f"{parameter} rejected: non-numeric value {value!r}")
        return None
    if number != number:
        warnings.append(f"{parameter} rejected: NaN is not permitted")
        return None
    if integer:
        rounded = int(round(number))
        if rounded != number:
            warnings.append(f"{parameter} rounded to integer {rounded}")
        number = float(rounded)
    clamped = max(bounds[0], min(number, bounds[1]))
    if clamped != number:
        warnings.append(
            f"{parameter} clamped from {number:g} to {clamped:g} "
            f"within [{bounds[0]:g}, {bounds[1]:g}]"
        )
    return int(clamped) if integer else clamped


def _argument_band(archetype: str, parameter: str) -> Optional[tuple[float, float]]:
    try:
        from .valuation_doctrine import band_for

        return band_for(archetype, parameter)
    except (ImportError, KeyError, TypeError, ValueError):
        return None


def validate_argued_inputs(
    proposed: dict,
    *,
    archetype: str,
    engine_default: dict,
    state: dict,
) -> tuple[dict, list[str]]:
    """Validate evidence-backed argued ranges and enforce all hard clamps."""
    accepted: dict[str, Any] = {"band_dissents": []}
    warnings: list[str] = []
    arguments = proposed.get("arguments") if isinstance(proposed, dict) else None
    if not isinstance(arguments, list):
        arguments = []

    for raw in arguments:
        if not isinstance(raw, dict):
            warnings.append("argued input rejected: argument is not an object")
            continue
        parameter = raw.get("parameter")
        if parameter not in {*ARGUED_INPUT_BOUNDS, "base_fcf_method"}:
            warnings.append(f"argued input rejected: unsupported parameter {parameter!r}")
            continue
        if not _has_resolvable_evidence(state, raw.get("evidence")):
            warnings.append(
                f"{parameter} rejected: evidence list is empty or unresolvable; "
                f"reverted to engine default {_default_value(engine_default, parameter)!r}"
            )
            continue

        if parameter == "base_fcf_method":
            # The enum may arrive as `value`, `argued_value`, or — because the
            # critique prompt asks for a uniform shape across all parameters —
            # inside `argued_range` as ["<method>", "<method>"]. Accept all
            # three: a schema divergence here silently disabled cash-flow
            # normalisation on every live run of 2026-07-29.
            method = raw.get("value", raw.get("argued_value"))
            if method is None:
                rng = raw.get("argued_range")
                if isinstance(rng, (list, tuple)) and rng:
                    candidates = [m for m in rng if isinstance(m, str)]
                    # Prefer the more conservative (normalised) method when the
                    # two corners disagree, e.g. ["avg_3y", "ttm"] → avg_3y.
                    for preferred in ("mid_cycle", "avg_5y", "avg_3y", "ttm"):
                        if preferred in candidates:
                            method = preferred
                            break
            if method not in _BASE_FCF_METHODS:
                warnings.append(
                    f"base_fcf_method rejected: {method!r} is not one of "
                    f"{sorted(_BASE_FCF_METHODS)}"
                )
                continue
            accepted[parameter] = {
                **raw,
                "value": method,
                "engine_default": _default_value(engine_default, parameter),
            }
            continue

        argued_range = raw.get("argued_range")
        if not isinstance(argued_range, (list, tuple)) or len(argued_range) != 2:
            warnings.append(f"{parameter} rejected: argued_range must contain [lo, hi]")
            continue
        integer = parameter in {"high_growth_years", "fade_years"}
        bounds = ARGUED_INPUT_BOUNDS[parameter]
        lo = _clamp_number(
            argued_range[0],
            parameter=parameter,
            bounds=bounds,
            integer=integer,
            warnings=warnings,
        )
        hi = _clamp_number(
            argued_range[1],
            parameter=parameter,
            bounds=bounds,
            integer=integer,
            warnings=warnings,
        )
        if lo is None or hi is None:
            continue
        if lo > hi:
            lo, hi = hi, lo
            warnings.append(f"{parameter} argued_range reordered to [{lo:g}, {hi:g}]")

        band = _argument_band(archetype, parameter)
        outside_band = bool(band and (lo < band[0] or hi > band[1]))
        reasoning = str(raw.get("reasoning") or "").strip()
        if outside_band and not reasoning:
            warnings.append(
                f"{parameter} rejected: range [{lo:g}, {hi:g}] is outside "
                f"the {archetype} band {band} and requires reasoning"
            )
            continue
        sanitized = {
            **raw,
            "argued_range": [lo, hi],
            "engine_default": _default_value(engine_default, parameter),
        }
        accepted[parameter] = sanitized
        if outside_band:
            accepted["band_dissents"].append(
                {
                    "parameter": parameter,
                    "argued_range": [lo, hi],
                    "archetype_band": list(band),
                    "reasoning": reasoning,
                    "evidence": list(raw.get("evidence") or []),
                }
            )

    justified = proposed.get("justified_multiple") if isinstance(proposed, dict) else None
    if isinstance(justified, dict):
        parameter = "justified_multiple"
        if not _has_resolvable_evidence(state, justified.get("evidence")):
            warnings.append(
                "justified_multiple rejected: evidence list is empty or unresolvable"
            )
        else:
            metric = str(justified.get("metric") or "")
            comps_key = _MULTIPLE_TO_COMPS_KEY.get(metric)
            peer_medians = engine_default.get("peer_medians") or {}
            peer_median = peer_medians.get(comps_key) if comps_key else None
            try:
                peer_median_f = float(peer_median)
            except (TypeError, ValueError):
                peer_median_f = 0.0
            if metric not in _MULTIPLE_ABSOLUTE_BOUNDS or peer_median_f <= 0:
                warnings.append(
                    f"justified_multiple rejected: unsupported metric {metric!r} "
                    "or unavailable peer median"
                )
            else:
                ratio_bounds = ARGUED_INPUT_BOUNDS["justified_multiple"]
                absolute = _MULTIPLE_ABSOLUTE_BOUNDS[metric]
                bounds = (
                    max(absolute[0], ratio_bounds[0] * peer_median_f),
                    min(absolute[1], ratio_bounds[1] * peer_median_f),
                )
                argued_range = justified.get("argued_range")
                if (
                    not isinstance(argued_range, (list, tuple))
                    or len(argued_range) != 2
                ):
                    warnings.append(
                        "justified_multiple rejected: argued_range must contain [lo, hi]"
                    )
                else:
                    lo = _clamp_number(
                        argued_range[0],
                        parameter=parameter,
                        bounds=bounds,
                        integer=False,
                        warnings=warnings,
                    )
                    hi = _clamp_number(
                        argued_range[1],
                        parameter=parameter,
                        bounds=bounds,
                        integer=False,
                        warnings=warnings,
                    )
                    if lo is not None and hi is not None:
                        if lo > hi:
                            lo, hi = hi, lo
                            warnings.append(
                                "justified_multiple argued_range reordered "
                                f"to [{lo:g}, {hi:g}]"
                            )
                        band = _argument_band(archetype, parameter)
                        reasoning = str(justified.get("reasoning") or "").strip()
                        outside_band = bool(
                            band and (lo < band[0] or hi > band[1])
                        )
                        if outside_band and not reasoning:
                            warnings.append(
                                "justified_multiple rejected: out-of-band dissent "
                                "requires reasoning"
                            )
                        else:
                            accepted[parameter] = {
                                **justified,
                                "argued_range": [lo, hi],
                                "peer_median": peer_median_f,
                            }
                            if outside_band:
                                accepted["band_dissents"].append(
                                    {
                                        "parameter": parameter,
                                        "metric": metric,
                                        "argued_range": [lo, hi],
                                        "archetype_band": list(band),
                                        "reasoning": reasoning,
                                        "evidence": list(
                                            justified.get("evidence") or []
                                        ),
                                    }
                                )

    peer_changes = proposed.get("peer_changes") if isinstance(proposed, dict) else None
    if isinstance(peer_changes, list):
        accepted_changes = []
        for change in peer_changes:
            if not isinstance(change, dict):
                warnings.append("peer change rejected: change is not an object")
                continue
            if not _has_resolvable_evidence(state, change.get("evidence")):
                warnings.append(
                    f"peer change for {change.get('ticker')!r} rejected: "
                    "evidence list is empty or unresolvable"
                )
                continue
            if change.get("action") not in {"include", "exclude"}:
                warnings.append(
                    f"peer change for {change.get('ticker')!r} rejected: invalid action"
                )
                continue
            accepted_changes.append(dict(change))
        accepted["peer_changes"] = accepted_changes

    # The Gordon-spread rule is enforced after all independent clamps so it
    # applies whether either input was argued or inherited from the engine.
    default_wacc = _default_value(engine_default, "wacc")
    default_g_terminal = _default_value(engine_default, "g_terminal")
    wacc_range = (accepted.get("wacc") or {}).get(
        "argued_range", [default_wacc, default_wacc]
    )
    terminal = accepted.get("g_terminal")
    terminal_range = (terminal or {}).get(
        "argued_range", [default_g_terminal, default_g_terminal]
    )
    if all(isinstance(v, (int, float)) for v in [*wacc_range, *terminal_range]):
        constrained = [
            min(float(terminal_range[i]), float(wacc_range[i]) - 0.015)
            for i in (0, 1)
        ]
        constrained = [max(0.0, value) for value in constrained]
        if constrained != [float(terminal_range[0]), float(terminal_range[1])]:
            warnings.append(
                "g_terminal clamped to preserve g_terminal <= wacc - 0.015: "
                f"{list(terminal_range)} -> {constrained}"
            )
        if terminal or constrained != [default_g_terminal, default_g_terminal]:
            source = terminal or {
                "parameter": "g_terminal",
                "reasoning": "mathematical Gordon-growth constraint",
                "evidence": list(
                    (accepted.get("wacc") or {}).get("evidence") or []
                ),
                "engine_default": default_g_terminal,
                "constraint_applied": True,
            }
            accepted["g_terminal"] = {**source, "argued_range": constrained}

    if not accepted["band_dissents"]:
        accepted.pop("band_dissents")
    return accepted, warnings


def extract_income_basics(income: dict) -> dict[str, Optional[float]]:
    cur = _period(income, "current_annual")
    prior = _period(income, "prior_annual")
    return {
        "revenue_current": _line_value(cur, "Revenues"),
        "revenue_prior": _line_value(prior, "Revenues"),
        "net_income_current": _line_value(cur, "NetIncomeLoss"),
        "net_income_prior": _line_value(prior, "NetIncomeLoss"),
        "eps_diluted_current": _line_value(cur, "EarningsPerShareDiluted", "EPS_Diluted"),
        "eps_diluted_prior": _line_value(prior, "EarningsPerShareDiluted", "EPS_Diluted"),
        "operating_income_current": _line_value(cur, "OperatingIncomeLoss"),
        "shares_diluted": _line_value(
            cur,
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageSharesDiluted",
        ),
    }


def _net_debt(balance: dict) -> Optional[float]:
    cur = _period(balance, "current_annual")
    cash = _line_value(cur, "CashAndCashEquivalents", "ShortTermInvestments") or 0.0
    st = _line_value(cur, "ShortTermDebt") or 0.0
    lt = _line_value(cur, "LongTermDebt") or 0.0
    # If we have neither cash nor debt tags, return None rather than 0.
    if (
        _line_value(cur, "CashAndCashEquivalents", "ShortTermInvestments") is None
        and _line_value(cur, "ShortTermDebt") is None
        and _line_value(cur, "LongTermDebt") is None
    ):
        return None
    return (st + lt) - cash


def compute_dcf(
    *,
    cash_flow: dict,
    income: dict,
    balance: dict,
    live_market: dict,
    sector: str,
    ticker: str = "",
    high_growth_years: int = 5,
    fade_years: int = 5,
) -> dict[str, Any]:
    """Multi-stage FCF DCF with explicit sector defaults.

    Stages:
      1. high_growth_years at g_high (from history, capped)
      2. fade_years linear fade from g_high → g_terminal
      3. Gordon terminal value at g_terminal

    Returns a structured dict safe to JSON-serialize into prompts.
    """
    fcf = extract_fcf_series(cash_flow)
    basics = extract_income_basics(income)
    base_fcf = fcf.get("current_annual")
    prior_fcf = fcf.get("prior_annual")

    wacc, g_term = SECTOR_WACC.get(_sector_key(sector), SECTOR_WACC["DEFAULT"])

    # Historical growth signals
    fcf_growth = None
    if base_fcf is not None and prior_fcf is not None and prior_fcf != 0:
        fcf_growth = (base_fcf / prior_fcf) - 1.0

    rev_c, rev_p = basics["revenue_current"], basics["revenue_prior"]
    rev_growth = None
    if rev_c is not None and rev_p is not None and rev_p != 0:
        rev_growth = (rev_c / rev_p) - 1.0

    # Cap high growth — don't extrapolate 100%+ forever.
    raw_g = fcf_growth if fcf_growth is not None else rev_growth
    if raw_g is None:
        g_high = 0.08
        g_source = "default_8pct_no_history"
    else:
        g_high = max(-0.05, min(float(raw_g), 0.35))
        g_source = "fcf_yoy" if fcf_growth is not None else "revenue_yoy"
        if abs(g_high - raw_g) > 1e-9:
            g_source += f"_capped_from_{raw_g:.1%}"

    price = live_market.get("price")
    try:
        price_f = float(price) if price is not None else None
    except (TypeError, ValueError):
        price_f = None

    shares = live_market.get("shares_outstanding") or basics.get("shares_diluted")
    try:
        shares_f = float(shares) if shares is not None else None
    except (TypeError, ValueError):
        shares_f = None

    mcap = live_market.get("market_cap")
    try:
        mcap_f = float(mcap) if mcap is not None else None
    except (TypeError, ValueError):
        mcap_f = None

    net_debt = _net_debt(balance)

    result: dict[str, Any] = {
        "method": "multi_stage_fcf_dcf",
        "ticker": (ticker or "").upper() or None,
        "sector": sector,
        "inputs": {
            "base_fcf_annual": base_fcf,
            "prior_fcf_annual": prior_fcf,
            "fcf_yoy_growth": fcf_growth,
            "revenue_yoy_growth": rev_growth,
            "price": price_f,
            "shares_outstanding": shares_f,
            "market_cap": mcap_f,
            "net_debt": net_debt,
            "eps_diluted_current": basics.get("eps_diluted_current"),
            "net_income_current": basics.get("net_income_current"),
        },
        "assumptions": {
            "wacc": wacc,
            "g_high": g_high,
            "g_high_source": g_source,
            "g_terminal": g_term,
            "high_growth_years": high_growth_years,
            "fade_years": fade_years,
            "note": (
                "WACC and terminal growth are sector defaults, not company-specific "
                "estimates. Change g_high / WACC to stress the model."
            ),
        },
        "projections": [],
        "enterprise_value": None,
        "equity_value": None,
        "fair_value_per_share": None,
        "fair_value_range": None,
        "implied_upside_vs_price": None,
        "epv_per_share": None,
        "trailing_pe": None,
        "confidence": "moderate",
        "errors": [],
        "warnings": [],
    }

    if base_fcf is None or base_fcf <= 0:
        result["errors"].append(
            "Cannot run FCF DCF: base annual FreeCashFlow missing or non-positive."
        )
        result["confidence"] = "none"
        return result

    if wacc <= g_term:
        result["errors"].append(f"Invalid WACC ({wacc}) <= terminal growth ({g_term}).")
        return result

    # Build projection path
    projections: list[dict[str, Any]] = []
    fcf_t = float(base_fcf)
    total_pv = 0.0
    year = 0

    for i in range(1, high_growth_years + 1):
        year = i
        fcf_t = fcf_t * (1.0 + g_high)
        pv = fcf_t / ((1.0 + wacc) ** year)
        total_pv += pv
        projections.append(
            {
                "year": year,
                "stage": "high_growth",
                "growth": g_high,
                "fcf": fcf_t,
                "pv": pv,
            }
        )

    for j in range(1, fade_years + 1):
        year = high_growth_years + j
        # Linear fade of growth rate
        weight = j / float(fade_years)
        g = g_high + (g_term - g_high) * weight
        fcf_t = fcf_t * (1.0 + g)
        pv = fcf_t / ((1.0 + wacc) ** year)
        total_pv += pv
        projections.append(
            {
                "year": year,
                "stage": "fade",
                "growth": g,
                "fcf": fcf_t,
                "pv": pv,
            }
        )

    # Terminal value at end of fade (Gordon on next year's FCF)
    fcf_terminal_next = fcf_t * (1.0 + g_term)
    tv = fcf_terminal_next / (wacc - g_term)
    tv_pv = tv / ((1.0 + wacc) ** year)
    total_pv += tv_pv

    result["projections"] = projections
    result["terminal_value"] = tv
    result["terminal_value_pv"] = tv_pv
    result["enterprise_value"] = total_pv

    # Equity value = EV − net debt (net debt can be negative = net cash)
    if net_debt is not None:
        equity = total_pv - net_debt
    else:
        equity = total_pv
        result["warnings"].append(
            "Net debt not available from balance sheet tags; treating EV as equity value."
        )
    result["equity_value"] = equity

    if shares_f and shares_f > 0:
        fv = equity / shares_f
        result["fair_value_per_share"] = fv
        # Sensitivity band: ±1pp WACC roughly
        # Approximate range: re-run not needed — use ±15% band on FV as simple range
        result["fair_value_range"] = {
            "low": fv * 0.85,
            "base": fv,
            "high": fv * 1.15,
            "basis": "±15% band on base DCF (assumption uncertainty, not full re-solve)",
        }
        if price_f and price_f > 0:
            result["implied_upside_vs_price"] = (fv / price_f) - 1.0

    # EPV cross-check: FCF / WACC (no growth), equity-level if net debt known
    epv_ev = float(base_fcf) / wacc
    epv_eq = epv_ev - net_debt if net_debt is not None else epv_ev
    if shares_f and shares_f > 0:
        result["epv_per_share"] = epv_eq / shares_f

    eps = basics.get("eps_diluted_current")
    if price_f and eps and eps > 0:
        result["trailing_pe"] = price_f / eps

    if fcf_growth is not None and fcf_growth > 0.5:
        result["warnings"].append(
            f"FCF grew {fcf_growth:.0%} YoY — g_high capped at {g_high:.0%}; "
            "base case may still be optimistic if growth normalizes faster."
        )
        result["confidence"] = "low_to_moderate"

    if not result["errors"]:
        result["confidence"] = result.get("confidence") or "moderate"

    return result


def format_dcf_for_prompt(dcf: dict[str, Any]) -> str:
    """Human-readable block for the fundamental valuation LLM."""
    lines = ["=== DETERMINISTIC DCF ENGINE (Python — source of truth for math) ==="]
    if dcf.get("errors"):
        lines.append("ERRORS: " + "; ".join(dcf["errors"]))
    if dcf.get("warnings"):
        lines.append("WARNINGS: " + "; ".join(dcf["warnings"]))

    a = dcf.get("assumptions") or {}
    inp = dcf.get("inputs") or {}
    lines.append(
        f"Method: {dcf.get('method')} | Confidence: {dcf.get('confidence')}"
    )
    lines.append(
        f"Base FCF (current annual): {_fmt_money(inp.get('base_fcf_annual'))} | "
        f"Prior FCF: {_fmt_money(inp.get('prior_fcf_annual'))}"
    )
    lines.append(
        f"Assumptions: WACC={_fmt_pct(a.get('wacc'))}, "
        f"g_high={_fmt_pct(a.get('g_high'))} (source: {a.get('g_high_source')}), "
        f"g_terminal={_fmt_pct(a.get('g_terminal'))}, "
        f"explicit={a.get('high_growth_years')}+{a.get('fade_years')} years"
    )
    lines.append(
        f"Enterprise value: {_fmt_money(dcf.get('enterprise_value'))} | "
        f"Equity value: {_fmt_money(dcf.get('equity_value'))} | "
        f"Net debt: {_fmt_money(inp.get('net_debt'))}"
    )
    lines.append(
        f"Fair value / share (base): {_fmt_price(dcf.get('fair_value_per_share'))} | "
        f"Live price: {_fmt_price(inp.get('price'))} | "
        f"Implied upside: {_fmt_pct(dcf.get('implied_upside_vs_price'))}"
    )
    fr = dcf.get("fair_value_range") or {}
    if fr:
        lines.append(
            f"FV range: {_fmt_price(fr.get('low'))} – {_fmt_price(fr.get('high'))} "
            f"({fr.get('basis')})"
        )
    lines.append(
        f"EPV / share (no-growth cross-check): {_fmt_price(dcf.get('epv_per_share'))} | "
        f"Trailing P/E: {_fmt_num(dcf.get('trailing_pe'), 1)}"
    )

    projs = dcf.get("projections") or []
    if projs:
        lines.append("Projection path (year | stage | growth | FCF | PV):")
        for p in projs[:12]:
            lines.append(
                f"  Y{p.get('year')}: {p.get('stage')} g={_fmt_pct(p.get('growth'))} "
                f"FCF={_fmt_money(p.get('fcf'))} PV={_fmt_money(p.get('pv'))}"
            )
        if dcf.get("terminal_value") is not None:
            lines.append(
                f"  Terminal value: {_fmt_money(dcf.get('terminal_value'))} "
                f"(PV {_fmt_money(dcf.get('terminal_value_pv'))})"
            )

    lines.append(
        "INSTRUCTION: Narrate and interpret these figures. Do NOT replace the fair-value "
        "math with invented numbers. You may discuss sensitivity (what if g or WACC moves) "
        "qualitatively and cite the engine outputs as the base case."
    )
    return "\n".join(lines)


def _book_inputs(state: dict) -> dict[str, Any]:
    bal = _period(state.get("balance_sheet") or {}, "current_annual")
    inc = _period(state.get("income_statement") or {}, "current_annual")
    live = _live_market_from_state(state)
    equity = _line_value(bal, "StockholdersEquity")
    ni = _line_value(inc, "NetIncomeLoss")
    shares = live.get("shares_outstanding") or _line_value(
        inc,
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageSharesDiluted",
    )
    price = live.get("price")
    return {
        "book_equity": equity,
        "net_income": ni,
        "shares": shares,
        "price": price,
        "roe": (ni / equity) if ni is not None and equity and equity != 0 else None,
    }


def _excess_return_on_equity(state: dict, *, archetype: str) -> dict[str, Any]:
    """Simple residual-income style: BV + PV of (ROE − r) × equity for N years.

    Not a full bank model — but valid directionally and never FCF DCF.
    """
    ticker = (state.get("ticker") or "").upper() or None
    sector = state.get("sector") or ""
    inp = _book_inputs(state)
    equity = inp.get("book_equity")
    roe = inp.get("roe")
    shares = inp.get("shares")
    price = inp.get("price")
    # Cost of equity: sector default WACC as proxy
    r_e, g = SECTOR_WACC.get(_sector_key(sector), SECTOR_WACC["DEFAULT"])
    result: dict[str, Any] = {
        "method": "excess_return_on_equity",
        "archetype": archetype,
        "ticker": ticker,
        "sector": sector,
        "inputs": {**inp, "cost_of_equity": r_e, "fade_years": 10},
        "assumptions": {
            "cost_of_equity": r_e,
            "fade_years": 10,
            "note": (
                "Residual income: equity_value ≈ BV + Σ PV[(ROE − r_e) × BV_t]. "
                "Bank/insurer FCF DCF is invalid — this is the intentional path."
            ),
        },
        "enterprise_value": None,
        "equity_value": None,
        "fair_value_per_share": None,
        "fair_value_range": None,
        "implied_upside_vs_price": None,
        "confidence": "low_to_moderate",
        "errors": [],
        "warnings": [],
        "projections": [],
    }
    if equity is None or equity <= 0 or roe is None:
        result["errors"].append(
            "excess_return_on_equity requires book equity and ROE (NI / equity)"
        )
        result["confidence"] = "none"
        return result
    if r_e <= 0:
        result["errors"].append(f"invalid cost of equity {r_e}")
        return result

    # Finite residual income: grow BV at retention * ROE; simplify with constant ROE 10y
    years = 10
    bv = float(equity)
    total_pv_ri = 0.0
    for t in range(1, years + 1):
        ri = (float(roe) - r_e) * bv
        pv = ri / ((1.0 + r_e) ** t)
        total_pv_ri += pv
        result["projections"].append(
            {"year": t, "book_equity": bv, "residual_income": ri, "pv": pv}
        )
        # plowback approx 50% if ROE>r else 0
        g_bv = max(0.0, min(0.08, float(roe) * 0.5))
        bv = bv * (1.0 + g_bv)

    equity_val = float(equity) + total_pv_ri
    result["equity_value"] = equity_val
    if shares and float(shares) > 0:
        fv = equity_val / float(shares)
        result["fair_value_per_share"] = fv
        result["fair_value_range"] = {
            "low": fv * 0.85,
            "base": fv,
            "high": fv * 1.15,
            "basis": "±15% band on residual-income base (not a full stress test)",
        }
        if price and float(price) > 0:
            result["implied_upside_vs_price"] = (fv / float(price)) - 1.0
    result["warnings"].append(
        "Residual-income model is simplified (constant ROE fade window) — "
        "not a regulatory stress test or full DDM."
    )
    return result


def _ffo_or_nav_valuation(state: dict, *, archetype: str) -> dict[str, Any]:
    """Equity REIT: use derived FFO if present; never net-income P/E as primary."""
    ticker = (state.get("ticker") or "").upper() or None
    sector = state.get("sector") or ""
    inc = _period(state.get("income_statement") or {}, "current_annual")
    live = _live_market_from_state(state)
    ffo = _line_value(inc, "FFO")
    ni = _line_value(inc, "NetIncomeLoss")
    shares = live.get("shares_outstanding") or _line_value(
        inc,
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageSharesDiluted",
    )
    price = live.get("price")
    mcap = live.get("market_cap")
    result: dict[str, Any] = {
        "method": "ffo_nav",
        "archetype": archetype,
        "ticker": ticker,
        "sector": sector,
        "inputs": {
            "ffo": ffo,
            "net_income": ni,
            "shares": shares,
            "price": price,
            "market_cap": mcap,
        },
        "assumptions": {
            "note": (
                "Equity REIT primary earnings metric is FFO/AFFO (non-GAAP). "
                "Never use net income alone. NAV/cap-rate not fully implemented."
            ),
        },
        "enterprise_value": None,
        "equity_value": None,
        "fair_value_per_share": None,
        "fair_value_range": None,
        "implied_upside_vs_price": None,
        "confidence": "low",
        "errors": [],
        "warnings": [],
        "projections": [],
    }
    if ffo is None:
        result["errors"].append(
            "FFO not available (non-GAAP; derive from NI + RE D&A − gains when tags "
            "resolve, or pull from earnings supplement). Do not fall back to FCF DCF "
            "or net-income P/E as primary for equity REIT."
        )
        result["confidence"] = "none"
        return result
    # Report FFO yield / P/FFO only — no invented DCF multiple
    if mcap and ffo and ffo > 0:
        result["inputs"]["p_ffo"] = float(mcap) / float(ffo)
        result["inputs"]["ffo_yield"] = float(ffo) / float(mcap)
        result["warnings"].append(
            f"P/FFO = {result['inputs']['p_ffo']:.1f}x and FFO yield = "
            f"{result['inputs']['ffo_yield']:.1%} at live market cap — "
            "no single fair-value DCF produced (NAV path not implemented)."
        )
    if shares and ffo and float(shares) > 0:
        result["inputs"]["ffo_per_share"] = float(ffo) / float(shares)
    result["confidence"] = "low_to_moderate"
    return result


def compute_dcf_from_state(state: dict) -> dict[str, Any]:
    """Archetype-aware valuation dispatch.

    Banks/insurance/REITs/pre-profit must NOT silently fall back to FCF DCF.
    """
    from .archetype import valuation_method_for_archetype

    cm = state.get("canonical_metrics") or {}
    archetype = "general"
    if isinstance(cm, dict) and cm.get("archetype"):
        archetype = str(cm["archetype"])
    else:
        try:
            from .archetype import classify_archetype

            clf = classify_archetype(
                ticker=state.get("ticker"),
                sector=state.get("sector"),
                income_statement=state.get("income_statement"),
                balance_sheet=state.get("balance_sheet"),
                cash_flow_statement=state.get("cash_flow_statement"),
                sic=state.get("sic"),
            )
            archetype = clf["archetype"]
        except Exception:
            archetype = "general"

    method = valuation_method_for_archetype(archetype)
    ticker = state.get("ticker") or ""
    sector = state.get("sector") or ""

    # Honest non-FCF methods: never silently fall back to industrial FCF DCF.
    if method == "excess_return_on_equity":
        return _excess_return_on_equity(state, archetype=archetype)
    if method == "ffo_nav":
        return _ffo_or_nav_valuation(state, archetype=archetype)
    if method == "book_value_spread":
        return {
            "method": method,
            "archetype": archetype,
            "ticker": (ticker or "").upper() or None,
            "sector": sector,
            "enterprise_value": None,
            "equity_value": None,
            "fair_value_per_share": None,
            "fair_value_range": None,
            "implied_upside_vs_price": None,
            "confidence": "low",
            "errors": [],
            "warnings": [
                "mortgage_reit: use book value / net interest spread analysis — "
                "not a multi-stage FCF DCF. Point estimate not produced."
            ],
            "inputs": _book_inputs(state),
            "assumptions": {"archetype": archetype, "method": method},
            "projections": [],
        }
    if method == "path_to_profitability":
        return {
            "method": method,
            "archetype": archetype,
            "ticker": (ticker or "").upper() or None,
            "sector": sector,
            "enterprise_value": None,
            "equity_value": None,
            "fair_value_per_share": None,
            "fair_value_range": None,
            "implied_upside_vs_price": None,
            "confidence": "none",
            "errors": [
                f"No single-point valuation for archetype {archetype!r} "
                f"(method={method}). Use scenario path-to-profitability; "
                f"do not fall back to FCF DCF or P/E."
            ],
            "warnings": [],
            "inputs": {},
            "assumptions": {"archetype": archetype, "method": method},
            "projections": [],
        }

    # Cycle-normalized FCF: use standard DCF but flag that base should be mid-cycle.
    dcf = compute_dcf(
        cash_flow=state.get("cash_flow_statement") or {},
        income=state.get("income_statement") or {},
        balance=state.get("balance_sheet") or {},
        live_market=_live_market_from_state(state),
        sector=sector,
        ticker=ticker,
    )
    dcf["archetype"] = archetype
    dcf["method_requested"] = method
    if method == "cycle_normalized_fcf_dcf":
        dcf.setdefault("warnings", []).append(
            "Archetype cyclical_commodity: FCF base is trailing, not mid-cycle "
            "normalized — treat point estimate with low confidence until cycle "
            "normalization is implemented."
        )
        dcf["confidence"] = "low"
        dcf["method"] = "cycle_normalized_fcf_dcf_placeholder_trailing_base"

    # Prefer canonical metrics net-debt (ex-ST) when applicable.
    by_id = cm.get("by_id") if isinstance(cm, dict) else None
    if isinstance(by_id, dict) and archetype not in ("bank_lender", "insurance"):
        for mid in (
            "net_debt_ex_st_investments__current_annual",
            "net_debt_ex_st_investments__current_quarter",
        ):
            m = by_id.get(mid)
            if isinstance(m, dict) and m.get("applicable") and m.get("value") is not None:
                try:
                    nd = float(m["value"])
                except (TypeError, ValueError):
                    continue
                dcf.setdefault("inputs", {})["net_debt"] = nd
                dcf.setdefault("inputs", {})["net_debt_source"] = mid
                ev = dcf.get("enterprise_value")
                shares = (dcf.get("inputs") or {}).get("shares_outstanding")
                price = (dcf.get("inputs") or {}).get("price")
                if ev is not None:
                    equity = float(ev) - nd
                    dcf["equity_value"] = equity
                    if shares and float(shares) > 0:
                        fv = equity / float(shares)
                        dcf["fair_value_per_share"] = fv
                        dcf["fair_value_range"] = {
                            "low": fv * 0.85,
                            "base": fv,
                            "high": fv * 1.15,
                            "basis": (
                                "±15% band on base DCF (assumption uncertainty, "
                                "not a rebuilt bull/bear scenario) — not a stress test"
                            ),
                        }
                        if price and float(price) > 0:
                            dcf["implied_upside_vs_price"] = (fv / float(price)) - 1.0
                dcf.setdefault("warnings", []).append(
                    f"Net debt taken from canonical metric {mid}: {m.get('headline')}"
                )
                break
    return dcf


def _argued_corner(
    argued: dict, parameter: str, corner: int, default: Any
) -> Any:
    entry = argued.get(parameter)
    if isinstance(entry, dict):
        values = entry.get("argued_range")
        if isinstance(values, (list, tuple)) and len(values) == 2:
            return values[corner]
    return default


def _argued_midpoint(argued: dict, parameter: str, default: Any) -> Any:
    """Midpoint of an argued range — the coherent central view.

    The two corners are the *compounded* extremes: every parameter at its
    pessimistic end simultaneously, then every parameter at its optimistic end.
    Because discount-rate and growth effects multiply, that spread is far wider
    than the analysis supports. Observed live 2026-07-29: NVDA's default case
    was $318.63 and the low corner $88.24, a 72% haircut produced by stacking
    five individually-defensible choices at once. That is a tail scenario, not
    a base case, and presenting it as the argued value overstates conviction.

    The midpoint of each argued range, taken together, is the central estimate
    an analyst would actually defend.
    """
    entry = argued.get(parameter)
    if isinstance(entry, dict):
        values = entry.get("argued_range")
        if isinstance(values, (list, tuple)) and len(values) == 2:
            try:
                lo, hi = float(values[0]), float(values[1])
            except (TypeError, ValueError):
                return default
            mid = (lo + hi) / 2.0
            if parameter in {"high_growth_years", "fade_years"}:
                return int(round(mid))
            return mid
    return default


def _normalized_base_fcf(
    state: dict, method: str
) -> tuple[Optional[float], str, list[str]]:
    warnings: list[str] = []
    ttm = extract_fcf_series(state.get("cash_flow_statement") or {}).get(
        "current_annual"
    )
    if method == "ttm":
        return ttm, "ttm", warnings

    history = fcf_history(state)
    required = 3 if method in {"avg_3y", "mid_cycle"} else 5
    if method in {"avg_3y", "avg_5y"}:
        rows = [row for row in history if row["rank"] < required]
        expected_ranks = set(range(required))
        found_ranks = {row["rank"] for row in rows}
        if found_ranks != expected_ranks:
            warnings.append(
                f"{method} requested, {len(found_ranks)} annual periods available "
                "— fell back to ttm"
            )
            return ttm, "ttm", warnings
        return (
            sum(float(row["fcf"]) for row in rows) / required,
            method,
            warnings,
        )

    # mid_cycle uses every available annual observation (maximum five),
    # retains negative FCF, and normalizes margin back onto current revenue.
    if method == "mid_cycle":
        if len(history) < required:
            warnings.append(
                f"mid_cycle requested, {len(history)} annual periods available "
                "— fell back to ttm"
            )
            return ttm, "ttm", warnings
        current = next((row for row in history if row["rank"] == 0), None)
        missing_revenue = [
            row["rank"] for row in history if row.get("revenue") is None
        ]
        if (
            current is None
            or current.get("revenue") is None
            or float(current["revenue"]) == 0
            or missing_revenue
            or any(float(row["revenue"]) == 0 for row in history)
        ):
            warnings.append(
                "mid_cycle requested but annual revenue is missing or zero "
                f"for ranks {missing_revenue}; fell back to ttm"
            )
            return ttm, "ttm", warnings
        margins = [
            float(row["fcf"]) / float(row["revenue"]) for row in history
        ]
        return (
            float(median(margins)) * float(current["revenue"]),
            method,
            warnings,
        )

    warnings.append(f"unknown base_fcf_method {method!r}; fell back to ttm")
    return ttm, "ttm", warnings


def _recompute_dcf_case(
    base: dict[str, Any],
    *,
    base_fcf: Optional[float],
    base_fcf_method: str,
    wacc: float,
    g_high: float,
    g_terminal: float,
    high_growth_years: int,
    fade_years: int,
) -> dict[str, Any]:
    result = deepcopy(base)
    result["input_source"] = "argued"
    result["errors"] = []
    result["warnings"] = list(base.get("warnings") or [])
    result.setdefault("inputs", {})["base_fcf_annual"] = base_fcf
    result["inputs"]["base_fcf_method"] = base_fcf_method
    result["assumptions"] = {
        **(base.get("assumptions") or {}),
        "wacc": float(wacc),
        "g_high": float(g_high),
        "g_terminal": float(g_terminal),
        "high_growth_years": int(high_growth_years),
        "fade_years": int(fade_years),
        "input_source": "argued",
    }
    result["projections"] = []
    result["enterprise_value"] = None
    result["equity_value"] = None
    result["fair_value_per_share"] = None
    result["fair_value_range"] = None
    result["implied_upside_vs_price"] = None
    result["epv_per_share"] = None

    if base_fcf is None or base_fcf <= 0:
        result["errors"].append(
            "Cannot run argued FCF DCF: normalized base FCF missing or non-positive."
        )
        result["confidence"] = "none"
        return result
    if g_terminal > wacc - 0.015:
        result["errors"].append(
            "Invalid argued inputs: g_terminal must be <= wacc - 0.015."
        )
        result["confidence"] = "none"
        return result

    projections: list[dict[str, Any]] = []
    fcf_t = float(base_fcf)
    total_pv = 0.0
    year = 0
    for year in range(1, int(high_growth_years) + 1):
        fcf_t *= 1.0 + float(g_high)
        pv = fcf_t / ((1.0 + float(wacc)) ** year)
        total_pv += pv
        projections.append(
            {
                "year": year,
                "stage": "high_growth",
                "growth": float(g_high),
                "fcf": fcf_t,
                "pv": pv,
            }
        )
    for offset in range(1, int(fade_years) + 1):
        year = int(high_growth_years) + offset
        weight = offset / float(fade_years)
        growth = float(g_high) + (
            float(g_terminal) - float(g_high)
        ) * weight
        fcf_t *= 1.0 + growth
        pv = fcf_t / ((1.0 + float(wacc)) ** year)
        total_pv += pv
        projections.append(
            {
                "year": year,
                "stage": "fade",
                "growth": growth,
                "fcf": fcf_t,
                "pv": pv,
            }
        )
    terminal_value = (
        fcf_t * (1.0 + float(g_terminal))
    ) / (float(wacc) - float(g_terminal))
    terminal_value_pv = terminal_value / ((1.0 + float(wacc)) ** year)
    enterprise_value = total_pv + terminal_value_pv
    net_debt = result["inputs"].get("net_debt")
    equity_value = (
        enterprise_value - float(net_debt)
        if isinstance(net_debt, (int, float))
        else enterprise_value
    )
    shares = result["inputs"].get("shares_outstanding")
    price = result["inputs"].get("price")

    result["projections"] = projections
    result["terminal_value"] = terminal_value
    result["terminal_value_pv"] = terminal_value_pv
    result["enterprise_value"] = enterprise_value
    result["equity_value"] = equity_value
    if isinstance(shares, (int, float)) and shares > 0:
        fair_value = equity_value / float(shares)
        result["fair_value_per_share"] = fair_value
        result["fair_value_range"] = {
            "low": fair_value,
            "base": fair_value,
            "high": fair_value,
            "basis": "single argued-input corner; judgment wrapper carries the range",
        }
        if isinstance(price, (int, float)) and price > 0:
            result["implied_upside_vs_price"] = fair_value / float(price) - 1.0
        epv_equity = float(base_fcf) / float(wacc)
        if isinstance(net_debt, (int, float)):
            epv_equity -= float(net_debt)
        result["epv_per_share"] = epv_equity / float(shares)
    return result


def compute_dcf_with_argued_inputs(state: dict, argued: dict) -> dict[str, Any]:
    """Re-run the deterministic DCF at both accepted argued-range corners."""
    base = compute_dcf_from_state(state)
    if base.get("method") not in {
        "multi_stage_fcf_dcf",
        "cycle_normalized_fcf_dcf_placeholder_trailing_base",
    }:
        result = deepcopy(base)
        result["input_source"] = "argued"
        result["clamp_warnings"] = [
            "Argued FCF inputs not applied: the archetype does not use an FCF DCF."
        ]
        result["band_dissents"] = list(argued.get("band_dissents") or [])
        return result

    assumptions = base.get("assumptions") or {}
    method_entry = argued.get("base_fcf_method")
    method = (
        method_entry.get("value")
        if isinstance(method_entry, dict)
        else method_entry
    ) or "ttm"
    normalized_fcf, applied_method, normalization_warnings = _normalized_base_fcf(
        state, str(method)
    )

    # ── Neutral reference ────────────────────────────────────────────────────
    # Every argued case below is recomputed on the *argued* base FCF. Measuring
    # those against `base["fair_value_per_share"]` — which used the engine's own
    # base FCF — compares two different worlds, so a parameter left at its
    # default reports a non-zero delta.
    #
    # Observed live 2026-07-30 on KO (argued base_fcf_method=avg_5y): g_terminal,
    # high_growth_years and fade_years were all argued *at* the engine default
    # and each reported +$17.31. The memo then named WACC the dominant lever
    # when g_high was nearly 50% larger and pointed the other way.
    #
    # `neutral_case` holds every parameter at the engine default and changes
    # only the base FCF, isolating the base-FCF swap from the parameter moves.
    _engine_kwargs = {
        "wacc": float(assumptions.get("wacc") or 0.0),
        "g_high": float(assumptions.get("g_high") or 0.0),
        "g_terminal": float(assumptions.get("g_terminal") or 0.0),
        "high_growth_years": int(assumptions.get("high_growth_years") or 0),
        "fade_years": int(assumptions.get("fade_years") or 0),
    }
    neutral_case = _recompute_dcf_case(
        base,
        base_fcf=normalized_fcf,
        base_fcf_method=applied_method,
        **_engine_kwargs,
    )
    neutral_fv = neutral_case.get("fair_value_per_share")
    engine_fv = base.get("fair_value_per_share")

    # ── Sign-aware corner selection ──────────────────────────────────────────
    # A range end is not inherently pessimistic: a *lower* WACC raises value
    # while a *lower* g_high lowers it, so taking index [0] of every range
    # builds a corner in which the two partly cancel. Observed live on KO — the
    # case labelled `low_case` returned the HIGHER value ($33.94 vs $28.39), and
    # the published band was 3.1x narrower than a genuine compounded extreme
    # ($5.55 wide against $17.10) while being disclosed as "wider than the
    # analysis supports".
    #
    # Direction is resolved empirically rather than from a static sign table:
    # `high_growth_years` and `fade_years` only raise value while
    # g_high > g_terminal, which is not guaranteed. Probe each parameter's two
    # range ends with everything else at default and let the lower fair value
    # define the pessimistic end.
    def _corner_ends(parameter: str) -> tuple[Any, Any]:
        """Return (pessimistic_end, optimistic_end) for one argued parameter."""
        lo = _argued_corner(argued, parameter, 0, _engine_kwargs[parameter])
        hi = _argued_corner(argued, parameter, 1, _engine_kwargs[parameter])
        cast = (
            (lambda v: int(v))
            if parameter in {"high_growth_years", "fade_years"}
            else (lambda v: float(v))
        )
        lo, hi = cast(lo), cast(hi)
        if lo == hi:
            return lo, hi
        probes = {}
        for end in (lo, hi):
            kwargs = dict(_engine_kwargs)
            kwargs[parameter] = end
            if parameter == "g_terminal":
                kwargs["g_terminal"] = max(
                    0.0, min(kwargs["g_terminal"], kwargs["wacc"] - 0.015)
                )
            probe = _recompute_dcf_case(
                base,
                base_fcf=normalized_fcf,
                base_fcf_method=applied_method,
                **kwargs,
            )
            probes[end] = probe.get("fair_value_per_share")
        f_lo, f_hi = probes.get(lo), probes.get(hi)
        if not isinstance(f_lo, (int, float)) or not isinstance(f_hi, (int, float)):
            return lo, hi  # cannot resolve direction — preserve prior behaviour
        return (lo, hi) if f_lo <= f_hi else (hi, lo)

    _ends = {p: _corner_ends(p) for p in _engine_kwargs}

    cases = []
    for corner in (0, 1):
        wacc = float(_ends["wacc"][corner])
        g_terminal = float(_ends["g_terminal"][corner])
        # Defense in depth: callers may bypass validate_argued_inputs. This must
        # run AFTER sign-aware selection — the optimistic corner pairs low WACC
        # with high terminal growth, which is exactly the combination that trips
        # the Gordon constraint. Without the clamp the case returns FV=None,
        # drops out of `values`, and the band silently collapses.
        g_terminal = max(0.0, min(g_terminal, wacc - 0.015))
        cases.append(
            _recompute_dcf_case(
                base,
                base_fcf=normalized_fcf,
                base_fcf_method=applied_method,
                wacc=wacc,
                g_high=float(_ends["g_high"][corner]),
                g_terminal=g_terminal,
                high_growth_years=int(_ends["high_growth_years"][corner]),
                fade_years=int(_ends["fade_years"][corner]),
            )
        )

    low_case, high_case = cases

    # Central case: every argued parameter at the midpoint of its range. This is
    # the coherent view and the one that anchors the deliverable. The corners
    # remain available but are explicitly labelled compounded extremes — see
    # _argued_midpoint() for why they must not be presented as the argued value.
    _argued_params = [p for p in argued if p not in {"band_dissents", "base_fcf_method"}]
    central_case = _recompute_dcf_case(
        base,
        base_fcf=normalized_fcf,
        base_fcf_method=applied_method,
        wacc=float(_argued_midpoint(argued, "wacc", assumptions.get("wacc"))),
        g_high=float(_argued_midpoint(argued, "g_high", assumptions.get("g_high"))),
        g_terminal=float(
            _argued_midpoint(argued, "g_terminal", assumptions.get("g_terminal"))
        ),
        high_growth_years=int(
            _argued_midpoint(
                argued, "high_growth_years", assumptions.get("high_growth_years")
            )
        ),
        fade_years=int(
            _argued_midpoint(argued, "fade_years", assumptions.get("fade_years"))
        ),
    )

    # One-at-a-time sensitivity: move a single parameter to its argued midpoint
    # and hold everything else at the engine default. This answers the question
    # a compounded range cannot — which assumption actually drives the value.
    # Deltas are measured against `neutral_fv` — same base FCF, every parameter
    # at the engine default — so each row isolates its own parameter. A
    # parameter argued at the engine default must produce exactly 0.0.
    default_fv = neutral_fv
    sensitivities = []
    for parameter in _argued_params:
        kwargs = dict(_engine_kwargs)
        if parameter not in kwargs:
            continue
        moved = _argued_midpoint(argued, parameter, kwargs[parameter])
        kwargs[parameter] = (
            int(moved) if parameter in {"high_growth_years", "fade_years"} else float(moved)
        )
        case = _recompute_dcf_case(
            base,
            base_fcf=normalized_fcf,
            base_fcf_method=applied_method,
            **kwargs,
        )
        fv = case.get("fair_value_per_share")
        sensitivities.append(
            {
                "parameter": parameter,
                "engine_default": assumptions.get(parameter),
                "argued_midpoint": kwargs[parameter],
                "fair_value_per_share": fv,
                "delta_vs_default": (
                    fv - default_fv
                    if isinstance(fv, (int, float))
                    and isinstance(default_fv, (int, float))
                    else None
                ),
            }
        )
    # `base_fcf_method` is excluded from `_argued_params` because it is not a
    # DCF dial, but it is still an argued choice and on KO it was the single
    # largest lever in the whole valuation (+$17.31, larger than either real
    # parameter). Leaving it out of the table hid it from the writer entirely
    # while its effect was silently smeared across every other row. Report it.
    if (
        applied_method
        and isinstance(neutral_fv, (int, float))
        and isinstance(engine_fv, (int, float))
        and abs(neutral_fv - engine_fv) > 1e-9
    ):
        sensitivities.append(
            {
                "parameter": "base_fcf_method",
                "engine_default": (base.get("inputs") or {}).get("base_fcf_method")
                or "engine_base_fcf",
                "argued_midpoint": applied_method,
                "fair_value_per_share": neutral_fv,
                "delta_vs_default": neutral_fv - engine_fv,
            }
        )

    sensitivities.sort(
        key=lambda s: abs(s["delta_vs_default"]) if s["delta_vs_default"] else 0.0,
        reverse=True,
    )

    # Directional bias: are all material arguments pushing the same way?
    #
    # Observed live 2026-07-30 on NVDA — growth −$145, discount rate −$77,
    # high-growth years −$63, every one against the stock. That produces a
    # valuation far below the default without any single defensible reason for
    # it. A real view is usually one or two strong departures with the rest
    # left at default; five simultaneous conservative nudges is a thumb on the
    # scale. The sensitivity deltas already measure this, so surface it rather
    # than leaving a reader to notice.
    _material = [
        s
        for s in sensitivities
        if isinstance(s.get("delta_vs_default"), (int, float))
        and isinstance(default_fv, (int, float))
        and default_fv
        and abs(s["delta_vs_default"]) >= abs(default_fv) * 0.02
    ]
    # Unanimity is the wrong test. NVDA's live set was three arguments down
    # (−$145, −$77, −$63) and one up (+$37): not unanimous, but 88% of the
    # total movement pointed one way. Measure net imbalance instead — the share
    # of total absolute movement running in the dominant direction.
    _down = sum(-s["delta_vs_default"] for s in _material if s["delta_vs_default"] < 0)
    _up = sum(s["delta_vs_default"] for s in _material if s["delta_vs_default"] > 0)
    _total = _down + _up
    _share = (max(_down, _up) / _total) if _total else 0.0
    directional_bias: dict[str, Any] = {
        "material_arguments": len(_material),
        "dominant_direction": (
            ("below default" if _down >= _up else "above default") if _total else None
        ),
        "dominant_share": round(_share, 3),
        "one_sided": False,
    }
    if len(_material) >= 3 and _share >= 0.80:
        directional_bias["one_sided"] = True
        normalization_warnings.append(
            f"DIRECTIONAL BIAS: {_share:.0%} of the argued movement across "
            f"{len(_material)} material arguments pushes fair value "
            f"{directional_bias['dominant_direction']}. A view is normally one "
            "or two departures with the rest left at default; a one-sided set "
            "warrants a single stated reason or it is a thumb on the scale."
        )

    values = [
        case.get("fair_value_per_share")
        for case in cases
        if isinstance(case.get("fair_value_per_share"), (int, float))
    ]
    central_fv = central_case.get("fair_value_per_share")
    result = deepcopy(base)
    result.update(
        {
            "input_source": "argued",
            "base_engine": base,
            # Same base FCF as the argued cases, every parameter at the engine
            # default. This is the reference `delta_vs_default` is measured
            # from; `base_engine` is the engine's own answer on its own base FCF.
            "neutral_case": neutral_case,
            "central_case": central_case,
            "sensitivities": sensitivities,
            "directional_bias": directional_bias,
            "low_case": low_case,
            "high_case": high_case,
            "fair_value_per_share": None,
            "fair_value_range": (
                {
                    "low": min(values),
                    # The central (all-midpoints) case, NOT the average of the
                    # two compounded corners. `fair_value_per_share` stays None
                    # on purpose — the argued case is a range — but consumers
                    # need one defensible scalar to anchor on.
                    "base": (
                        central_fv
                        if isinstance(central_fv, (int, float))
                        else sum(values) / len(values)
                    ),
                    "high": max(values),
                    "basis": (
                        "base = central case, every argued parameter at its "
                        "range midpoint; low/high = COMPOUNDED extremes — each "
                        "parameter set to whichever end of its argued range "
                        "moves fair value down (low) or up (high), all at once. "
                        "The spread is wider than any single coherent view and "
                        "is NOT a scenario set; headline the central case."
                    ),
                }
                if values
                else None
            ),
            "clamp_warnings": normalization_warnings,
            "band_dissents": list(argued.get("band_dissents") or []),
            "assumptions": {
                "low": low_case.get("assumptions"),
                "high": high_case.get("assumptions"),
                "base_fcf_method_requested": method,
                "base_fcf_method_applied": applied_method,
            },
            "errors": list(
                dict.fromkeys(
                    [
                        *(low_case.get("errors") or []),
                        *(high_case.get("errors") or []),
                    ]
                )
            ),
        }
    )
    return result


# ── Peer multiples (yfinance) ────────────────────────────────────────────────

def _yf_info(ticker: str) -> dict[str, Any]:
    try:
        import yfinance as yf

        t = yf.Ticker(ticker.strip().upper())
        info = t.info or {}
        return info if isinstance(info, dict) else {}
    except Exception as exc:
        return {"error": str(exc)}


def _row_from_info(ticker: str, info: dict[str, Any]) -> dict[str, Any]:
    if info.get("error") and len(info) == 1:
        return {"ticker": ticker, "error": info["error"]}

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    return {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName"),
        "price": price,
        "market_cap": info.get("marketCap"),
        "enterprise_value": info.get("enterpriseValue"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio"),
        "price_to_sales": info.get("priceToSalesTrailing12Months"),
        "price_to_book": info.get("priceToBook"),
        "ev_to_ebitda": info.get("enterpriseToEbitda"),
        "ev_to_revenue": info.get("enterpriseToRevenue"),
        "profit_margins": info.get("profitMargins"),
        "operating_margins": info.get("operatingMargins"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "error": info.get("error"),
    }


def _mcap_band_filter(
    subject_mcap: Optional[float],
    candidates: list[str],
    *,
    lo: float = 0.1,
    hi: float = 10.0,
) -> tuple[list[str], list[dict[str, str]]]:
    """Drop peers whose market cap is outside ~0.1×–10× of subject."""
    if not subject_mcap or subject_mcap <= 0:
        return candidates, []
    kept: list[str] = []
    excl: list[dict[str, str]] = []
    for p in candidates:
        info = _yf_info(p)
        m = info.get("marketCap")
        try:
            mf = float(m) if m is not None else None
        except (TypeError, ValueError):
            mf = None
        if mf is None or mf <= 0:
            kept.append(p)  # keep if unknown — don't over-filter
            continue
        ratio = mf / float(subject_mcap)
        if ratio < lo or ratio > hi:
            excl.append(
                {
                    "ticker": p,
                    "peer_archetype": "",
                    "reason": (
                        f"market-cap ratio {ratio:.2f}x outside [{lo}×, {hi}×] band"
                    ),
                }
            )
        else:
            kept.append(p)
    return kept, excl


def _apply_canonical_subject_overrides(
    subject_row: dict[str, Any],
    canonical_metrics: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Prefer Python canonical metrics for subject standalone multiples.

    yfinance trailing P/E / P/S often disagree with SEC-derived canonical
    figures; agents must not treat Yahoo subject multiples as source of truth.
    """
    if not canonical_metrics or not isinstance(subject_row, dict):
        return subject_row
    try:
        from .metrics import get_metric
    except Exception:
        return subject_row

    overrides: list[str] = []
    mapping = (
        ("trailing_pe", "trailing_pe"),
        ("price_to_sales", "price_to_sales"),
        ("price_to_book", "price_to_book"),
        ("market_cap", "market_cap"),
        ("price", "price"),
    )
    for row_key, mid in mapping:
        m = get_metric(canonical_metrics, mid)
        if not m or not m.get("applicable") or m.get("value") is None:
            continue
        # Skip stale-flagged lines for load-bearing subject overrides.
        if m.get("staleness"):
            continue
        try:
            subject_row[row_key] = float(m["value"])
            overrides.append(mid)
        except (TypeError, ValueError):
            continue
    if overrides:
        subject_row["canonical_overrides"] = overrides
        subject_row["multiples_source"] = "canonical_metrics_preferred"
    return subject_row


def fetch_peer_multiples(
    subject_ticker: str,
    *,
    sector: str = "",
    peer_tickers: Optional[list[str]] = None,
    subject_archetype: Optional[str] = None,
    subject_sic: Optional[str] = None,
    canonical_metrics: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Pull live multiples for subject + peers via yfinance.

    Peer universe priority:
      1. Explicit peer_tickers if provided
      2. Sector peer list when sector maps to a known SECTOR_PEERS key
         (e.g. Semiconductors → AMD/AVGO/TSM… — not mega-cap tech)
      3. Archetype peer list + SIC-proximity candidates
    Then filter by archetype match and market-cap band.
    Subject standalone multiples prefer canonical_metrics when supplied.
    """
    from .archetype import (
        filter_peers_by_archetype,
        peers_for_archetype,
        classify_archetype,
    )

    subject = (subject_ticker or "").strip().upper()
    arch = subject_archetype
    if not arch:
        clf = classify_archetype(ticker=subject, sector=sector, sic=subject_sic)
        arch = clf["archetype"]

    if peer_tickers:
        raw_peers = [p.strip().upper() for p in peer_tickers if p]
        peer_source = "explicit"
    else:
        sk = _sector_key(sector)
        # Prefer sector peers when sector maps (e.g. Semiconductors → AMD/AVGO/…).
        sector_list = (
            default_peers_for_sector(sector, subject=subject)
            if sk != "DEFAULT"
            else []
        )
        arch_list = peers_for_archetype(arch, subject=subject)
        raw_peers = list(sector_list)
        for p in arch_list:
            if p not in raw_peers:
                raw_peers.append(p)
        peer_source = (
            f"sector:{sk}+archetype:{arch}" if sector_list else f"archetype:{arch}"
        )
        # SIC proximity: candidates with same 4-digit or 3-digit SIC from
        # submissions cache + archetype peer pool (lazy — no full SEC crawl).
        if subject_sic:
            try:
                from .tools import peers_by_sic_proximity

                sic_peers = peers_by_sic_proximity(
                    subject_sic, subject=subject, limit=12
                )
                for p in sic_peers:
                    if p not in raw_peers:
                        raw_peers.append(p)
            except Exception:
                pass
        if not raw_peers:
            raw_peers = sector_list or arch_list
            peer_source = "fallback_sector_or_archetype"

    # For hard financial archetypes keep strict filter; for general/semi allow
    # sector peers through even if archetype map labels them "general".
    if arch in ("bank_lender", "insurance", "equity_reit", "mortgage_reit", "reit_real_estate"):
        peers, exclusions = filter_peers_by_archetype(
            raw_peers, arch, subject=subject
        )
    else:
        # Soft filter: drop only hard-mismatched archetypes (banks etc.), keep
        # other general/tech/semi names from the sector list.
        peers = []
        exclusions = []
        hard = {
            "bank_lender",
            "insurance",
            "equity_reit",
            "mortgage_reit",
            "reit_real_estate",
        }
        from .archetype import classify_archetype as _clf

        for p in raw_peers:
            if p == subject:
                continue
            pa = (_clf(ticker=p).get("archetype") or "general")
            if pa in hard:
                exclusions.append(
                    {
                        "ticker": p,
                        "peer_archetype": pa,
                        "reason": f"hard archetype mismatch ({pa} vs {arch})",
                    }
                )
            else:
                peers.append(p)

    subject_row = _row_from_info(subject, _yf_info(subject)) if subject else {}
    yf_trailing = subject_row.get("trailing_pe")
    subject_row = _apply_canonical_subject_overrides(subject_row, canonical_metrics)
    # Market-cap band — prefer canonical mcap when present.
    # Keep sector-default peers even when the subject is a mega-cap (NVDA-scale
    # 0.1×–10× band would otherwise drop most true semi comps).
    mcap = subject_row.get("market_cap")
    sk = _sector_key(sector)
    sector_core = set(
        default_peers_for_sector(sector, subject=subject) if sk != "DEFAULT" else []
    )
    if sector_core:
        core = [p for p in peers if p in sector_core]
        extra = [p for p in peers if p not in sector_core]
        extra, mcap_excl = _mcap_band_filter(
            mcap if isinstance(mcap, (int, float)) else None, extra
        )
        peers = core + extra
    else:
        peers, mcap_excl = _mcap_band_filter(
            mcap if isinstance(mcap, (int, float)) else None, peers
        )
    exclusions = list(exclusions) + list(mcap_excl)

    # If filtering wiped the list, re-seed from sector then archetype.
    if len(peers) < 2:
        peers = default_peers_for_sector(sector, subject=subject) or peers_for_archetype(
            arch, subject=subject
        )
        exclusions = exclusions + [
            {
                "ticker": "?",
                "peer_archetype": "",
                "reason": "re-seeded after filter left <2 peers",
            }
        ]
    # Cap list length for prompt size (sector core first).
    peers = peers[:8]

    peer_rows = [_row_from_info(p, _yf_info(p)) for p in peers]
    candidate_pool = list(
        dict.fromkeys(
            p
            for p in [*raw_peers, *peers]
            if p and p != subject
        )
    )
    peer_rows_by_ticker = {
        str(row.get("ticker") or "").upper(): row for row in peer_rows
    }
    candidate_rows = [
        peer_rows_by_ticker.get(ticker) or _row_from_info(ticker, _yf_info(ticker))
        for ticker in candidate_pool
    ]

    # Peer medians for key multiples
    def _median(key: str) -> Optional[float]:
        vals = []
        for r in peer_rows:
            v = r.get(key)
            if isinstance(v, (int, float)) and v == v:  # not NaN
                vals.append(float(v))
        if not vals:
            return None
        vals.sort()
        mid = len(vals) // 2
        if len(vals) % 2:
            return vals[mid]
        return (vals[mid - 1] + vals[mid]) / 2.0

    medians = {
        "trailing_pe": _median("trailing_pe"),
        "forward_pe": _median("forward_pe"),
        "ev_to_ebitda": _median("ev_to_ebitda"),
        "price_to_sales": _median("price_to_sales"),
        "ev_to_revenue": _median("ev_to_revenue"),
        "price_to_book": _median("price_to_book"),
    }

    def _vs(subject_key: str, median_key: str) -> Optional[str]:
        s = subject_row.get(subject_key)
        m = medians.get(median_key)
        if not isinstance(s, (int, float)) or not isinstance(m, (int, float)) or m == 0:
            return None
        ratio = float(s) / float(m)
        if ratio < 0.85:
            label = "cheap"
        elif ratio > 1.15:
            label = "rich"
        else:
            label = "fair"
        return f"{label} ({ratio:.2f}x peer median)"

    relative = {
        "trailing_pe_vs_peers": _vs("trailing_pe", "trailing_pe"),
        "forward_pe_vs_peers": _vs("forward_pe", "forward_pe"),
        "ev_ebitda_vs_peers": _vs("ev_to_ebitda", "ev_to_ebitda"),
        "ps_vs_peers": _vs("price_to_sales", "price_to_sales"),
    }

    # Simple overall read: majority vote on available labels
    votes = []
    for v in relative.values():
        if v:
            votes.append(v.split()[0])
    if votes:
        overall = max(set(votes), key=votes.count)
    else:
        overall = "insufficient_data"

    notes: list[str] = []
    if subject_row.get("canonical_overrides"):
        notes.append(
            "Subject trailing multiples overridden from canonical_metrics: "
            + ", ".join(subject_row["canonical_overrides"])
        )
        if (
            isinstance(yf_trailing, (int, float))
            and isinstance(subject_row.get("trailing_pe"), (int, float))
            and abs(float(yf_trailing) - float(subject_row["trailing_pe"])) > 1.0
        ):
            notes.append(
                f"yfinance trailing P/E was {yf_trailing:.1f}x; "
                f"canonical {float(subject_row['trailing_pe']):.1f}x governs for subject."
            )

    return {
        "subject": subject_row,
        "peers": peer_rows,
        "peer_medians": medians,
        "relative_read": relative,
        "overall_vs_peers": overall,
        "peer_list": peers,
        "candidate_pool": candidate_pool,
        "candidate_rows": candidate_rows,
        "subject_archetype": arch,
        "peer_exclusions": exclusions,
        "peer_source": peer_source,
        "notes": notes,
        "relative_valuation_applicable": len(peers) >= 2,
    }


def _median_from_rows(rows: list[dict[str, Any]], key: str) -> Optional[float]:
    values = [
        float(row[key])
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get(key), (int, float))
        and float(row[key]) == float(row[key])
    ]
    if not values:
        return None
    return float(median(values))


def _relative_label(subject_value: Any, peer_median: Any) -> Optional[str]:
    if (
        not isinstance(subject_value, (int, float))
        or not isinstance(peer_median, (int, float))
        or peer_median == 0
    ):
        return None
    ratio = float(subject_value) / float(peer_median)
    label = "cheap" if ratio < 0.85 else "rich" if ratio > 1.15 else "fair"
    return f"{label} ({ratio:.2f}x peer median)"


def apply_peer_changes(comps: dict, changes: list[dict]) -> dict:
    """Apply evidence-vetted include/exclude choices without fetching data."""
    result = deepcopy(comps)
    current_rows = [
        dict(row) for row in result.get("peers") or [] if isinstance(row, dict)
    ]
    current_by_ticker = {
        str(row.get("ticker") or "").upper(): row
        for row in current_rows
        if row.get("ticker")
    }
    candidate_rows = [
        row
        for key in ("candidate_rows", "peer_candidates", "peers")
        for row in (result.get(key) or [])
        if isinstance(row, dict)
    ]
    candidate_by_ticker = {
        str(row.get("ticker") or "").upper(): dict(row)
        for row in candidate_rows
        if row.get("ticker")
    }
    candidate_pool = {
        str(ticker).upper()
        for ticker in [
            *(result.get("candidate_pool") or []),
            *(result.get("peer_list") or []),
            *candidate_by_ticker.keys(),
        ]
        if ticker
    }
    warnings = list(result.get("clamp_warnings") or [])
    applied: list[dict[str, Any]] = []

    for change in changes or []:
        if not isinstance(change, dict):
            warnings.append("peer change ignored: change is not an object")
            continue
        ticker = str(change.get("ticker") or "").strip().upper()
        action = change.get("action")
        if not ticker or action not in {"include", "exclude"}:
            warnings.append(f"peer change ignored: invalid change {change!r}")
            continue
        if action == "exclude":
            if ticker not in current_by_ticker:
                warnings.append(
                    f"peer exclusion ignored: {ticker} is not in the active peer set"
                )
                continue
            current_by_ticker.pop(ticker)
            applied.append(dict(change))
            continue
        if ticker not in candidate_pool or ticker not in candidate_by_ticker:
            warnings.append(
                f"peer inclusion rejected: {ticker} is not an engine candidate "
                "with an existing data row"
            )
            continue
        current_by_ticker[ticker] = dict(candidate_by_ticker[ticker])
        applied.append(dict(change))

    ordered_tickers = [
        str(row.get("ticker") or "").upper()
        for row in current_rows
        if str(row.get("ticker") or "").upper() in current_by_ticker
    ]
    for change in applied:
        ticker = str(change.get("ticker") or "").upper()
        if change.get("action") == "include" and ticker not in ordered_tickers:
            ordered_tickers.append(ticker)
    rows = [current_by_ticker[ticker] for ticker in ordered_tickers]
    median_keys = (
        "trailing_pe",
        "forward_pe",
        "ev_to_ebitda",
        "price_to_sales",
        "ev_to_revenue",
        "price_to_book",
    )
    medians = {key: _median_from_rows(rows, key) for key in median_keys}
    subject = result.get("subject") or {}
    relative = {
        "trailing_pe_vs_peers": _relative_label(
            subject.get("trailing_pe"), medians["trailing_pe"]
        ),
        "forward_pe_vs_peers": _relative_label(
            subject.get("forward_pe"), medians["forward_pe"]
        ),
        "ev_ebitda_vs_peers": _relative_label(
            subject.get("ev_to_ebitda"), medians["ev_to_ebitda"]
        ),
        "ps_vs_peers": _relative_label(
            subject.get("price_to_sales"), medians["price_to_sales"]
        ),
    }
    votes = [
        label.split()[0] for label in relative.values() if isinstance(label, str)
    ]
    result.update(
        {
            "peers": rows,
            "peer_list": ordered_tickers,
            "peer_medians": medians,
            "relative_read": relative,
            "overall_vs_peers": (
                max(set(votes), key=votes.count) if votes else "insufficient_data"
            ),
            "relative_valuation_applicable": len(rows) >= 2,
            "peer_changes_applied": applied,
            "clamp_warnings": warnings,
        }
    )
    return result


def implied_value_from_multiple(
    *,
    metric: str,
    multiple: float,
    comps: dict,
    state: dict,
) -> dict:
    """Compute per-share value from a clamped multiple and engine-derived base."""
    if metric not in _MULTIPLE_ABSOLUTE_BOUNDS:
        return {
            "metric": metric,
            "multiple": multiple,
            "implied_value_per_share": None,
            "forward_estimate_available": False,
            "errors": [f"unsupported justified-multiple metric {metric!r}"],
        }
    try:
        multiple_f = float(multiple)
    except (TypeError, ValueError):
        return {
            "metric": metric,
            "multiple": multiple,
            "implied_value_per_share": None,
            "forward_estimate_available": False,
            "errors": ["multiple must be numeric"],
        }

    subject = comps.get("subject") or {}
    price = subject.get("price")
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        price_f = 0.0
    result: dict[str, Any] = {
        "metric": metric,
        "multiple": multiple_f,
        "implied_value_per_share": None,
        "forward_estimate_available": False,
        "estimate_basis": None,
        "estimate_per_share": None,
        "errors": [],
    }
    if price_f <= 0:
        result["errors"].append("subject price unavailable")
        return result

    if metric in {"forward_pe", "trailing_pe"}:
        forward_pe = subject.get("forward_pe")
        if metric == "forward_pe" and isinstance(forward_pe, (int, float)) and forward_pe > 0:
            estimate = price_f / float(forward_pe)
            result["forward_estimate_available"] = True
            result["estimate_basis"] = "consensus_forward_eps_from_price_over_forward_pe"
        else:
            trailing_pe = subject.get("trailing_pe")
            if isinstance(trailing_pe, (int, float)) and trailing_pe > 0:
                estimate = price_f / float(trailing_pe)
            else:
                estimate = extract_income_basics(
                    state.get("income_statement") or {}
                ).get("eps_diluted_current")
            if estimate is None or float(estimate) <= 0:
                result["errors"].append("trailing EPS fallback unavailable")
                return result
            result["estimate_basis"] = "trailing_eps_fallback"
        result["estimate_per_share"] = float(estimate)
        result["implied_value_per_share"] = float(estimate) * multiple_f
        return result

    market_cap = subject.get("market_cap")
    enterprise_value = subject.get("enterprise_value")
    try:
        shares = float(market_cap) / price_f if float(market_cap) > 0 else None
    except (TypeError, ValueError):
        shares = None

    if metric == "ev_ebitda":
        current_multiple = subject.get("ev_to_ebitda")
        if (
            not isinstance(enterprise_value, (int, float))
            or not isinstance(current_multiple, (int, float))
            or current_multiple <= 0
            or not shares
        ):
            result["errors"].append(
                "enterprise value, EV/EBITDA, or share count unavailable"
            )
            return result
        ebitda = float(enterprise_value) / float(current_multiple)
        net_debt = float(enterprise_value) - float(market_cap)
        implied_equity = ebitda * multiple_f - net_debt
        result["estimate_basis"] = "engine_derived_ebitda_per_share"
        result["estimate_per_share"] = ebitda / shares
        result["implied_value_per_share"] = implied_equity / shares
        return result

    current_ps = subject.get("price_to_sales")
    if isinstance(current_ps, (int, float)) and current_ps > 0:
        revenue_per_share = price_f / float(current_ps)
    else:
        revenue = extract_income_basics(
            state.get("income_statement") or {}
        ).get("revenue_current")
        if revenue is None or not shares:
            result["errors"].append("revenue-per-share basis unavailable")
            return result
        revenue_per_share = float(revenue) / shares
    result["estimate_basis"] = "trailing_revenue_per_share"
    result["estimate_per_share"] = revenue_per_share
    result["implied_value_per_share"] = revenue_per_share * multiple_f
    return result


def format_comps_for_prompt(comps: dict[str, Any]) -> str:
    lines = [
        "=== DETERMINISTIC PEER COMPS (peer multiples from yfinance; "
        "subject standalone multiples prefer canonical_metrics when present) ===",
        f"Subject archetype: {comps.get('subject_archetype')}",
        f"Peer source: {comps.get('peer_source') or 'n/a'}",
        f"Peers used: {', '.join(comps.get('peer_list') or [])}",
        f"Overall vs peers: {comps.get('overall_vs_peers')}",
        f"Relative valuation applicable: {comps.get('relative_valuation_applicable')}",
    ]
    for note in comps.get("notes") or []:
        lines.append(f"NOTE: {note}")
    excl = comps.get("peer_exclusions") or []
    if excl:
        lines.append("Excluded peers (mismatch or re-seed notes):")
        for e in excl[:8]:
            if isinstance(e, dict):
                lines.append(
                    f"  - {e.get('ticker')}: {e.get('reason')} "
                    f"(peer_archetype={e.get('peer_archetype')})"
                )
    sub = comps.get("subject") or {}
    src = sub.get("multiples_source") or "yfinance"
    lines.append(
        f"Subject {sub.get('ticker')} (source={src}): price={_fmt_price(sub.get('price'))} "
        f"mcap={_fmt_money(sub.get('market_cap'))} "
        f"P/E t={_fmt_num(sub.get('trailing_pe'), 1)} f={_fmt_num(sub.get('forward_pe'), 1)} "
        f"EV/EBITDA={_fmt_num(sub.get('ev_to_ebitda'), 1)} "
        f"P/S={_fmt_num(sub.get('price_to_sales'), 2)} "
        f"P/B={_fmt_num(sub.get('price_to_book'), 2)}"
    )
    med = comps.get("peer_medians") or {}
    lines.append(
        f"Peer medians: P/E t={_fmt_num(med.get('trailing_pe'), 1)} "
        f"f={_fmt_num(med.get('forward_pe'), 1)} "
        f"EV/EBITDA={_fmt_num(med.get('ev_to_ebitda'), 1)} "
        f"P/S={_fmt_num(med.get('price_to_sales'), 2)}"
    )
    rel = comps.get("relative_read") or {}
    for k, v in rel.items():
        if v:
            lines.append(f"  {k}: {v}")

    lines.append("Peer detail:")
    for r in comps.get("peers") or []:
        if r.get("error") and not r.get("price"):
            lines.append(f"  {r.get('ticker')}: ERROR {r.get('error')}")
            continue
        lines.append(
            f"  {r.get('ticker')}: P/E t={_fmt_num(r.get('trailing_pe'), 1)} "
            f"f={_fmt_num(r.get('forward_pe'), 1)} "
            f"EV/EBITDA={_fmt_num(r.get('ev_to_ebitda'), 1)} "
            f"P/S={_fmt_num(r.get('price_to_sales'), 2)} "
            f"mcap={_fmt_money(r.get('market_cap'))}"
        )
    lines.append(
        "INSTRUCTION: Narrate cheap/fair/rich using ONLY these multiples. "
        "Do not invent peer P/Es from memory. Note growth/margin context from "
        "the company packet when judging whether a premium/discount is justified."
    )
    return "\n".join(lines)


# ── Formatting ───────────────────────────────────────────────────────────────

def _fmt_money(v: Any) -> str:
    if v is None:
        return "n/a"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "n/a"
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1e12:
        return f"{sign}${x/1e12:.2f}T"
    if x >= 1e9:
        return f"{sign}${x/1e9:.2f}B"
    if x >= 1e6:
        return f"{sign}${x/1e6:.2f}M"
    if x >= 1e3:
        return f"{sign}${x/1e3:.1f}K"
    return f"{sign}${x:.2f}"


def _fmt_price(v: Any) -> str:
    if v is None:
        return "n/a"
    try:
        return f"${float(v):.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v)*100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_num(v: Any, digits: int = 1) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"
