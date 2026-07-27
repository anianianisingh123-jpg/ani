"""Canonical metrics contract — deterministic load-bearing figures.

Any number that appears in a memo must be computed here (or by another
Python engine such as valuation_engine), carry its own provenance and
qualifiers, and be quoted verbatim by LLM agents via the ``headline`` field.

Agents must not recompute, re-express, annualize, or paraphrase these figures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# Period keys produced by tools.extract_statements_from_company_facts.
PERIOD_KEYS: tuple[str, ...] = (
    "current_annual",
    "prior_annual",
    "current_quarter",
    "prior_quarter",
)

# How long each period key is assumed to cover when XBRL does not say otherwise.
# Nine-month YTD blocks must be detected and labeled — never treated as QoQ.
_DURATION_BY_FP = {
    "FY": "12mo",
    "Q1": "3mo",
    "Q2": "3mo",
    "Q3": "3mo",
    "Q4": "3mo",
}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_float(x: Any) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _line(period_block: Any, *keys: str) -> dict[str, Any]:
    """Return the first matching line dict (value/end/fy/fp/form/filed/note)."""
    if not isinstance(period_block, dict):
        return {}
    for key in keys:
        cell = period_block.get(key)
        if isinstance(cell, dict):
            return cell
        if isinstance(cell, (int, float)) and not isinstance(cell, bool):
            return {"value": float(cell)}
    return {}


def _line_value(period_block: Any, *keys: str) -> Optional[float]:
    cell = _line(period_block, *keys)
    return _safe_float(cell.get("value")) if cell else None


def _period(statement: Any, name: str) -> dict:
    if not isinstance(statement, dict):
        return {}
    block = statement.get(name)
    return block if isinstance(block, dict) else {}


def _fmt_money(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e12:
        return f"{sign}${a / 1e12:.2f}T"
    if a >= 1e9:
        return f"{sign}${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.2f}M"
    if a >= 1e3:
        return f"{sign}${a / 1e3:.2f}K"
    return f"{sign}${a:.2f}"


def _fmt_pct(v: Optional[float], *, bps: bool = False) -> str:
    if v is None:
        return "n/a"
    if bps:
        return f"{v:+.0f} bps"
    return f"{v * 100:.1f}%"


def _fmt_num(v: Optional[float], digits: int = 2) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{digits}f}"


def _parse_date(s: Any) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    try:
        # XBRL end dates are YYYY-MM-DD
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _period_meta(period_block: dict, period_key: str) -> dict[str, Any]:
    """Infer label, duration, and reference end date for a period block."""
    # Prefer revenue / total assets as the period's "spine" dates.
    spine_keys = (
        "Revenues",
        "TotalAssets",
        "Assets",
        "NetIncomeLoss",
        "CashAndCashEquivalents",
        "NetCashFromOperatingActivities",
    )
    end = fy = fp = form = filed = None
    for k in spine_keys:
        cell = period_block.get(k)
        if isinstance(cell, dict) and cell.get("end"):
            end = cell.get("end")
            fy = cell.get("fy")
            fp = cell.get("fp")
            form = cell.get("form")
            filed = cell.get("filed")
            break
    if end is None:
        # Fall back to any line with an end date.
        for cell in period_block.values():
            if isinstance(cell, dict) and cell.get("end"):
                end = cell.get("end")
                fy = cell.get("fy")
                fp = cell.get("fp")
                form = cell.get("form")
                filed = cell.get("filed")
                break

    fp_u = (str(fp) if fp is not None else "").upper()
    form_u = (str(form) if form is not None else "").upper()
    duration = _DURATION_BY_FP.get(fp_u)
    ytd_suspected = False
    note_bits: list[str] = []

    # Heuristic: cumulative / YTD frames in SEC sometimes surface as quarters
    # with very large values relative to annual — agents must not QoQ them.
    frame_blob = " ".join(
        str((c or {}).get("frame") or "")
        for c in period_block.values()
        if isinstance(c, dict)
    ).upper()
    if "YTD" in frame_blob or "NINE" in frame_blob or "9M" in frame_blob:
        ytd_suspected = True
        duration = "YTD_cumulative"
        note_bits.append("XBRL frame suggests YTD/cumulative — not a discrete quarter")

    if duration is None:
        if "annual" in period_key:
            duration = "12mo"
        elif "quarter" in period_key:
            duration = "3mo_assumed"
            note_bits.append(
                "duration assumed ~3mo from period key; not independently verified"
            )
        else:
            duration = "unknown"
            note_bits.append("period duration ambiguous")

    # Prefer end-date in the label — XBRL `fy` can be unreliable across ranks.
    if "annual" in period_key:
        if end:
            label = f"year ended {end}"
            if fy is not None:
                label = f"{label} (filer FY field={fy})"
        else:
            label = f"FY{fy}" if fy is not None else period_key
    else:
        if end:
            label = f"{fp_u or 'Qx'} ended {end}"
            if fy is not None:
                label = f"{label} (filer FY field={fy})"
        else:
            label = f"{fp_u or 'Q?'} FY{fy}" if fy is not None else period_key
        if ytd_suspected:
            label = f"{label} [YTD/CUMULATIVE — not discrete quarter]"

    return {
        "period_key": period_key,
        "label": label,
        "duration": duration,
        "end": end,
        "fy": fy,
        "fp": fp_u or None,
        "form": form_u or None,
        "filed": filed,
        "notes": note_bits,
        # Candidate only — cross-period checks must also verify end-date adjacency.
        "comparable_for_qoq": (
            duration in ("3mo", "3mo_assumed") and not ytd_suspected
        ),
    }


def _staleness_for_line(
    cell: dict[str, Any],
    ref_end: Optional[str],
    *,
    line_name: str,
) -> list[str]:
    """Flag lines whose XBRL end date is stale vs the period's spine date."""
    flags: list[str] = []
    note = (cell.get("note") or "") if isinstance(cell, dict) else ""
    if "STALE" in note.upper():
        flags.append(f"{line_name}: note marks STALE ({note[:80]})")
    line_end = cell.get("end") if isinstance(cell, dict) else None
    d_line = _parse_date(line_end)
    d_ref = _parse_date(ref_end)
    if d_line and d_ref:
        delta = (d_ref - d_line).days
        if delta > 120:
            flags.append(
                f"{line_name}: XBRL end {line_end} is {delta}d before period end "
                f"{ref_end} (stale tag risk)"
            )
    return flags


def _record(
    *,
    id: str,
    value: Any,
    unit: str,
    basis_period: str,
    qualifiers: list[str],
    staleness: list[str],
    source_lines: list[str],
    computation: str,
    applicable: bool,
    headline: str,
    confidence: str = "moderate",
    period_key: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "value": value,
        "unit": unit,
        "basis_period": basis_period,
        "period_key": period_key,
        "qualifiers": list(qualifiers),
        "staleness": list(staleness),
        "source_lines": list(source_lines),
        "computation": computation,
        "applicable": applicable,
        "headline": headline,
        "confidence": confidence,
    }


def _unavailable(
    id: str,
    *,
    basis_period: str,
    reason: str,
    source_lines: list[str],
    computation: str,
    period_key: Optional[str] = None,
) -> dict[str, Any]:
    return _record(
        id=id,
        value=None,
        unit="",
        basis_period=basis_period,
        qualifiers=[],
        staleness=[],
        source_lines=source_lines,
        computation=computation,
        applicable=False,
        headline=f"{id} unavailable — {reason}",
        confidence="none",
        period_key=period_key,
    )


def _live_market_from_statements(
    income: dict, balance: dict, cash_flow: dict, live_market: Optional[dict]
) -> dict[str, Any]:
    if isinstance(live_market, dict) and (
        live_market.get("price") is not None or live_market.get("market_cap") is not None
    ):
        return live_market
    for stmt in (income, balance, cash_flow):
        if isinstance(stmt, dict) and isinstance(stmt.get("live_market"), dict):
            lm = stmt["live_market"]
            if lm.get("price") is not None or lm.get("market_cap") is not None:
                return lm
    return live_market if isinstance(live_market, dict) else {}


# ─────────────────────────────────────────────────────────────────────────────
# Per-period builders
# ─────────────────────────────────────────────────────────────────────────────

