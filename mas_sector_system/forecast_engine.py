"""Deterministic historical profiling and forward forecast construction.

This module owns arithmetic only.  It reads filing-derived annual statement
series and caller-supplied, already-selected forecast drivers; it performs no
I/O and contains no model calls.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Any, Optional


FORECAST_YEARS = 5


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, dict):
        return _number(value.get("value"))
    return None


def _line(row: dict[str, Any], *names: str) -> Optional[float]:
    for name in names:
        value = _number(row.get(name))
        if value is not None:
            return value
    return None


def _annual_rows(statement: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(statement, dict):
        return {}
    rows: dict[int, dict[str, Any]] = {}
    for row in statement.get("annual_series") or []:
        if not isinstance(row, dict):
            continue
        rank = row.get("rank")
        if isinstance(rank, int) and rank >= 0:
            rows[rank] = row
    return rows


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _growth(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    if current is None or prior in (None, 0):
        return None
    return current / prior - 1.0


def _cagr(current: Optional[float], oldest: Optional[float], intervals: int) -> Optional[float]:
    if (
        current is None
        or oldest is None
        or current <= 0
        or oldest <= 0
        or intervals <= 0
    ):
        return None
    return (current / oldest) ** (1.0 / intervals) - 1.0


def _summary(values: list[float]) -> dict[str, Optional[float]]:
    return {
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": mean(values) if values else None,
    }


def _trend(values_newest_first: list[float]) -> Optional[str]:
    if len(values_newest_first) < 2:
        return None
    delta = values_newest_first[0] - values_newest_first[-1]
    if math.isclose(delta, 0.0, rel_tol=1e-9, abs_tol=1e-12):
        return "stable"
    return "increasing" if delta > 0 else "decreasing"


def _period_value(periods: list[dict[str, Any]], key: str, rank: int) -> Optional[float]:
    for period in periods:
        if period.get("rank") == rank:
            return _number(period.get(key))
    return None


def historical_profile(state: dict) -> dict:
    """Compute filing-derived annual historical facts, newest first.

    Missing ranks and missing ratios are omitted rather than interpolated.
    Negative reported values and ratios are retained.
    """

    income = _annual_rows(state.get("income_statement"))
    balance = _annual_rows(state.get("balance_sheet"))
    cash = _annual_rows(state.get("cash_flow_statement"))
    ranks = sorted(set(income) | set(balance) | set(cash))
    periods: list[dict[str, Any]] = []

    for rank in ranks:
        inc = income.get(rank, {})
        bal = balance.get(rank, {})
        cf = cash.get(rank, {})
        revenue = _line(inc, "Revenues")
        prior_revenue = _line(income.get(rank + 1, {}), "Revenues")
        gross_profit = _line(inc, "GrossProfit")
        if gross_profit is None:
            cost_of_revenue = _line(inc, "CostOfRevenue")
            if revenue is not None and cost_of_revenue is not None:
                gross_profit = revenue - abs(cost_of_revenue)

        operating_income = _line(inc, "OperatingIncomeLoss")
        opex = None
        if gross_profit is not None and operating_income is not None:
            opex = gross_profit - operating_income
        if opex is None:
            opex = _line(inc, "OperatingExpenses")
        prior_inc = income.get(rank + 1, {})
        prior_revenue_for_opex = _line(prior_inc, "Revenues")
        prior_gross_profit = _line(prior_inc, "GrossProfit")
        if prior_gross_profit is None:
            prior_cost = _line(prior_inc, "CostOfRevenue")
            if prior_revenue_for_opex is not None and prior_cost is not None:
                prior_gross_profit = prior_revenue_for_opex - abs(prior_cost)
        prior_operating_income = _line(prior_inc, "OperatingIncomeLoss")
        prior_opex = None
        if prior_gross_profit is not None and prior_operating_income is not None:
            prior_opex = prior_gross_profit - prior_operating_income
        if prior_opex is None:
            prior_opex = _line(prior_inc, "OperatingExpenses")

        net_income = _line(inc, "NetIncomeLoss")
        tax_expense = _line(inc, "IncomeTaxExpense", "IncomeTaxExpenseBenefit")
        pretax_income = _line(
            inc,
            "IncomeBeforeTax",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
        )
        if pretax_income is None and net_income is not None and tax_expense is not None:
            pretax_income = net_income + tax_expense

        capex = _line(cf, "CapitalExpenditures")
        d_and_a = _line(
            cf,
            "DepreciationAndAmortization",
            "DepreciationDepletionAndAmortization",
            "Depreciation",
            "DepreciationRealEstateCF",
        )
        if d_and_a is None:
            d_and_a = _line(
                inc,
                "DepreciationAndAmortization",
                "DepreciationDepletionAndAmortization",
                "Depreciation",
                "DepreciationRealEstate",
            )

        current_assets = _line(bal, "TotalCurrentAssets")
        current_liabilities = _line(bal, "TotalCurrentLiabilities")
        working_capital = None
        if current_assets is not None and current_liabilities is not None:
            working_capital = current_assets - current_liabilities

        diluted_shares = _line(
            inc,
            "WeightedAverageSharesDiluted",
            "WeightedAverageNumberOfDilutedSharesOutstanding",
        )
        if diluted_shares is None:
            diluted_shares = _line(bal, "SharesOutstanding")

        fcf = _line(cf, "FreeCashFlow")
        if fcf is None:
            operating_cash_flow = _line(cf, "NetCashFromOperatingActivities")
            if operating_cash_flow is not None and capex is not None:
                fcf = operating_cash_flow - abs(capex)

        dividends = _line(cf, "DividendsPaid")
        period = {
            "rank": rank,
            "fy": inc.get("fy") or bal.get("fy") or cf.get("fy"),
            "revenue": revenue,
            "revenue_growth": _growth(revenue, prior_revenue),
            "gross_margin": _ratio(gross_profit, revenue),
            "opex": opex,
            "opex_pct_revenue": _ratio(opex, revenue),
            "opex_growth": _growth(opex, prior_opex),
            "effective_tax_rate": _ratio(tax_expense, pretax_income),
            "capex_pct_revenue": _ratio(abs(capex) if capex is not None else None, revenue),
            "d_and_a_pct_revenue": _ratio(
                abs(d_and_a) if d_and_a is not None else None, revenue
            ),
            "working_capital": working_capital,
            "working_capital_pct_revenue": _ratio(working_capital, revenue),
            "diluted_shares": diluted_shares,
            "share_count_growth": _growth(
                diluted_shares,
                _line(
                    income.get(rank + 1, {}),
                    "WeightedAverageSharesDiluted",
                    "WeightedAverageNumberOfDilutedSharesOutstanding",
                )
                or _line(balance.get(rank + 1, {}), "SharesOutstanding"),
            ),
            "free_cash_flow": fcf,
            "fcf_conversion": _ratio(fcf, net_income),
            "dividend_payout": _ratio(
                abs(dividends) if dividends is not None else None, net_income
            ),
        }
        periods.append(period)

    def values(key: str) -> list[float]:
        return [
            float(period[key])
            for period in periods
            if _number(period.get(key)) is not None
        ]

    share_points = [
        (period["rank"], float(period["diluted_shares"]))
        for period in periods
        if _number(period.get("diluted_shares")) is not None
    ]
    shares = [value for _, value in share_points]
    share_count_cagr = None
    if len(share_points) >= 2:
        intervals = share_points[-1][0] - share_points[0][0]
        share_count_cagr = _cagr(shares[0], shares[-1], intervals)

    warnings: list[str] = []
    requested_ratios = (
        "effective_tax_rate",
        "capex_pct_revenue",
        "d_and_a_pct_revenue",
        "working_capital_pct_revenue",
        "diluted_shares",
        "fcf_conversion",
        "dividend_payout",
    )
    for key in requested_ratios:
        if not values(key):
            warnings.append(f"{key} unavailable from annual_series")

    gross_margins = values("gross_margin")
    profile = {
        "periods": periods,
        "period_count": len(periods),
        "revenue": {
            "growth_by_year": [
                {"rank": p["rank"], "fy": p["fy"], "value": p["revenue_growth"]}
                for p in periods
                if p["revenue_growth"] is not None
            ],
            "cagr_3y": _cagr(
                _period_value(periods, "revenue", 0),
                _period_value(periods, "revenue", 2),
                2,
            ),
            "cagr_5y": _cagr(
                _period_value(periods, "revenue", 0),
                _period_value(periods, "revenue", 4),
                4,
            ),
        },
        "gross_margin": {
            "by_year": gross_margins,
            **_summary(gross_margins),
            "trend": _trend(gross_margins),
        },
        "opex_pct_revenue": {
            "by_year": values("opex_pct_revenue"),
            **_summary(values("opex_pct_revenue")),
        },
        "opex_growth": {
            "by_year": values("opex_growth"),
            **_summary(values("opex_growth")),
        },
        "effective_tax_rate": {
            "by_year": values("effective_tax_rate"),
            "mean_5y": mean(values("effective_tax_rate")[:5])
            if values("effective_tax_rate")[:5]
            else None,
        },
        "capex_pct_revenue": {
            "by_year": values("capex_pct_revenue"),
            "mean_5y": mean(values("capex_pct_revenue")[:5])
            if values("capex_pct_revenue")[:5]
            else None,
        },
        "d_and_a_pct_revenue": {
            "by_year": values("d_and_a_pct_revenue"),
            "mean_5y": mean(values("d_and_a_pct_revenue")[:5])
            if values("d_and_a_pct_revenue")[:5]
            else None,
        },
        "working_capital_pct_revenue": {
            "by_year": values("working_capital_pct_revenue"),
            "mean_5y": mean(values("working_capital_pct_revenue")[:5])
            if values("working_capital_pct_revenue")[:5]
            else None,
        },
        "share_count": {
            "trajectory": shares,
            "growth_by_year": values("share_count_growth"),
            "pace": share_count_cagr,
            "implied_buyback_pace": -share_count_cagr
            if share_count_cagr is not None
            else None,
        },
        "fcf_conversion": {
            "by_year": values("fcf_conversion"),
            "mean_5y": mean(values("fcf_conversion")[:5])
            if values("fcf_conversion")[:5]
            else None,
        },
        "dividend_payout": {
            "by_year": values("dividend_payout"),
            "mean_5y": mean(values("dividend_payout")[:5])
            if values("dividend_payout")[:5]
            else None,
        },
        "warnings": warnings,
    }
    return profile


def mechanical_defaults(profile: dict, *, archetype: str) -> dict:
    """Return the empirical layer-3 forecast defaults from history."""

    def profile_value(section: str, key: str = "mean_5y") -> Optional[float]:
        block = profile.get(section)
        return _number(block.get(key)) if isinstance(block, dict) else None

    return {
        "archetype": archetype,
        "tax_rate": profile_value("effective_tax_rate"),
        "d_and_a_pct_revenue": profile_value("d_and_a_pct_revenue"),
        "capex_pct_revenue": profile_value("capex_pct_revenue"),
        "working_capital_pct_revenue": profile_value(
            "working_capital_pct_revenue"
        ),
        "share_count_pace": profile_value("share_count", "pace"),
        "payout": profile_value("dividend_payout"),
    }


def _driver_path(drivers: dict, *names: str) -> Any:
    for name in names:
        if name in drivers:
            return drivers[name]
    return None


def _driver_for_year(value: Any, index: int, *, name: str) -> float:
    if isinstance(value, (list, tuple)):
        if index >= len(value):
            raise ValueError(f"{name} requires one value per forecast year")
        value = value[index]
    number = _number(value)
    if number is None:
        raise ValueError(f"{name} must be a finite number or annual value list")
    return number


def _latest_segments(state: dict) -> tuple[dict[str, float], bool, list[str]]:
    income = _annual_rows(state.get("income_statement"))
    latest = income.get(0, {})
    revenue = _line(latest, "Revenues")
    raw_segments = latest.get("segments")
    segments: dict[str, float] = {}
    if isinstance(raw_segments, dict):
        for name, cell in raw_segments.items():
            value = _number(cell)
            if value is not None:
                segments[str(name)] = value
    warnings: list[str] = []
    if segments and revenue not in (None, 0):
        reconciled = abs(sum(segments.values()) - revenue) / abs(revenue) <= 0.02
        if reconciled:
            return segments, True, warnings
        warnings.append(
            "Segment revenue did not reconcile within 2%; used consolidated revenue"
        )
    elif segments:
        warnings.append(
            "Consolidated revenue unavailable; segment reconciliation could not be tested"
        )
    if revenue is None:
        raise ValueError("rank-0 filing revenue is required to build a forecast")
    if not segments:
        warnings.append("Segment revenue unavailable; used consolidated revenue")
    return {"consolidated": revenue}, False, warnings


def _segment_growth_map(drivers: dict) -> dict[str, Any]:
    nested = _driver_path(drivers, "segment_growth", "revenue_growth")
    result = dict(nested) if isinstance(nested, dict) else {}
    for key, value in drivers.items():
        if isinstance(key, str) and key.startswith("revenue_growth."):
            result[key.split(".", 1)[1]] = value
    return result


def build_forecast(
    state: dict,
    drivers: dict,
    *,
    archetype: str,
    years: int = FORECAST_YEARS,
) -> dict:
    """Build a deterministic annual P&L and FCF forecast.

    The general-driver skeleton accepts segment/revenue growth, gross margin,
    and opex growth as a scalar or one value per forecast year.  Filing facts
    and mechanical defaults provide every remaining input.
    """

    if not isinstance(years, int) or years <= 0:
        raise ValueError("years must be a positive integer")
    if not isinstance(drivers, dict):
        raise TypeError("drivers must be a dictionary")

    profile = historical_profile(state)
    defaults = mechanical_defaults(profile, archetype=archetype)
    required_defaults = (
        "tax_rate",
        "d_and_a_pct_revenue",
        "capex_pct_revenue",
        "working_capital_pct_revenue",
        "share_count_pace",
    )
    missing = [name for name in required_defaults if defaults.get(name) is None]
    if missing:
        raise ValueError(
            "forecast requires filing-derived mechanical defaults: "
            + ", ".join(missing)
        )

    segments, segments_reconciled, warnings = _latest_segments(state)
    growth_map = _segment_growth_map(drivers)
    gross_margin_driver = _driver_path(drivers, "gross_margin")
    opex_growth_driver = _driver_path(drivers, "opex_growth")
    if gross_margin_driver is None or opex_growth_driver is None:
        raise ValueError("gross_margin and opex_growth drivers are required")
    missing_growth = sorted(set(segments) - set(growth_map))
    if missing_growth:
        raise ValueError(
            "revenue growth driver missing for: " + ", ".join(missing_growth)
        )

    periods = profile.get("periods") or []
    current_revenue = _period_value(periods, "revenue", 0)
    current_opex = _period_value(periods, "opex", 0)
    current_shares = _period_value(periods, "diluted_shares", 0)
    if current_revenue is None or current_opex is None or current_shares in (None, 0):
        raise ValueError("rank-0 revenue, opex, and diluted shares are required")

    income_rows = _annual_rows(state.get("income_statement"))
    current_fy_raw = income_rows.get(0, {}).get("fy")
    try:
        current_fy = int(str(current_fy_raw))
    except (TypeError, ValueError):
        current_fy = None

    projected: list[dict[str, Any]] = []
    prior_revenue = current_revenue
    prior_opex = current_opex
    prior_shares = current_shares
    segment_values = dict(segments)

    for index in range(years):
        revenue_by_segment: dict[str, float] = {}
        for name, base in segment_values.items():
            growth = _driver_for_year(
                growth_map[name], index, name=f"revenue_growth.{name}"
            )
            revenue_by_segment[name] = base * (1.0 + growth)
        segment_values = revenue_by_segment
        revenue = sum(revenue_by_segment.values())
        gross_margin = _driver_for_year(
            gross_margin_driver, index, name="gross_margin"
        )
        opex_growth = _driver_for_year(
            opex_growth_driver, index, name="opex_growth"
        )
        gross_profit = revenue * gross_margin
        opex = prior_opex * (1.0 + opex_growth)
        operating_income = gross_profit - opex
        tax_expense = operating_income * defaults["tax_rate"]
        net_income = operating_income - tax_expense
        shares = prior_shares * (1.0 + defaults["share_count_pace"])
        if shares <= 0:
            raise ValueError("mechanical share-count pace produced non-positive shares")
        eps = net_income / shares
        d_and_a = revenue * defaults["d_and_a_pct_revenue"]
        capex = revenue * defaults["capex_pct_revenue"]
        delta_working_capital = (
            revenue - prior_revenue
        ) * defaults["working_capital_pct_revenue"]
        free_cash_flow = net_income + d_and_a - capex - delta_working_capital
        fy = f"{current_fy + index + 1}E" if current_fy is not None else f"Y{index + 1}E"

        projected.append(
            {
                "fy": fy,
                "revenue": revenue,
                "revenue_by_segment": revenue_by_segment,
                "gross_profit": gross_profit,
                "gross_margin": gross_margin,
                "opex": opex,
                "operating_income": operating_income,
                "net_income": net_income,
                "eps_diluted": eps,
                "d_and_a": d_and_a,
                "capex": capex,
                "delta_working_capital": delta_working_capital,
                "free_cash_flow": free_cash_flow,
            }
        )
        prior_revenue = revenue
        prior_opex = opex
        prior_shares = shares

    if projected and projected[-1]["revenue"] > current_revenue * 6.0:
        raise ValueError("year-5 revenue exceeds the 6x terminal sanity limit")

    return {
        "archetype": archetype,
        "years": projected,
        "drivers_applied": {
            "revenue_growth": growth_map,
            "gross_margin": gross_margin_driver,
            "opex_growth": opex_growth_driver,
        },
        "mechanical_defaults_used": defaults,
        "warnings": [*(profile.get("warnings") or []), *warnings],
        "segments_reconciled": segments_reconciled,
    }
