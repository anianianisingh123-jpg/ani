"""Deterministic valuation helpers for deep-dive agents.

DCF and peer comps are computed in Python from SEC statements + yfinance.
LLM nodes narrate these numbers — they do not invent the core math.
"""

from __future__ import annotations

from typing import Any, Optional


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


def compute_dcf_from_state(state: dict) -> dict[str, Any]:
    return compute_dcf(
        cash_flow=state.get("cash_flow_statement") or {},
        income=state.get("income_statement") or {},
        balance=state.get("balance_sheet") or {},
        live_market=_live_market_from_state(state),
        sector=state.get("sector") or "",
        ticker=state.get("ticker") or "",
    )


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


def fetch_peer_multiples(
    subject_ticker: str,
    *,
    sector: str = "",
    peer_tickers: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Pull live multiples for subject + peers via yfinance."""
    subject = (subject_ticker or "").strip().upper()
    peers = peer_tickers or default_peers_for_sector(sector, subject=subject)
    peers = [p.strip().upper() for p in peers if p and p.strip().upper() != subject]

    subject_row = _row_from_info(subject, _yf_info(subject)) if subject else {}
    peer_rows = [_row_from_info(p, _yf_info(p)) for p in peers]

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

    return {
        "subject": subject_row,
        "peers": peer_rows,
        "peer_medians": medians,
        "relative_read": relative,
        "overall_vs_peers": overall,
        "peer_list": peers,
    }


def format_comps_for_prompt(comps: dict[str, Any]) -> str:
    lines = [
        "=== DETERMINISTIC PEER COMPS (yfinance — source of truth for multiples) ===",
        f"Peers used: {', '.join(comps.get('peer_list') or [])}",
        f"Overall vs peers: {comps.get('overall_vs_peers')}",
    ]
    sub = comps.get("subject") or {}
    lines.append(
        f"Subject {sub.get('ticker')}: price={_fmt_price(sub.get('price'))} "
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