def _margin_metrics(
    income: dict,
    cash_flow: dict,
    period_key: str,
    meta: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    inc = _period(income, period_key)
    cf = _period(cash_flow, period_key)
    label = meta["label"]
    pk = period_key

    rev = _line_value(inc, "Revenues")
    gp = _line_value(inc, "GrossProfit")
    if gp is None and rev is not None:
        cogs = _line_value(inc, "CostOfRevenue")
        if cogs is not None:
            gp = rev - abs(cogs)
    opinc = _line_value(inc, "OperatingIncomeLoss")
    ni = _line_value(inc, "NetIncomeLoss")
    fcf = _line_value(cf, "FreeCashFlow")

    def _m(name: str, num: Optional[float], den: Optional[float], comp: str, src: list[str]):
        mid = f"{name}__{pk}"
        if den is None or den == 0 or num is None:
            out.append(
                _unavailable(
                    mid,
                    basis_period=label,
                    reason="missing numerator or denominator",
                    source_lines=src,
                    computation=comp,
                    period_key=pk,
                )
            )
            return
        val = num / den
        out.append(
            _record(
                id=mid,
                value=val,
                unit="ratio",
                basis_period=label,
                period_key=pk,
                qualifiers=[f"duration={meta['duration']}"],
                staleness=[],
                source_lines=src,
                computation=comp,
                applicable=True,
                headline=(
                    f"{name.replace('_', ' ')} of {_fmt_pct(val)} "
                    f"({label}; {comp})"
                ),
                confidence="high" if not meta.get("notes") else "moderate",
            )
        )

    _m("gross_margin", gp, rev, "gross_profit / revenue", ["GrossProfit", "Revenues"])
    _m(
        "operating_margin",
        opinc,
        rev,
        "operating_income / revenue",
        ["OperatingIncomeLoss", "Revenues"],
    )
    _m("net_margin", ni, rev, "net_income / revenue", ["NetIncomeLoss", "Revenues"])
    _m(
        "fcf_margin",
        fcf,
        rev,
        "free_cash_flow / revenue",
        ["FreeCashFlow", "Revenues"],
    )
    if fcf is not None and ni is not None and ni != 0:
        out.append(
            _record(
                id=f"fcf_conversion__{pk}",
                value=fcf / ni,
                unit="ratio",
                basis_period=label,
                period_key=pk,
                qualifiers=[f"duration={meta['duration']}"],
                staleness=[],
                source_lines=["FreeCashFlow", "NetIncomeLoss"],
                computation="FCF / net_income",
                applicable=True,
                headline=(
                    f"FCF conversion of {_fmt_pct(fcf / ni)} "
                    f"(FCF/NI, {label})"
                ),
            )
        )
    else:
        out.append(
            _unavailable(
                f"fcf_conversion__{pk}",
                basis_period=label,
                reason="missing FCF or net income",
                source_lines=["FreeCashFlow", "NetIncomeLoss"],
                computation="FCF / net_income",
                period_key=pk,
            )
        )
    return out


def _scale_and_bs_metrics(
    balance: dict,
    period_key: str,
    meta: dict[str, Any],
    live: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    bal = _period(balance, period_key)
    label = meta["label"]
    pk = period_key
    ref_end = meta.get("end")

    cash_cell = _line(bal, "CashAndCashEquivalents")
    st_cell = _line(bal, "ShortTermInvestments")
    st_debt_cell = _line(bal, "ShortTermDebt")
    lt_debt_cell = _line(bal, "LongTermDebt")
    equity_cell = _line(bal, "StockholdersEquity")
    assets_cell = _line(bal, "TotalAssets")
    ca_cell = _line(bal, "TotalCurrentAssets")
    cl_cell = _line(bal, "TotalCurrentLiabilities")
    inv_cell = _line(bal, "Inventory")
    ar_cell = _line(bal, "AccountsReceivable")
    gw_cell = _line(bal, "Goodwill")

    cash = _safe_float(cash_cell.get("value"))
    st_inv = _safe_float(st_cell.get("value"))
    st_debt = _safe_float(st_debt_cell.get("value")) or 0.0
    lt_debt = _safe_float(lt_debt_cell.get("value")) or 0.0
    has_debt_tag = bool(st_debt_cell or lt_debt_cell)
    total_debt = (st_debt + lt_debt) if has_debt_tag else None
    equity = _safe_float(equity_cell.get("value"))
    assets = _safe_float(assets_cell.get("value"))

    # --- Net cash EX short-term investments (partial metric — must stay labeled)
    stale_ex: list[str] = []
    stale_ex += _staleness_for_line(cash_cell, ref_end, line_name="CashAndCashEquivalents")
    stale_ex += _staleness_for_line(st_debt_cell, ref_end, line_name="ShortTermDebt")
    stale_ex += _staleness_for_line(lt_debt_cell, ref_end, line_name="LongTermDebt")
    if cash is not None and total_debt is not None:
        net_ex = cash - total_debt
        q = [
            "EXCLUDES short-term investments",
            "partial liquidity view — do not present as full net cash",
            f"duration={meta['duration']}",
        ]
        out.append(
            _record(
                id=f"net_cash_ex_st_investments__{pk}",
                value=net_ex,
                unit="USD",
                basis_period=label,
                period_key=pk,
                qualifiers=q,
                staleness=stale_ex,
                source_lines=[
                    "CashAndCashEquivalents",
                    "ShortTermDebt",
                    "LongTermDebt",
                ],
                computation="cash - (short_term_debt + long_term_debt); ST investments excluded",
                applicable=True,
                headline=(
                    f"net cash ex-ST-investments of {_fmt_money(net_ex)} "
                    f"({label}; cash − total debt only; EXCLUDES short-term investments"
                    + (
                        f"; STALE: {'; '.join(stale_ex)}"
                        if stale_ex
                        else ""
                    )
                    + ")"
                ),
                confidence="moderate" if stale_ex else "high",
            )
        )
        # Companion net-debt sign convention for DCF bridges
        out.append(
            _record(
                id=f"net_debt_ex_st_investments__{pk}",
                value=-net_ex,
                unit="USD",
                basis_period=label,
                period_key=pk,
                qualifiers=q
                + ["net_debt = -net_cash_ex_st; negative means net cash"],
                staleness=stale_ex,
                source_lines=[
                    "CashAndCashEquivalents",
                    "ShortTermDebt",
                    "LongTermDebt",
                ],
                computation="(st_debt + lt_debt) - cash; ST investments excluded",
                applicable=True,
                headline=(
                    f"net debt ex-ST-investments of {_fmt_money(-net_ex)} "
                    f"({label}; total debt − cash only; EXCLUDES short-term investments; "
                    f"negative = net cash position on this partial basis"
                    + (
                        f"; STALE: {'; '.join(stale_ex)}"
                        if stale_ex
                        else ""
                    )
                    + ")"
                ),
                confidence="moderate" if stale_ex else "high",
            )
        )
    else:
        out.append(
            _unavailable(
                f"net_cash_ex_st_investments__{pk}",
                basis_period=label,
                reason="missing cash and/or debt tags",
                source_lines=["CashAndCashEquivalents", "ShortTermDebt", "LongTermDebt"],
                computation="cash - total_debt",
                period_key=pk,
            )
        )

    # --- Net cash INCLUDING short-term investments (preferred economic view)
    stale_in: list[str] = list(stale_ex)
    stale_in += _staleness_for_line(st_cell, ref_end, line_name="ShortTermInvestments")
    if cash is not None and total_debt is not None:
        st_part = st_inv if st_inv is not None else 0.0
        if st_inv is None:
            stale_in.append("ShortTermInvestments: tag missing — treated as 0")
        net_in = cash + st_part - total_debt
        q = [
            "INCLUDES short-term investments" if st_inv is not None else "ST investments missing (treated as 0)",
            f"duration={meta['duration']}",
        ]
        out.append(
            _record(
                id=f"net_cash_incl_st_investments__{pk}",
                value=net_in,
                unit="USD",
                basis_period=label,
                period_key=pk,
                qualifiers=q,
                staleness=stale_in,
                source_lines=[
                    "CashAndCashEquivalents",
                    "ShortTermInvestments",
                    "ShortTermDebt",
                    "LongTermDebt",
                ],
                computation="cash + st_investments - total_debt",
                applicable=True,
                headline=(
                    f"net cash of {_fmt_money(net_in)} "
                    f"(incl. ST investments, {label}"
                    + (
                        f"; ST investments={_fmt_money(st_inv)}"
                        if st_inv is not None
                        else "; ST investments missing→0"
                    )
                    + (
                        f"; STALE: {'; '.join(stale_in)}"
                        if stale_in
                        else ""
                    )
                    + ")"
                ),
                confidence="low" if stale_in else "high",
            )
        )
    else:
        out.append(
            _unavailable(
                f"net_cash_incl_st_investments__{pk}",
                basis_period=label,
                reason="missing cash and/or debt tags",
                source_lines=[
                    "CashAndCashEquivalents",
                    "ShortTermInvestments",
                    "TotalDebt",
                ],
                computation="cash + st_investments - total_debt",
                period_key=pk,
            )
        )

    if total_debt is not None:
        out.append(
            _record(
                id=f"total_debt__{pk}",
                value=total_debt,
                unit="USD",
                basis_period=label,
                period_key=pk,
                qualifiers=[f"duration={meta['duration']}"],
                staleness=stale_ex,
                source_lines=["ShortTermDebt", "LongTermDebt"],
                computation="short_term_debt + long_term_debt",
                applicable=True,
                headline=f"total debt of {_fmt_money(total_debt)} ({label})",
            )
        )

    if equity is not None and equity != 0 and total_debt is not None:
        de = total_debt / equity
        out.append(
            _record(
                id=f"debt_to_equity__{pk}",
                value=de,
                unit="ratio",
                basis_period=label,
                period_key=pk,
                qualifiers=[f"duration={meta['duration']}"],
                staleness=[],
                source_lines=["ShortTermDebt", "LongTermDebt", "StockholdersEquity"],
                computation="total_debt / stockholders_equity",
                applicable=True,
                headline=f"debt/equity of {_fmt_num(de, 3)} ({label})",
            )
        )

    ca = _safe_float(ca_cell.get("value"))
    cl = _safe_float(cl_cell.get("value"))
    if ca is not None and cl is not None and cl != 0:
        out.append(
            _record(
                id=f"current_ratio__{pk}",
                value=ca / cl,
                unit="ratio",
                basis_period=label,
                period_key=pk,
                qualifiers=[f"duration={meta['duration']}"],
                staleness=[],
                source_lines=["TotalCurrentAssets", "TotalCurrentLiabilities"],
                computation="current_assets / current_liabilities",
                applicable=True,
                headline=f"current ratio of {_fmt_num(ca / cl, 2)} ({label})",
            )
        )

    if assets is not None and assets != 0:
        gw = _safe_float(gw_cell.get("value"))
        if gw is not None:
            out.append(
                _record(
                    id=f"goodwill_pct_assets__{pk}",
                    value=gw / assets,
                    unit="ratio",
                    basis_period=label,
                    period_key=pk,
                    qualifiers=[f"duration={meta['duration']}"],
                    staleness=[],
                    source_lines=["Goodwill", "TotalAssets"],
                    computation="goodwill / total_assets",
                    applicable=True,
                    headline=(
                        f"goodwill {_fmt_pct(gw / assets)} of total assets "
                        f"({_fmt_money(gw)} / {_fmt_money(assets)}, {label})"
                    ),
                )
            )

    # Inventory / AR absolute levels (growth computed across periods elsewhere)
    for name, cell, sid in (
        ("inventory", inv_cell, f"inventory__{pk}"),
        ("accounts_receivable", ar_cell, f"accounts_receivable__{pk}"),
        ("stockholders_equity", equity_cell, f"stockholders_equity__{pk}"),
        ("total_assets", assets_cell, f"total_assets__{pk}"),
        ("cash", cash_cell, f"cash__{pk}"),
        ("short_term_investments", st_cell, f"short_term_investments__{pk}"),
    ):
        val = _safe_float(cell.get("value")) if cell else None
        st = _staleness_for_line(cell, ref_end, line_name=name) if cell else []
        if val is None:
            out.append(
                _unavailable(
                    sid,
                    basis_period=label,
                    reason=f"{name} not tagged",
                    source_lines=[name],
                    computation="statement line",
                    period_key=pk,
                )
            )
        else:
            out.append(
                _record(
                    id=sid,
                    value=val,
                    unit="USD",
                    basis_period=label,
                    period_key=pk,
                    qualifiers=[f"duration={meta['duration']}"],
                    staleness=st,
                    source_lines=[name],
                    computation="statement line",
                    applicable=True,
                    headline=(
                        f"{name.replace('_', ' ')} of {_fmt_money(val)} ({label}"
                        + (f"; STALE: {'; '.join(st)}" if st else "")
                        + ")"
                    ),
                    confidence="low" if st else "high",
                )
            )

    return out


def _income_level_metrics(
    income: dict,
    cash_flow: dict,
    period_key: str,
    meta: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    inc = _period(income, period_key)
    cf = _period(cash_flow, period_key)
    label = meta["label"]
    pk = period_key

    pairs = [
        ("revenue", ["Revenues"], "Revenues"),
        ("gross_profit", ["GrossProfit"], "GrossProfit"),
        ("operating_income", ["OperatingIncomeLoss"], "OperatingIncomeLoss"),
        ("net_income", ["NetIncomeLoss"], "NetIncomeLoss"),
        ("rd_expense", ["ResearchAndDevelopmentExpense", "RD_Expense"], "R&D"),
        (
            "eps_diluted",
            ["EarningsPerShareDiluted", "EPS_Diluted"],
            "EPS diluted",
        ),
        (
            "eps_basic",
            ["EarningsPerShareBasic", "EPS_Basic"],
            "EPS basic",
        ),
        (
            "shares_diluted",
            [
                "WeightedAverageNumberOfDilutedSharesOutstanding",
                "WeightedAverageSharesDiluted",
            ],
            "diluted weighted-average shares",
        ),
        (
            "shares_basic",
            [
                "WeightedAverageNumberOfSharesOutstandingBasic",
                "WeightedAverageSharesBasic",
            ],
            "basic weighted-average shares",
        ),
        ("interest_expense", ["InterestExpense", "InterestExpenseBank"], "interest expense"),
        # Archetype-specific (null for commercial companies)
        ("interest_income", ["InterestIncome"], "interest income"),
        ("net_interest_income", ["NetInterestIncome"], "net interest income"),
        ("noninterest_income", ["NoninterestIncome"], "noninterest income"),
        ("premiums_earned", ["PremiumsEarned"], "premiums earned"),
        ("ffo", ["FFO"], "FFO (NAREIT-style derived)"),
        ("loans_net", ["LoansNet"], "loans net"),  # will miss on income — also BS
        ("deposits", ["Deposits"], "deposits"),
    ]
    for mid, keys, pretty in pairs:
        cell = _line(inc, *keys)
        val = _safe_float(cell.get("value")) if cell else None
        st = _staleness_for_line(cell, meta.get("end"), line_name=keys[0]) if cell else []
        unit = "USD_per_share" if "eps" in mid else ("shares" if "shares" in mid else "USD")
        rid = f"{mid}__{pk}"
        if val is None:
            out.append(
                _unavailable(
                    rid,
                    basis_period=label,
                    reason=f"{pretty} not tagged",
                    source_lines=list(keys),
                    computation="statement line",
                    period_key=pk,
                )
            )
        else:
            if unit == "USD":
                hv = _fmt_money(val)
            elif unit == "shares":
                hv = f"{val:,.0f}" if val >= 1000 else _fmt_num(val, 3)
            else:
                hv = _fmt_num(val, 2)
            out.append(
                _record(
                    id=rid,
                    value=val,
                    unit=unit,
                    basis_period=label,
                    period_key=pk,
                    qualifiers=[f"duration={meta['duration']}"],
                    staleness=st,
                    source_lines=list(keys),
                    computation="statement line",
                    applicable=True,
                    headline=(
                        f"{pretty} of {hv} ({label}"
                        + (f"; STALE: {'; '.join(st)}" if st else "")
                        + ")"
                    ),
                    confidence="low" if st else "high",
                )
            )

    # Capex, FCF, buybacks, dividends from cash flow — per period only
    cf_pairs = [
        ("fcf", ["FreeCashFlow"], "free cash flow"),
        ("ocf", ["NetCashFromOperatingActivities"], "operating cash flow"),
        ("capex", ["CapitalExpenditures"], "capex"),
        ("buyback_spend", ["StockRepurchases"], "share repurchase spend"),
        ("dividends_paid", ["DividendsPaid"], "dividends paid"),
    ]
    for mid, keys, pretty in cf_pairs:
        cell = _line(cf, *keys)
        val = _safe_float(cell.get("value")) if cell else None
        # Capex/buybacks often positive payments
        if mid in ("capex", "buyback_spend", "dividends_paid") and val is not None:
            val = abs(val)
        st = _staleness_for_line(cell, meta.get("end"), line_name=keys[0]) if cell else []
        rid = f"{mid}__{pk}"
        if val is None:
            out.append(
                _unavailable(
                    rid,
                    basis_period=label,
                    reason=f"{pretty} not tagged",
                    source_lines=list(keys),
                    computation="statement line",
                    period_key=pk,
                )
            )
        else:
            out.append(
                _record(
                    id=rid,
                    value=val,
                    unit="USD",
                    basis_period=label,
                    period_key=pk,
                    qualifiers=[f"duration={meta['duration']}"],
                    staleness=st,
                    source_lines=list(keys),
                    computation="statement line (absolute value for payments)",
                    applicable=True,
                    headline=(
                        f"{pretty} of {_fmt_money(val)} ({label}"
                        + (f"; STALE: {'; '.join(st)}" if st else "")
                        + ")"
                    ),
                    confidence="low" if st else "high",
                )
            )

    # Ratios within period: R&D %, capex %, payout, FCF/share
    rev = _line_value(inc, "Revenues")
    rd = _line_value(inc, "ResearchAndDevelopmentExpense", "RD_Expense")
    capex = _line_value(cf, "CapitalExpenditures")
    if capex is not None:
        capex = abs(capex)
    fcf = _line_value(cf, "FreeCashFlow")
    div = _line_value(cf, "DividendsPaid")
    if div is not None:
        div = abs(div)
    shares = _line_value(
        inc,
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageSharesDiluted",
    )

    if rev and rev != 0 and rd is not None:
        out.append(
            _record(
                id=f"rd_pct_revenue__{pk}",
                value=rd / rev,
                unit="ratio",
                basis_period=label,
                period_key=pk,
                qualifiers=[f"duration={meta['duration']}"],
                staleness=[],
                source_lines=["ResearchAndDevelopmentExpense", "Revenues"],
                computation="R&D / revenue",
                applicable=True,
                headline=f"R&D {_fmt_pct(rd / rev)} of revenue ({label})",
            )
        )
    if rev and rev != 0 and capex is not None:
        out.append(
            _record(
                id=f"capex_pct_revenue__{pk}",
                value=capex / rev,
                unit="ratio",
                basis_period=label,
                period_key=pk,
                qualifiers=[f"duration={meta['duration']}"],
                staleness=[],
                source_lines=["CapitalExpenditures", "Revenues"],
                computation="|capex| / revenue",
                applicable=True,
                headline=f"capex {_fmt_pct(capex / rev)} of revenue ({label})",
            )
        )
    if fcf is not None and fcf != 0 and div is not None:
        out.append(
            _record(
                id=f"dividend_payout_fcf__{pk}",
                value=div / fcf,
                unit="ratio",
                basis_period=label,
                period_key=pk,
                qualifiers=[f"duration={meta['duration']}"],
                staleness=[],
                source_lines=["DividendsPaid", "FreeCashFlow"],
                computation="|dividends| / FCF",
                applicable=True,
                headline=f"dividend payout {_fmt_pct(div / fcf)} of FCF ({label})",
            )
        )
    if fcf is not None and shares and shares > 0:
        out.append(
            _record(
                id=f"fcf_per_share__{pk}",
                value=fcf / shares,
                unit="USD_per_share",
                basis_period=label,
                period_key=pk,
                qualifiers=[f"duration={meta['duration']}"],
                staleness=[],
                source_lines=["FreeCashFlow", "WeightedAverageSharesDiluted"],
                computation="FCF / diluted weighted-average shares",
                applicable=True,
                headline=f"FCF/share of {_fmt_num(fcf / shares, 2)} ({label})",
            )
        )

    # Interest coverage
    opinc = _line_value(inc, "OperatingIncomeLoss")
    interest = _line_value(inc, "InterestExpense")
    if interest is not None:
        interest = abs(interest)
    int_st = _staleness_for_line(
        _line(inc, "InterestExpense"), meta.get("end"), line_name="InterestExpense"
    )
    if opinc is not None and interest and interest > 0:
        out.append(
            _record(
                id=f"interest_coverage__{pk}",
                value=opinc / interest,
                unit="ratio",
                basis_period=label,
                period_key=pk,
                qualifiers=[f"duration={meta['duration']}"],
                staleness=int_st,
                source_lines=["OperatingIncomeLoss", "InterestExpense"],
                computation="operating_income / |interest_expense|",
                applicable=True,
                headline=(
                    f"interest coverage {_fmt_num(opinc / interest, 1)}x ({label}"
                    + (f"; STALE: {'; '.join(int_st)}" if int_st else "")
                    + ")"
                ),
                confidence="low" if int_st else "moderate",
            )
        )
    else:
        out.append(
            _unavailable(
                f"interest_coverage__{pk}",
                basis_period=label,
                reason="missing operating income or interest expense",
                source_lines=["OperatingIncomeLoss", "InterestExpense"],
                computation="operating_income / |interest_expense|",
                period_key=pk,
            )
        )

    return out


def _growth_pair(
    *,
    id: str,
    cur: Optional[float],
    prior: Optional[float],
    cur_label: str,
    prior_label: str,
    pretty: str,
    source_lines: list[str],
    comparable: bool,
    incomparable_reason: str = "",
) -> dict[str, Any]:
    if not comparable:
        return _unavailable(
            id,
            basis_period=f"{cur_label} vs {prior_label}",
            reason=incomparable_reason or "periods not comparable",
            source_lines=source_lines,
            computation=f"({pretty}_cur / {pretty}_prior) - 1",
        )
    if cur is None or prior is None or prior == 0:
        return _unavailable(
            id,
            basis_period=f"{cur_label} vs {prior_label}",
            reason="missing current or prior value",
            source_lines=source_lines,
            computation=f"({pretty}_cur / {pretty}_prior) - 1",
        )
    g = (cur / prior) - 1.0
    return _record(
        id=id,
        value=g,
        unit="ratio",
        basis_period=f"{cur_label} vs {prior_label}",
        qualifiers=["YoY" if "annual" in id or "FY" in cur_label else "period-over-period"],
        staleness=[],
        source_lines=source_lines,
        computation=f"({pretty}_cur / {pretty}_prior) - 1 — never summed across periods",
        applicable=True,
        headline=(
            f"{pretty} growth of {_fmt_pct(g)} "
            f"({cur_label} vs {prior_label}; each period separate)"
        ),
        confidence="high",
    )


def _cross_period_metrics(
    income: dict,
    balance: dict,
    cash_flow: dict,
    metas: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Growth and buyback efficiency — always one pair of periods, never summed."""
    out: list[dict[str, Any]] = []

    # Annual YoY
    ca, pa = "current_annual", "prior_annual"
    if ca in metas and pa in metas:
        cl, pl = metas[ca]["label"], metas[pa]["label"]
        for mid, getter, pretty, src in (
            (
                "revenue_yoy",
                lambda s, p: _line_value(_period(s, p), "Revenues"),
                "revenue",
                ["Revenues"],
            ),
            (
                "net_income_yoy",
                lambda s, p: _line_value(_period(s, p), "NetIncomeLoss"),
                "net income",
                ["NetIncomeLoss"],
            ),
            (
                "operating_income_yoy",
                lambda s, p: _line_value(_period(s, p), "OperatingIncomeLoss"),
                "operating income",
                ["OperatingIncomeLoss"],
            ),
            (
                "fcf_yoy",
                lambda s, p: _line_value(_period(s, p), "FreeCashFlow"),
                "FCF",
                ["FreeCashFlow"],
            ),
        ):
            stmt = cash_flow if "fcf" in mid else income
            out.append(
                _growth_pair(
                    id=mid,
                    cur=getter(stmt, ca),
                    prior=getter(stmt, pa),
                    cur_label=cl,
                    prior_label=pl,
                    pretty=pretty,
                    source_lines=src,
                    comparable=True,
                )
            )

        # Margin bps change (annual)
        def _gm(pk: str) -> Optional[float]:
            inc = _period(income, pk)
            rev = _line_value(inc, "Revenues")
            gp = _line_value(inc, "GrossProfit")
            if gp is None and rev is not None:
                cogs = _line_value(inc, "CostOfRevenue")
                if cogs is not None:
                    gp = rev - abs(cogs)
            if rev and rev != 0 and gp is not None:
                return gp / rev
            return None

        def _om(pk: str) -> Optional[float]:
            inc = _period(income, pk)
            rev = _line_value(inc, "Revenues")
            op = _line_value(inc, "OperatingIncomeLoss")
            if rev and rev != 0 and op is not None:
                return op / rev
            return None

        for mid, fn, pretty in (
            ("gross_margin_yoy_bps", _gm, "gross margin"),
            ("operating_margin_yoy_bps", _om, "operating margin"),
        ):
            cur_m, pri_m = fn(ca), fn(pa)
            if cur_m is None or pri_m is None:
                out.append(
                    _unavailable(
                        mid,
                        basis_period=f"{cl} vs {pl}",
                        reason="missing margin inputs",
                        source_lines=["Revenues", "margins"],
                        computation="(cur_margin - prior_margin) * 10000 bps",
                    )
                )
            else:
                bps = (cur_m - pri_m) * 10000
                out.append(
                    _record(
                        id=mid,
                        value=bps,
                        unit="bps",
                        basis_period=f"{cl} vs {pl}",
                        qualifiers=["YoY change in basis points"],
                        staleness=[],
                        source_lines=["Revenues", "margin lines"],
                        computation="(cur_margin - prior_margin) * 10000",
                        applicable=True,
                        headline=(
                            f"{pretty} changed {bps:+.0f} bps YoY ({cl} vs {pl})"
                        ),
                    )
                )

        # Inventory / AR growth vs revenue growth (annual)
        inv_c = _line_value(_period(balance, ca), "Inventory")
        inv_p = _line_value(_period(balance, pa), "Inventory")
        ar_c = _line_value(_period(balance, ca), "AccountsReceivable")
        ar_p = _line_value(_period(balance, pa), "AccountsReceivable")
        rev_c = _line_value(_period(income, ca), "Revenues")
        rev_p = _line_value(_period(income, pa), "Revenues")
        out.append(
            _growth_pair(
                id="inventory_yoy",
                cur=inv_c,
                prior=inv_p,
                cur_label=cl,
                prior_label=pl,
                pretty="inventory",
                source_lines=["Inventory"],
                comparable=True,
            )
        )
        out.append(
            _growth_pair(
                id="receivables_yoy",
                cur=ar_c,
                prior=ar_p,
                cur_label=cl,
                prior_label=pl,
                pretty="accounts receivable",
                source_lines=["AccountsReceivable"],
                comparable=True,
            )
        )

        # Buyback efficiency — SINGLE annual pair only (never sum FY + Q)
        buyback = _line_value(_period(cash_flow, ca), "StockRepurchases")
        if buyback is not None:
            buyback = abs(buyback)
        sh_c = _line_value(
            _period(income, ca),
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageSharesDiluted",
        )
        sh_p = _line_value(
            _period(income, pa),
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageSharesDiluted",
        )
        if buyback is None or sh_c is None or sh_p is None or sh_p == 0:
            out.append(
                _unavailable(
                    "buyback_dollars_per_pct_point__current_annual_vs_prior_annual",
                    basis_period=f"{cl} vs {pl}",
                    reason="missing buyback spend or diluted share counts",
                    source_lines=[
                        "StockRepurchases",
                        "WeightedAverageNumberOfDilutedSharesOutstanding",
                    ],
                    computation=(
                        "buyback_spend / (100 * (shares_prior - shares_cur) / shares_prior) "
                        "— per annual pair only; never sum periods"
                    ),
                )
            )
        else:
            pct_reduction = (sh_p - sh_c) / sh_p  # fraction, e.g. 0.0117
            pct_points = pct_reduction * 100.0  # e.g. 1.17
            out.append(
                _record(
                    id="share_count_change_pct__current_annual_vs_prior_annual",
                    value=pct_reduction,
                    unit="ratio",
                    basis_period=f"{cl} vs {pl}",
                    qualifiers=[
                        "diluted weighted-average shares",
                        "single annual pair — not summed with quarters",
                    ],
                    staleness=[],
                    source_lines=[
                        "WeightedAverageNumberOfDilutedSharesOutstanding",
                    ],
                    computation="(shares_prior_annual - shares_current_annual) / shares_prior_annual",
                    applicable=True,
                    headline=(
                        f"diluted share count changed {_fmt_pct(pct_reduction)} "
                        f"({sh_p:,.0f} → {sh_c:,.0f}, {pl} → {cl}; "
                        f"single annual pair only)"
                    ),
                    confidence="high",
                )
            )
            if pct_points > 0.01:  # at least 0.01 percentage points reduction
                dpp = buyback / pct_points
                out.append(
                    _record(
                        id="buyback_dollars_per_pct_point__current_annual_vs_prior_annual",
                        value=dpp,
                        unit="USD_per_percentage_point",
                        basis_period=f"{cl} vs {pl}",
                        qualifiers=[
                            "per percentage point of diluted share-count reduction",
                            "single annual pair only — never sum FY + quarter buybacks",
                            f"buyback spend {_fmt_money(buyback)} / {pct_points:.2f} pp",
                        ],
                        staleness=[],
                        source_lines=[
                            "StockRepurchases",
                            "WeightedAverageNumberOfDilutedSharesOutstanding",
                        ],
                        computation=(
                            "abs(StockRepurchases_current_annual) / "
                            "(100 * (shares_prior - shares_cur) / shares_prior)"
                        ),
                        applicable=True,
                        headline=(
                            f"buyback efficiency of {_fmt_money(dpp)} per percentage point "
                            f"of diluted share-count reduction "
                            f"({_fmt_money(buyback)} spend for {pct_points:.2f} pp reduction, "
                            f"{pl} → {cl}; single annual pair only — do not recompute)"
                        ),
                        confidence="high",
                    )
                )
            elif pct_points < -0.01:
                out.append(
                    _record(
                        id="buyback_dollars_per_pct_point__current_annual_vs_prior_annual",
                        value=None,
                        unit="USD_per_percentage_point",
                        basis_period=f"{cl} vs {pl}",
                        qualifiers=["share count increased — efficiency not defined"],
                        staleness=[],
                        source_lines=[
                            "StockRepurchases",
                            "WeightedAverageNumberOfDilutedSharesOutstanding",
                        ],
                        computation="n/a — share count rose",
                        applicable=False,
                        headline=(
                            f"buyback $/pp unavailable — diluted shares rose "
                            f"{_fmt_pct(-pct_reduction)} despite "
                            f"{_fmt_money(buyback)} buybacks ({pl} → {cl})"
                        ),
                        confidence="high",
                    )
                )
            else:
                out.append(
                    _unavailable(
                        "buyback_dollars_per_pct_point__current_annual_vs_prior_annual",
                        basis_period=f"{cl} vs {pl}",
                        reason="share-count change ~0; $/pp undefined",
                        source_lines=["StockRepurchases"],
                        computation="buyback / pct_point_reduction",
                    )
                )

        # Goodwill increment (annual)
        gw_c = _line_value(_period(balance, ca), "Goodwill")
        gw_p = _line_value(_period(balance, pa), "Goodwill")
        assets_c = _line_value(_period(balance, ca), "TotalAssets")
        if gw_c is not None and gw_p is not None:
            delta = gw_c - gw_p
            out.append(
                _record(
                    id="goodwill_increment__current_annual_vs_prior_annual",
                    value=delta,
                    unit="USD",
                    basis_period=f"{cl} vs {pl}",
                    qualifiers=["year-over-year change in goodwill stock"],
                    staleness=[],
                    source_lines=["Goodwill"],
                    computation="goodwill_current_annual - goodwill_prior_annual",
                    applicable=True,
                    headline=(
                        f"goodwill changed by {_fmt_money(delta)} "
                        f"({_fmt_money(gw_p)} → {_fmt_money(gw_c)}, {pl} → {cl})"
                    ),
                )
            )
            if assets_c and assets_c != 0 and delta > 0:
                out.append(
                    _record(
                        id="goodwill_increment_pct_assets__current_annual",
                        value=delta / assets_c,
                        unit="ratio",
                        basis_period=cl,
                        qualifiers=["increment / end-of-period assets — not total goodwill %"],
                        staleness=[],
                        source_lines=["Goodwill", "TotalAssets"],
                        computation="(gw_cur - gw_prior) / total_assets_cur",
                        applicable=True,
                        headline=(
                            f"goodwill increment {_fmt_pct(delta / assets_c)} of "
                            f"end-period assets ({_fmt_money(delta)} / {_fmt_money(assets_c)}, "
                            f"{cl}; this is the increment, not total goodwill)"
                        ),
                    )
                )

    # Quarterly sequential — only if both sides are discrete quarters AND
    # their end dates are adjacent (~60–120 days). SEC rank-1 "prior quarter"
    # is sometimes Q3 when current is Q1 (Q4 rolled into the 10-K) — that is
    # NOT QoQ and must not produce a sequential growth headline.
    cq, pq = "current_quarter", "prior_quarter"
    if cq in metas and pq in metas:
        cl, pl = metas[cq]["label"], metas[pq]["label"]
        comparable = metas[cq].get("comparable_for_qoq") and metas[pq].get(
            "comparable_for_qoq"
        )
        reason = ""
        d_c = _parse_date(metas[cq].get("end"))
        d_p = _parse_date(metas[pq].get("end"))
        if comparable and d_c and d_p:
            gap = abs((d_c - d_p).days)
            if gap < 60 or gap > 120:
                comparable = False
                reason = (
                    f"quarter end dates are {gap}d apart (need ~90d for QoQ); "
                    f"{pl} is not the immediately prior discrete quarter to {cl}"
                )
        elif not comparable:
            reason = (
                "one or both quarter blocks are YTD/cumulative or duration-ambiguous; "
                "QoQ comparison suppressed"
            )
        out.append(
            _growth_pair(
                id="revenue_qoq",
                cur=_line_value(_period(income, cq), "Revenues"),
                prior=_line_value(_period(income, pq), "Revenues"),
                cur_label=cl,
                prior_label=pl,
                pretty="revenue",
                source_lines=["Revenues"],
                comparable=bool(comparable),
                incomparable_reason=reason,
            )
        )

    return out


def _market_metrics(
    live: dict[str, Any],
    income: dict,
    balance: dict,
    cash_flow: dict,
    metas: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    price = _safe_float(live.get("price"))
    mcap = _safe_float(live.get("market_cap"))
    shares_live = _safe_float(live.get("shares_outstanding"))
    as_of = live.get("as_of_utc") or "live snapshot"

    if price is None:
        out.append(
            _unavailable(
                "price",
                basis_period=as_of,
                reason="live price missing",
                source_lines=["live_market.price"],
                computation="yfinance",
            )
        )
    else:
        out.append(
            _record(
                id="price",
                value=price,
                unit="USD_per_share",
                basis_period=str(as_of),
                qualifiers=["live market snapshot"],
                staleness=[],
                source_lines=["live_market.price"],
                computation="yfinance current/regular market price",
                applicable=True,
                headline=f"live price of {_fmt_num(price, 2)} (as of {as_of})",
                confidence="high",
            )
        )

    if mcap is None:
        out.append(
            _unavailable(
                "market_cap",
                basis_period=as_of,
                reason="live market cap missing",
                source_lines=["live_market.market_cap"],
                computation="yfinance",
            )
        )
    else:
        out.append(
            _record(
                id="market_cap",
                value=mcap,
                unit="USD",
                basis_period=str(as_of),
                qualifiers=["live market snapshot"],
                staleness=[],
                source_lines=["live_market.market_cap"],
                computation="yfinance marketCap",
                applicable=True,
                headline=f"market cap of {_fmt_money(mcap)} (as of {as_of})",
                confidence="high",
            )
        )

    # Price × shares reconciliation
    if price is not None and shares_live is not None and shares_live > 0:
        implied = price * shares_live
        out.append(
            _record(
                id="market_cap_price_x_shares",
                value=implied,
                unit="USD",
                basis_period=str(as_of),
                qualifiers=["price × live shares_outstanding"],
                staleness=[],
                source_lines=["live_market.price", "live_market.shares_outstanding"],
                computation="price * shares_outstanding",
                applicable=True,
                headline=(
                    f"price × shares implies {_fmt_money(implied)} "
                    f"({_fmt_num(price, 2)} × {shares_live:,.0f} shares, {as_of})"
                ),
            )
        )
        if mcap is not None and mcap > 0:
            div = abs(implied - mcap) / mcap
            out.append(
                _record(
                    id="market_cap_vs_price_x_shares_divergence",
                    value=div,
                    unit="ratio",
                    basis_period=str(as_of),
                    qualifiers=[
                        "flag if >10% — vintage/share-count mismatch",
                    ],
                    staleness=[],
                    source_lines=["live_market.market_cap", "price", "shares"],
                    computation="abs(price*shares - market_cap) / market_cap",
                    applicable=True,
                    headline=(
                        f"market cap vs price×shares divergence of {_fmt_pct(div)} "
                        f"(mcap {_fmt_money(mcap)} vs implied {_fmt_money(implied)}, {as_of})"
                    ),
                    confidence="high",
                )
            )

    # Trailing P/E from annual diluted EPS
    ca = "current_annual"
    eps = _line_value(
        _period(income, ca),
        "EarningsPerShareDiluted",
        "EPS_Diluted",
    )
    label = metas.get(ca, {}).get("label", ca)
    if price is not None and eps is not None and eps > 0:
        pe = price / eps
        out.append(
            _record(
                id="trailing_pe",
                value=pe,
                unit="ratio",
                basis_period=f"price @ {as_of} / diluted EPS {label}",
                qualifiers=["uses live price and current-annual diluted EPS"],
                staleness=[],
                source_lines=["live_market.price", "EarningsPerShareDiluted"],
                computation="price / diluted_EPS_current_annual",
                applicable=True,
                headline=(
                    f"trailing P/E of {_fmt_num(pe, 1)}x "
                    f"(price {_fmt_num(price, 2)} / diluted EPS {_fmt_num(eps, 2)} from {label})"
                ),
                confidence="high",
            )
        )
    else:
        out.append(
            _unavailable(
                "trailing_pe",
                basis_period=label,
                reason="missing price or non-positive diluted EPS",
                source_lines=["live_market.price", "EarningsPerShareDiluted"],
                computation="price / diluted_EPS",
            )
        )

    # FCF yield
    fcf = _line_value(_period(cash_flow, ca), "FreeCashFlow")
    if fcf is not None and mcap is not None and mcap > 0:
        out.append(
            _record(
                id="fcf_yield",
                value=fcf / mcap,
                unit="ratio",
                basis_period=f"FCF {label} / mcap @ {as_of}",
                qualifiers=["annual FCF / live market cap"],
                staleness=[],
                source_lines=["FreeCashFlow", "live_market.market_cap"],
                computation="current_annual_FCF / market_cap",
                applicable=True,
                headline=(
                    f"FCF yield of {_fmt_pct(fcf / mcap)} "
                    f"(FCF {_fmt_money(fcf)} from {label} / mcap {_fmt_money(mcap)})"
                ),
            )
        )

    # Book value / share
    equity = _line_value(_period(balance, ca), "StockholdersEquity")
    shares = shares_live or _line_value(
        _period(income, ca),
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageSharesDiluted",
    )
    if equity is not None and shares and shares > 0:
        bvps = equity / shares
        out.append(
            _record(
                id="book_value_per_share",
                value=bvps,
                unit="USD_per_share",
                basis_period=label,
                qualifiers=["equity / shares (live shares preferred)"],
                staleness=[],
                source_lines=["StockholdersEquity", "shares"],
                computation="stockholders_equity / shares",
                applicable=True,
                headline=f"book value/share of {_fmt_num(bvps, 2)} ({label})",
            )
        )
        if price is not None and bvps != 0:
            out.append(
                _record(
                    id="price_to_book",
                    value=price / bvps,
                    unit="ratio",
                    basis_period=f"price @ {as_of} / BVPS {label}",
                    qualifiers=[],
                    staleness=[],
                    source_lines=["price", "StockholdersEquity"],
                    computation="price / book_value_per_share",
                    applicable=True,
                    headline=(
                        f"P/B of {_fmt_num(price / bvps, 2)}x "
                        f"(price {_fmt_num(price, 2)} / BVPS {_fmt_num(bvps, 2)})"
                    ),
                )
            )

    # Enterprise value (two bases) using current annual net debt/cash
    net_ex = None
    net_in = None
    # Prefer current_quarter for point-in-time BS if available, else annual
    for pk in ("current_quarter", "current_annual"):
        bal = _period(balance, pk)
        cash = _line_value(bal, "CashAndCashEquivalents")
        st = _line_value(bal, "ShortTermInvestments")
        debt = (_line_value(bal, "ShortTermDebt") or 0.0) + (
            _line_value(bal, "LongTermDebt") or 0.0
        )
        if cash is not None:
            net_ex = cash - debt
            net_in = cash + (st or 0.0) - debt
            blabel = metas.get(pk, {}).get("label", pk)
            break
    else:
        blabel = "n/a"

    if mcap is not None and net_ex is not None:
        # EV = mcap + net_debt = mcap - net_cash
        ev_ex = mcap - net_ex
        out.append(
            _record(
                id="enterprise_value_ex_st",
                value=ev_ex,
                unit="USD",
                basis_period=f"mcap @ {as_of}; net cash ex-ST from {blabel}",
                qualifiers=[
                    "EV = market_cap - net_cash_ex_st_investments",
                    "EXCLUDES ST investments from cash",
                ],
                staleness=[],
                source_lines=["market_cap", "cash", "debt"],
                computation="market_cap - (cash - total_debt)",
                applicable=True,
                headline=(
                    f"enterprise value of {_fmt_money(ev_ex)} "
                    f"(mcap {_fmt_money(mcap)} − net cash ex-ST {_fmt_money(net_ex)}, "
                    f"BS {blabel}; ST investments excluded from cash)"
                ),
            )
        )
    if mcap is not None and net_in is not None:
        ev_in = mcap - net_in
        out.append(
            _record(
                id="enterprise_value_incl_st",
                value=ev_in,
                unit="USD",
                basis_period=f"mcap @ {as_of}; net cash incl-ST from {blabel}",
                qualifiers=[
                    "EV = market_cap - net_cash_incl_st_investments",
                    "INCLUDES ST investments in cash",
                ],
                staleness=[],
                source_lines=["market_cap", "cash", "ST investments", "debt"],
                computation="market_cap - (cash + st_investments - total_debt)",
                applicable=True,
                headline=(
                    f"enterprise value of {_fmt_money(ev_in)} "
                    f"(mcap {_fmt_money(mcap)} − net cash incl-ST {_fmt_money(net_in)}, "
                    f"BS {blabel}; includes ST investments)"
                ),
            )
        )

    # EV/EBITDA rough: use operating income as poor proxy only if no D&A —
    # better leave unavailable than invent. Operating income ≠ EBITDA.
    out.append(
        _record(
            id="ev_to_ebitda",
            value=None,
            unit="ratio",
            basis_period="n/a",
            qualifiers=[],
            staleness=[],
            source_lines=["EBITDA"],
            computation="requires EBITDA (not computed — D&A tags not in statement map)",
            applicable=False,
            headline=(
                "EV/EBITDA unavailable — EBITDA not computed from SEC tags in this "
                "pipeline (no D&A line in concept map); use relative_valuation "
                "yfinance comps table for EV/EBITDA"
            ),
            confidence="none",
        )
    )

    # P/S
    rev = _line_value(_period(income, ca), "Revenues")
    if mcap is not None and rev and rev > 0:
        out.append(
            _record(
                id="price_to_sales",
                value=mcap / rev,
                unit="ratio",
                basis_period=f"mcap @ {as_of} / revenue {label}",
                qualifiers=["annual revenue"],
                staleness=[],
                source_lines=["market_cap", "Revenues"],
                computation="market_cap / current_annual_revenue",
                applicable=True,
                headline=(
                    f"P/S of {_fmt_num(mcap / rev, 2)}x "
                    f"(mcap {_fmt_money(mcap)} / revenue {_fmt_money(rev)} from {label})"
                ),
            )
        )

    # Forward P/E and PEG — not inventable from SEC alone
    out.append(
        _record(
            id="forward_pe",
            value=None,
            unit="ratio",
            basis_period="n/a",
            qualifiers=[],
            staleness=[],
            source_lines=["consensus_eps"],
            computation="requires forward EPS consensus — not in SEC tags",
            applicable=False,
            headline=(
                "forward P/E unavailable from SEC statements — use relative_valuation "
                "yfinance comps table (do not invent forward EPS)"
            ),
            confidence="none",
        )
    )
    out.append(
        _record(
            id="peg",
            value=None,
            unit="ratio",
            basis_period="n/a",
            qualifiers=[],
            staleness=[],
            source_lines=[],
            computation="requires forward P/E and defined growth rate",
            applicable=False,
            headline="PEG unavailable — forward P/E not in canonical SEC metrics",
            confidence="none",
        )
    )

    # Mechanical annualization of current quarter FCF/revenue — explicit only
    cq = "current_quarter"
    if cq in metas and metas[cq].get("comparable_for_qoq"):
        ql = metas[cq]["label"]
        q_rev = _line_value(_period(income, cq), "Revenues")
        q_fcf = _line_value(_period(cash_flow, cq), "FreeCashFlow")
        if q_rev is not None:
            out.append(
                _record(
                    id="revenue_annualized_from_current_quarter",
                    value=q_rev * 4,
                    unit="USD",
                    basis_period=ql,
                    qualifiers=[
                        f"annualized from {ql}",
                        "mechanical run-rate, not guidance",
                    ],
                    staleness=[],
                    source_lines=["Revenues"],
                    computation="current_quarter_revenue * 4",
                    applicable=True,
                    headline=(
                        f"revenue annualized run-rate of {_fmt_money(q_rev * 4)} "
                        f"(annualized from {ql}; mechanical run-rate, not guidance)"
                    ),
                    confidence="moderate",
                )
            )
        if q_fcf is not None:
            out.append(
                _record(
                    id="fcf_annualized_from_current_quarter",
                    value=q_fcf * 4,
                    unit="USD",
                    basis_period=ql,
                    qualifiers=[
                        f"annualized from {ql}",
                        "mechanical run-rate, not guidance",
                    ],
                    staleness=[],
                    source_lines=["FreeCashFlow"],
                    computation="current_quarter_FCF * 4",
                    applicable=True,
                    headline=(
                        f"FCF annualized run-rate of {_fmt_money(q_fcf * 4)} "
                        f"(annualized from {ql}; mechanical run-rate, not guidance)"
                    ),
                    confidence="moderate",
                )
            )
    else:
        out.append(
            _unavailable(
                "revenue_annualized_from_current_quarter",
                basis_period=metas.get(cq, {}).get("label", cq),
                reason="current quarter not safe to annualize (YTD/ambiguous)",
                source_lines=["Revenues"],
                computation="quarterly * 4",
            )
        )

    # 52-week positioning if present
    hi = _safe_float(live.get("fifty_two_week_high"))
    lo = _safe_float(live.get("fifty_two_week_low"))
    if price is not None and hi is not None and hi > 0:
        out.append(
            _record(
                id="pct_below_52w_high",
                value=(hi - price) / hi,
                unit="ratio",
                basis_period=str(as_of),
                qualifiers=[],
                staleness=[],
                source_lines=["price", "fifty_two_week_high"],
                computation="(52w_high - price) / 52w_high",
                applicable=True,
                headline=(
                    f"{_fmt_pct((hi - price) / hi)} below 52-week high "
                    f"(price {_fmt_num(price, 2)} vs high {_fmt_num(hi, 2)})"
                ),
            )
        )
    if price is not None and lo is not None and lo > 0:
        out.append(
            _record(
                id="pct_above_52w_low",
                value=(price - lo) / lo,
                unit="ratio",
                basis_period=str(as_of),
                qualifiers=[],
                staleness=[],
                source_lines=["price", "fifty_two_week_low"],
                computation="(price - 52w_low) / 52w_low",
                applicable=True,
                headline=(
                    f"{_fmt_pct((price - lo) / lo)} above 52-week low "
                    f"(price {_fmt_num(price, 2)} vs low {_fmt_num(lo, 2)})"
                ),
            )
        )

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def compute_canonical_metrics(
    *,
    income_statement: Optional[dict] = None,
    balance_sheet: Optional[dict] = None,
    cash_flow_statement: Optional[dict] = None,
    live_market: Optional[dict] = None,
    ticker: Optional[str] = None,
    sector: Optional[str] = None,
    sic: Optional[str] = None,
) -> dict[str, Any]:
    """Compute the full CanonicalMetrics object from statements + live market.

    Returns a JSON-serializable dict::

        {
          "ticker", "sector", "computed_at_utc",
          "period_labels": { period_key: meta },
          "metrics": [ MetricRecord, ... ],
          "by_id": { id: MetricRecord },
          "headlines": [ str, ... ],  # applicable headlines only
        }
    """
    income = income_statement if isinstance(income_statement, dict) else {}
    balance = balance_sheet if isinstance(balance_sheet, dict) else {}
    cash_flow = cash_flow_statement if isinstance(cash_flow_statement, dict) else {}
    live = _live_market_from_statements(income, balance, cash_flow, live_market)

    metas: dict[str, dict[str, Any]] = {}
    for pk in PERIOD_KEYS:
        # Prefer income spine; fall back to balance / cash flow.
        block = _period(income, pk) or _period(balance, pk) or _period(cash_flow, pk)
        metas[pk] = _period_meta(block, pk)

    metrics: list[dict[str, Any]] = []

    for pk in PERIOD_KEYS:
        meta = metas[pk]
        metrics.extend(_income_level_metrics(income, cash_flow, pk, meta))
        metrics.extend(_margin_metrics(income, cash_flow, pk, meta))
        metrics.extend(_scale_and_bs_metrics(balance, pk, meta, live))

    metrics.extend(_cross_period_metrics(income, balance, cash_flow, metas))
    metrics.extend(_market_metrics(live, income, balance, cash_flow, metas))

    by_id = {m["id"]: m for m in metrics}
    headlines = [m["headline"] for m in metrics if m.get("applicable") and m.get("headline")]
    n_app = sum(1 for m in metrics if m.get("applicable") and m.get("value") is not None)
    n_unavail = sum(1 for m in metrics if not m.get("applicable"))

    base = {
        "ticker": (ticker or "").upper() or None,
        "sector": sector or None,
        "computed_at_utc": _now_utc(),
        "period_labels": metas,
        "metrics": metrics,
        "by_id": by_id,
        "headlines": headlines,
        "summary": {
            "metric_count": len(metrics),
            "applicable_with_value": n_app,
            "unavailable": n_unavail,
        },
    }

    # Phase 2: classify archetype and suppress / annotate metrics before any LLM.
    try:
        from .archetype import apply_archetype_to_metrics, classify_archetype

        industry = None
        if isinstance(live, dict):
            industry = live.get("industry") or live.get("sector")
        clf = classify_archetype(
            ticker=ticker,
            sector=sector,
            income_statement=income,
            balance_sheet=balance,
            cash_flow_statement=cash_flow,
            industry=str(industry) if industry else None,
            sic=sic,
        )
        base["archetype_classification"] = clf
        base["sic"] = sic
        base = apply_archetype_to_metrics(base, clf["archetype"])
    except Exception as exc:  # pragma: no cover — never block metrics on classifier
        base["archetype"] = "general"
        base["archetype_classification"] = {
            "archetype": "general",
            "confidence": "none",
            "reasons": [f"classifier error: {exc}"],
        }
    return base


def format_metrics_for_prompt(canonical: Optional[dict[str, Any]]) -> str:
    """Render canonical metrics for LLM prompts — headlines are the contract."""
    if not canonical or not isinstance(canonical, dict):
        return (
            "=== CANONICAL METRICS (Python engine) ===\n"
            "(not computed — no figures available; do not invent numbers)"
        )
    lines = [
        "=== CANONICAL METRICS (Python engine — source of truth for load-bearing figures) ===",
        f"Ticker: {canonical.get('ticker')} | Sector: {canonical.get('sector')} | "
        f"Computed: {canonical.get('computed_at_utc')}",
    ]
    if canonical.get("archetype"):
        clf = canonical.get("archetype_classification") or {}
        lines.append(
            f"Archetype: {canonical.get('archetype')} "
            f"(confidence={clf.get('confidence', 'n/a')}; "
            f"reasons={'; '.join(clf.get('reasons') or [])})"
        )
    summ = canonical.get("summary") or {}
    lines.append(
        f"Coverage: {summ.get('applicable_with_value', 0)} applicable with values, "
        f"{summ.get('unavailable', 0)} unavailable, "
        f"{summ.get('metric_count', 0)} total records."
    )
    lines.append("")
    lines.append("PERIOD LABELS (duration — do not QoQ YTD/cumulative blocks):")
    for pk, meta in (canonical.get("period_labels") or {}).items():
        if not isinstance(meta, dict):
            continue
        flags = []
        if not meta.get("comparable_for_qoq") and "quarter" in pk:
            flags.append("NOT QoQ-safe")
        for n in meta.get("notes") or []:
            flags.append(n)
        flag_s = f" [{'; '.join(flags)}]" if flags else ""
        lines.append(
            f"  - {pk}: {meta.get('label')} | duration={meta.get('duration')}{flag_s}"
        )

    lines.append("")
    lines.append(
        "HEADLINES (quote verbatim — do not recompute, re-express, or strip qualifiers):"
    )
    # Prefer a stable order: market → annual growth → capital allocation → per-period
    metrics = list(canonical.get("metrics") or [])
    priority_prefixes = (
        "price",
        "market_cap",
        "trailing_pe",
        "fcf_yield",
        "enterprise_value",
        "net_cash",
        "net_debt",
        "revenue_yoy",
        "fcf_yoy",
        "buyback_",
        "share_count",
        "goodwill_increment",
        "gross_margin_yoy",
        "operating_margin_yoy",
        "inventory_yoy",
        "receivables_yoy",
        "pct_below",
        "pct_above",
    )

    def _sort_key(m: dict) -> tuple:
        mid = m.get("id") or ""
        for i, p in enumerate(priority_prefixes):
            if mid.startswith(p):
                return (0, i, mid)
        if m.get("applicable"):
            return (1, 0, mid)
        return (2, 0, mid)

    metrics_sorted = sorted(metrics, key=_sort_key)
    for m in metrics_sorted:
        if not m.get("headline"):
            continue
        # Include all applicable headlines + unavailable that matter for agents
        if m.get("applicable") or m.get("id") in (
            "forward_pe",
            "peg",
            "ev_to_ebitda",
            "buyback_dollars_per_pct_point__current_annual_vs_prior_annual",
        ):
            flag = "✓" if m.get("applicable") and m.get("value") is not None else "·"
            lines.append(f"  {flag} [{m.get('id')}] {m['headline']}")

    lines.append("")
    lines.append(
        "RULE: For any metric listed above, quote its headline string verbatim. "
        "If a metric you need is absent or marked unavailable, say it is unavailable — "
        "do not derive it from raw statement lines."
    )
    return "\n".join(lines)


def get_metric(
    canonical: Optional[dict[str, Any]], metric_id: str
) -> Optional[dict[str, Any]]:
    if not canonical or not isinstance(canonical, dict):
        return None
    by_id = canonical.get("by_id") or {}
    m = by_id.get(metric_id)
    return m if isinstance(m, dict) else None


# Instruction block injected into analytical / synthesis / QC system prompts.
CANONICAL_METRICS_SYSTEM_RULE = """\
CANONICAL METRICS — a Python engine has computed every load-bearing figure for this company
and placed them in the CANONICAL METRICS block (each with an id and a headline).
For ANY metric present there, quote its `headline` string verbatim.
Do not compute, recompute, re-express, annualize, or paraphrase these figures from raw
statement lines. If a metric you want is not in the object, say it is unavailable — do not
derive it yourself. Never strip qualifiers, basis periods, or STALE flags from a headline.
"""
