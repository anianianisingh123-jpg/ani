"""Live data tools for the sector research agents.

Sources of truth:

  1. SEC EDGAR XBRL Company Facts — full financial statements
  2. yfinance                       — live price / market cap + free options/insider proxies
  3. Tavily web search              — narrative context SEC tags can't give
  4. SEC Form 4 (submissions index) — free insider filing alerts (no paid vendors)

These are plain Python helpers (not LangChain tool objects). Nodes call them
before prompting the LLM so the model is grounded in fresh external data.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv

from .cost import record_sec_call, record_tavily_search

# Load both package-local and repo-root .env files (either is fine).
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_PKG_DIR)
load_dotenv(os.path.join(_PKG_DIR, ".env"))
load_dotenv(os.path.join(_REPO_ROOT, ".env"))

_CACHE_DIR = os.path.join(_PKG_DIR, ".cache")
_TICKERS_CACHE = os.path.join(_CACHE_DIR, "company_tickers.json")
_SIC_CACHE_DIR = os.path.join(_CACHE_DIR, "submissions")
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# Conservative spacing between SEC requests (~5 req/s max; SEC limit is ~10).
_SEC_MIN_INTERVAL_SEC = 0.25
_last_sec_request_at = 0.0


def _strip_env(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.strip().strip('"').strip("'")


def _tavily_key() -> Optional[str]:
    return _strip_env(os.environ.get("TAVILY_API_KEY"))


def _sec_user_agent() -> str:
    """SEC-compliant User-Agent — required or EDGAR blocks the request.

    Format expected by SEC: application name + contact email, e.g.
    ``Ani Singh ani-research-tool contact@example.com``.
    Set ``SEC_EDGAR_USER_AGENT`` in .env — do not leave the default in prod.
    """
    ua = _strip_env(os.environ.get("SEC_EDGAR_USER_AGENT"))
    if ua:
        return ua
    return "Ani Singh ani-research-tool contact: ani.research@example.com"


def _sec_rate_limit() -> None:
    global _last_sec_request_at
    now = time.monotonic()
    wait = _SEC_MIN_INTERVAL_SEC - (now - _last_sec_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_sec_request_at = time.monotonic()


def _http_get_json(url: str, *, headers: Optional[dict] = None, timeout: int = 60) -> Any:
    """GET JSON with SEC-friendly headers. Raises on HTTP/parse errors."""
    req_headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": _sec_user_agent(),
    }
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        body = raw.decode("utf-8")
    # Count SEC (and any other) EDGAR HTTP hits for rate-limit visibility.
    if "sec.gov" in (url or "").lower():
        record_sec_call(1)
    return json.loads(body)


# ─────────────────────────────────────────────────────────────────────────────
# Tavily
# ─────────────────────────────────────────────────────────────────────────────

def web_search(
    query: str,
    *,
    max_results: int = 6,
    search_depth: str = "advanced",
    topic: str = "finance",
    include_answer: bool = True,
) -> dict[str, Any]:
    """Run a Tavily search and return a structured result dict."""
    key = _tavily_key()
    if not key:
        return {
            "query": query,
            "answer": None,
            "results": [],
            "error": (
                "TAVILY_API_KEY is not set. Add it to .env "
                "(repo root or mas_sector_system/.env)."
            ),
        }

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=key)
        raw = client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            topic=topic,
            include_answer=include_answer,
        )
        record_tavily_search(1)
    except Exception as exc:
        return {
            "query": query,
            "answer": None,
            "results": [],
            "error": f"Tavily search failed: {exc}",
        }

    hits = []
    for r in raw.get("results") or []:
        hits.append(
            {
                "title": r.get("title") or "",
                "url": r.get("url") or "",
                "content": r.get("content") or "",
                "score": r.get("score"),
                "published_date": r.get("published_date"),
            }
        )

    return {
        "query": query,
        "answer": raw.get("answer"),
        "results": hits,
        "error": None,
    }


def format_search_for_prompt(search: dict[str, Any]) -> str:
    """Render a web_search() result as readable text for an LLM prompt."""
    lines: list[str] = [f"### Search: {search.get('query', '')}"]

    if search.get("error"):
        lines.append(f"ERROR: {search['error']}")
        return "\n".join(lines)

    if search.get("answer"):
        lines.append(f"Tavily summary: {search['answer']}")

    results = search.get("results") or []
    if not results:
        lines.append("(no results)")
        return "\n".join(lines)

    for i, r in enumerate(results, 1):
        date = r.get("published_date") or "n/d"
        lines.append(
            f"\n[{i}] {r.get('title', '')}  ({date})\n"
            f"    URL: {r.get('url', '')}\n"
            f"    {r.get('content', '')}"
        )
    return "\n".join(lines)


def multi_search(queries: list[str], **kwargs: Any) -> str:
    """Run several Tavily queries and concatenate formatted results."""
    blocks = [format_search_for_prompt(web_search(q, **kwargs)) for q in queries]
    return "\n\n".join(blocks)


def _relevance_tokens(*, ticker: Optional[str], entity_name: Optional[str] = None) -> list[str]:
    """Lowercased tokens used to check whether search text is on-target."""
    # Common legal / brand names when entity_name was not threaded through.
    _TICKER_ALIASES: dict[str, tuple[str, ...]] = {
        "NVDA": ("nvidia",),
        "AAPL": ("apple",),
        "MSFT": ("microsoft",),
        "GOOGL": ("alphabet", "google"),
        "GOOG": ("alphabet", "google"),
        "AMZN": ("amazon",),
        "META": ("meta", "facebook"),
        "AVGO": ("broadcom",),
        "TSM": ("tsmc", "taiwan semiconductor"),
        "QCOM": ("qualcomm",),
        "AMD": ("advanced micro devices",),
        "INTC": ("intel",),
        "JPM": ("jpmorgan", "jp morgan"),
    }
    tokens: list[str] = []
    if ticker and str(ticker).strip():
        t_up = str(ticker).strip().upper()
        tokens.append(t_up)
        tokens.append(str(ticker).strip().lower())
        for alias in _TICKER_ALIASES.get(t_up, ()):
            tokens.append(alias.lower())
    if entity_name and str(entity_name).strip():
        name = str(entity_name).strip()
        tokens.append(name.lower())
        # First significant word (e.g. "NVIDIA" from "NVIDIA CORP") helps
        # when Tavily titles omit the full legal name.
        first = name.split()[0].lower()
        if len(first) >= 3:
            tokens.append(first)
    # Dedupe, preserve order.
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def check_search_relevance(
    text: str,
    *,
    ticker: Optional[str],
    entity_name: Optional[str] = None,
    label: str = "search",
) -> bool:
    """Return True if ticker/entity appears in search text; log a warning if not.

    Used so a failed/irrelevant Tavily retrieval is visible at run time rather
    than only later in the QC report. Generic macro queries (Fed, rates) may
    legitimately omit the ticker — callers should only run this on digests that
    were supposed to be company-anchored.
    """
    tokens = _relevance_tokens(ticker=ticker, entity_name=entity_name)
    if not tokens or not (text or "").strip():
        return True  # nothing to check
    lower = text.lower()
    upper = text.upper()
    hit = False
    for tok in tokens:
        if tok.isupper() and len(tok) <= 5:
            # Ticker: word-ish presence (avoid matching random substrings in URLs
            # only — still accept any occurrence of the symbol).
            if tok in upper:
                hit = True
                break
        elif tok in lower:
            hit = True
            break
    if not hit:
        print(
            f"[{label}] WARNING: search digest has no mention of "
            f"ticker={ticker!r} / entity={entity_name!r} — results may be "
            f"irrelevant (chars={len(text)})",
            flush=True,
        )
    return hit


def clip_search_digest(text: str, max_chars: int) -> str:
    """Truncate a multi-search digest at a result boundary when possible.

    Avoids the ``https://finance.y`` mid-URL cut that poisons macro_context
    when a hard ``text[:N]`` slice lands inside an entry.
    """
    if not text or len(text) <= max_chars:
        return text or ""
    cut = text[:max_chars]
    # Prefer breaking before a numbered result header: "\n[N] "
    last_header = -1
    for i, ch in enumerate(cut):
        if ch == "\n" and i + 1 < len(cut) and cut[i + 1] == "[":
            # rough match for "\n[12] "
            j = i + 2
            while j < len(cut) and cut[j].isdigit():
                j += 1
            if j < len(cut) and cut[j] == "]":
                last_header = i
    if last_header > max_chars // 2:
        return cut[:last_header].rstrip() + "\n\n[... truncated at result boundary ...]"
    # Fall back to last newline.
    nl = cut.rfind("\n")
    if nl > max_chars // 2:
        return cut[:nl].rstrip() + "\n\n[... truncated ...]"
    return cut.rstrip() + "…"


# ─────────────────────────────────────────────────────────────────────────────
# SEC EDGAR — CIK lookup + Company Facts
# ─────────────────────────────────────────────────────────────────────────────

def _load_ticker_map(*, force_refresh: bool = False) -> dict[str, str]:
    """Return {TICKER: zero-padded-10-digit-CIK} from SEC company_tickers.json.

    Caches the raw JSON under mas_sector_system/.cache/ (refreshed if missing
    or older than 7 days).
    """
    os.makedirs(_CACHE_DIR, exist_ok=True)
    refresh = force_refresh or not os.path.exists(_TICKERS_CACHE)
    if not refresh:
        age = time.time() - os.path.getmtime(_TICKERS_CACHE)
        if age > 7 * 24 * 3600:
            refresh = True

    if refresh:
        _sec_rate_limit()
        raw = _http_get_json(_TICKERS_URL)
        with open(_TICKERS_CACHE, "w", encoding="utf-8") as f:
            json.dump(raw, f)
    else:
        with open(_TICKERS_CACHE, "r", encoding="utf-8") as f:
            raw = json.load(f)

    mapping: dict[str, str] = {}
    # File shape: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
    for entry in raw.values() if isinstance(raw, dict) else raw:
        if not isinstance(entry, dict):
            continue
        ticker = (entry.get("ticker") or "").upper().strip()
        cik_raw = entry.get("cik_str")
        if not ticker or cik_raw is None:
            continue
        mapping[ticker] = str(cik_raw).zfill(10)
    return mapping


def get_cik_for_ticker(ticker: str) -> str:
    """Look up the 10-digit zero-padded CIK for a ticker.

    Raises ValueError if the ticker is not found in the SEC ticker map.
    """
    if not ticker or not str(ticker).strip():
        raise ValueError("Empty ticker — cannot look up CIK.")
    symbol = ticker.strip().upper()
    mapping = _load_ticker_map()
    cik = mapping.get(symbol)
    if not cik:
        # One forced refresh in case the cache is stale for a recent IPO.
        mapping = _load_ticker_map(force_refresh=True)
        cik = mapping.get(symbol)
    if not cik:
        raise ValueError(f"CIK not found for ticker {symbol!r} in SEC company_tickers.json")
    return cik


def fetch_sec_company_facts(cik: str) -> dict[str, Any]:
    """Fetch the full XBRL companyfacts JSON for a CIK from SEC EDGAR."""
    padded = str(cik).zfill(10)
    url = _COMPANY_FACTS_URL.format(cik=padded)
    _sec_rate_limit()
    return _http_get_json(url)


def fetch_entity_metadata(cik: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """Fetch SIC / entity name from SEC submissions JSON (cached under .cache/submissions)."""
    padded = str(cik).zfill(10)
    os.makedirs(_SIC_CACHE_DIR, exist_ok=True)
    path = os.path.join(_SIC_CACHE_DIR, f"CIK{padded}.json")
    refresh = force_refresh or not os.path.exists(path)
    if not refresh:
        age = time.time() - os.path.getmtime(path)
        if age > 30 * 24 * 3600:
            refresh = True
    if refresh:
        _sec_rate_limit()
        url = _SUBMISSIONS_URL.format(cik=padded)
        try:
            raw = _http_get_json(url)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(raw, f)
        except Exception as exc:
            return {"cik": padded, "sic": None, "error": str(exc)}
    else:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

    sic = raw.get("sic") or raw.get("sicCode")
    # submissions may nest tickers
    tickers = []
    for t in raw.get("tickers") or []:
        if isinstance(t, str):
            tickers.append(t.upper())
    return {
        "cik": padded,
        "sic": str(sic).zfill(4) if sic is not None else None,
        "sic_description": raw.get("sicDescription"),
        "name": raw.get("name"),
        "tickers": tickers,
        "exchanges": raw.get("exchanges"),
        "error": None,
    }


# Concept aliases: primary key first, then fallbacks used across filers.
# Prefer concept_maps.GENERAL_* ; these remain as the general default import target.
from .concept_maps import maps_for_archetype  # noqa: E402

_INCOME_CONCEPTS: dict[str, list[str]] = {
    "Revenues": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "TurnoverRevenue",
    ],
    "CostOfRevenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
        "CostOfServices",
    ],
    "GrossProfit": ["GrossProfit"],
    "ResearchAndDevelopmentExpense": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    "SellingGeneralAndAdministrativeExpense": [
        "SellingGeneralAndAdministrativeExpense",
        "SellingAndMarketingExpense",
        "GeneralAndAdministrativeExpense",
    ],
    "OperatingExpenses": [
        "OperatingExpenses",
        "CostsAndExpenses",
    ],
    "OperatingIncomeLoss": [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ],
    "InterestExpense": [
        "InterestExpense",
        "InterestExpenseDebt",
        "InterestAndDebtExpense",
    ],
    "IncomeTaxExpenseBenefit": [
        "IncomeTaxExpenseBenefit",
        "IncomeTaxExpenseBenefitContinuingOperations",
    ],
    "NetIncomeLoss": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "EarningsPerShareBasic": ["EarningsPerShareBasic"],
    "EarningsPerShareDiluted": ["EarningsPerShareDiluted"],
    "WeightedAverageNumberOfSharesOutstandingBasic": [
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    ],
    "WeightedAverageNumberOfDilutedSharesOutstanding": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ],
}

_BALANCE_CONCEPTS: dict[str, list[str]] = {
    "CashAndCashEquivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
        "Cash",
    ],
    "ShortTermInvestments": [
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesCurrent",
    ],
    "AccountsReceivable": [
        "AccountsReceivableNetCurrent",
        "AccountsReceivableNet",
        "ReceivablesNetCurrent",
    ],
    "Inventory": [
        "InventoryNet",
        "InventoryFinishedGoodsNetOfReserves",
    ],
    "TotalCurrentAssets": ["AssetsCurrent"],
    "PropertyPlantAndEquipment": [
        "PropertyPlantAndEquipmentNet",
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
    ],
    "Goodwill": ["Goodwill"],
    "IntangibleAssets": [
        "IntangibleAssetsNetExcludingGoodwill",
        "FiniteLivedIntangibleAssetsNet",
    ],
    "TotalAssets": ["Assets"],
    "AccountsPayable": [
        "AccountsPayableCurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
    ],
    "ShortTermDebt": [
        "ShortTermBorrowings",
        "LongTermDebtCurrent",
        "DebtCurrent",
        "CommercialPaper",
    ],
    "TotalCurrentLiabilities": ["LiabilitiesCurrent"],
    "LongTermDebt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
    ],
    "TotalLiabilities": [
        "Liabilities",
        "LiabilitiesAndStockholdersEquity",
    ],
    "StockholdersEquity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "PartnersCapital",
    ],
    "SharesOutstanding": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
}

_CASHFLOW_CONCEPTS: dict[str, list[str]] = {
    "NetCashFromOperatingActivities": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "CapitalExpenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "CapitalExpendituresIncurredButNotYetPaid",
    ],
    "NetCashFromInvestingActivities": [
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
    ],
    "DividendsPaid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfOrdinaryDividends",
    ],
    "StockRepurchases": [
        "PaymentsForRepurchaseOfCommonStock",
        "PaymentsForRepurchaseOfEquity",
    ],
    "DebtIssuance": [
        "ProceedsFromIssuanceOfLongTermDebt",
        "ProceedsFromDebtNetOfIssuanceCosts",
        "ProceedsFromIssuanceOfDebt",
    ],
    "DebtRepayment": [
        "RepaymentsOfLongTermDebt",
        "RepaymentsOfDebt",
        "RepaymentsOfLongTermDebtAndCapitalSecurities",
    ],
    "NetCashFromFinancingActivities": [
        "NetCashProvidedByUsedInFinancingActivities",
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
    ],
}


def _usd_facts_for_concept(facts: dict, concept_names: list[str]) -> list[dict]:
    """Return USD (or unit) observations merged across concept aliases.

    Filers often migrate tags over time (e.g. ``Revenues`` →
    ``RevenueFromContractWithCustomerExcludingAssessedTax``). Taking only the
    first matching alias can lock onto a stale series, so we merge all
    aliases and let period selection pick the most recent end date.
    """
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    # Also check dei for entity-level share counts occasionally parked there.
    dei = (facts.get("facts") or {}).get("dei") or {}
    merged: list[dict] = []
    unit_preference = ("USD", "USD/shares", "shares", "pure")

    for name in concept_names:
        node = us_gaap.get(name) or dei.get(name)
        if not node:
            continue
        units = node.get("units") or {}
        for unit_key in unit_preference:
            series = units.get(unit_key)
            if series:
                for obs in series:
                    # Tag source concept so debugging is possible without noise.
                    item = dict(obs)
                    item.setdefault("_concept", name)
                    item.setdefault("_unit", unit_key)
                    merged.append(item)
                break  # one unit family per concept name
    return merged


def _pick_period(
    series: list[dict],
    *,
    annual: bool,
    rank: int = 0,
) -> Optional[dict]:
    """Pick the Nth most recent annual (FY 10-K) or quarterly (10-Q) point.

    rank=0 → most recent, rank=1 → prior period of same type.
    """
    if not series:
        return None

    filtered: list[dict] = []
    for obs in series:
        form = (obs.get("form") or "").upper()
        fp = (obs.get("fp") or "").upper()
        if annual:
            # Prefer 10-K / FY frames; also accept fp == FY without form.
            if form in ("10-K", "10-K/A") or fp == "FY":
                filtered.append(obs)
        else:
            # Quarters: 10-Q or fp in Q1–Q3 (Q4 often rolled into 10-K).
            if form in ("10-Q", "10-Q/A") or fp in ("Q1", "Q2", "Q3", "Q4"):
                # Skip full-year frames that sometimes appear under Q tags.
                if fp == "FY":
                    continue
                filtered.append(obs)

    if not filtered:
        return None

    # Sort by end date descending; break ties with filed date.
    def _key(o: dict) -> tuple:
        return (o.get("end") or "", o.get("filed") or "", o.get("fy") or 0)

    filtered.sort(key=_key, reverse=True)

    # Deduplicate by (end, fp) keeping first (most recently filed).
    seen: set[tuple] = set()
    unique: list[dict] = []
    for o in filtered:
        sig = (o.get("end"), o.get("fp"), o.get("fy"))
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(o)

    if rank >= len(unique):
        return None
    return unique[rank]


def _null_line(note: str) -> dict[str, Any]:
    return {"value": None, "note": note}


def _extract_line(
    facts: dict,
    concept_aliases: list[str],
    *,
    annual: bool,
    rank: int,
) -> dict[str, Any]:
    series = _usd_facts_for_concept(facts, concept_aliases)
    if not series:
        return _null_line(f"concept not tagged (tried: {', '.join(concept_aliases[:3])}…)")

    obs = _pick_period(series, annual=annual, rank=rank)
    if not obs:
        kind = "annual" if annual else "quarterly"
        which = "current" if rank == 0 else "prior"
        return _null_line(f"no {which} {kind} observation found")

    return {
        "value": obs.get("val"),
        "end": obs.get("end"),
        "fy": obs.get("fy"),
        "fp": obs.get("fp"),
        "form": obs.get("form"),
        "filed": obs.get("filed"),
        "frame": obs.get("frame"),
        "note": None,
    }


def _extract_statement_block(
    facts: dict,
    concept_map: dict[str, list[str]],
) -> dict[str, Any]:
    """Build current/prior annual + quarterly dicts for a statement family."""
    block: dict[str, Any] = {
        "current_annual": {},
        "prior_annual": {},
        "current_quarter": {},
        "prior_quarter": {},
    }
    for label, aliases in concept_map.items():
        block["current_annual"][label] = _extract_line(
            facts, aliases, annual=True, rank=0
        )
        block["prior_annual"][label] = _extract_line(
            facts, aliases, annual=True, rank=1
        )
        block["current_quarter"][label] = _extract_line(
            facts, aliases, annual=False, rank=0
        )
        block["prior_quarter"][label] = _extract_line(
            facts, aliases, annual=False, rank=1
        )
    return block


def _compute_fcf(cash_flow: dict[str, Any]) -> None:
    """Add FreeCashFlow = Operating CF − CapEx for each period sub-block."""
    for period_key in (
        "current_annual",
        "prior_annual",
        "current_quarter",
        "prior_quarter",
    ):
        period = cash_flow.get(period_key) or {}
        ocf = (period.get("NetCashFromOperatingActivities") or {}).get("value")
        capex = (period.get("CapitalExpenditures") or {}).get("value")
        if ocf is None or capex is None:
            period["FreeCashFlow"] = _null_line(
                "cannot compute FCF — missing Operating CF and/or CapEx"
            )
        else:
            # CapEx is usually reported as a positive payment; FCF = OCF − |CapEx|
            period["FreeCashFlow"] = {
                "value": float(ocf) - abs(float(capex)),
                "end": (period.get("NetCashFromOperatingActivities") or {}).get("end"),
                "fy": (period.get("NetCashFromOperatingActivities") or {}).get("fy"),
                "fp": (period.get("NetCashFromOperatingActivities") or {}).get("fp"),
                "form": (period.get("NetCashFromOperatingActivities") or {}).get("form"),
                "filed": (period.get("NetCashFromOperatingActivities") or {}).get("filed"),
                "note": "computed as NetCashFromOperatingActivities − |CapitalExpenditures|",
            }
        cash_flow[period_key] = period


def _friendly_income_aliases(income: dict[str, Any]) -> None:
    for period_key in list(income.keys()):
        p = income[period_key]
        if not isinstance(p, dict):
            continue
        if "IncomeTaxExpenseBenefit" in p and "IncomeTaxExpense" not in p:
            p["IncomeTaxExpense"] = p["IncomeTaxExpenseBenefit"]
        if "EarningsPerShareBasic" in p:
            p["EPS_Basic"] = p["EarningsPerShareBasic"]
        if "EarningsPerShareDiluted" in p:
            p["EPS_Diluted"] = p["EarningsPerShareDiluted"]
        if "WeightedAverageNumberOfSharesOutstandingBasic" in p:
            p["WeightedAverageSharesBasic"] = p[
                "WeightedAverageNumberOfSharesOutstandingBasic"
            ]
        if "WeightedAverageNumberOfDilutedSharesOutstanding" in p:
            p["WeightedAverageSharesDiluted"] = p[
                "WeightedAverageNumberOfDilutedSharesOutstanding"
            ]
        if "ResearchAndDevelopmentExpense" in p:
            p["RD_Expense"] = p["ResearchAndDevelopmentExpense"]
        if "SellingGeneralAndAdministrativeExpense" in p:
            p["SGA_Expense"] = p["SellingGeneralAndAdministrativeExpense"]


def _cell_val(cell: Any) -> Optional[float]:
    if isinstance(cell, dict) and cell.get("value") is not None:
        try:
            return float(cell["value"])
        except (TypeError, ValueError):
            return None
    return None


def _derive_archetype_lines(
    income: dict[str, Any],
    balance: dict[str, Any],
    cash_flow: dict[str, Any],
    archetype: str,
) -> dict[str, Any]:
    """Post-extract derived lines (NII, bank revenues, NAREIT FFO, etc.)."""
    notes: list[str] = []
    arch = archetype or "general"

    for pk in ("current_annual", "prior_annual", "current_quarter", "prior_quarter"):
        inc = income.get(pk) if isinstance(income.get(pk), dict) else {}
        bal = balance.get(pk) if isinstance(balance.get(pk), dict) else {}
        cf = cash_flow.get(pk) if isinstance(cash_flow.get(pk), dict) else {}

        if arch == "bank_lender":
            ii = _cell_val(inc.get("InterestIncome"))
            ie = _cell_val(inc.get("InterestExpenseBank") or inc.get("InterestExpense"))
            nii_tag = _cell_val(inc.get("NetInterestIncome"))
            if nii_tag is None and ii is not None and ie is not None:
                # NII = interest income − interest expense
                template = inc.get("InterestIncome") or {}
                inc["NetInterestIncome"] = {
                    "value": ii - abs(ie),
                    "end": template.get("end"),
                    "fy": template.get("fy"),
                    "fp": template.get("fp"),
                    "form": template.get("form"),
                    "filed": template.get("filed"),
                    "note": "derived: InterestIncome − |InterestExpense|",
                }
                notes.append(f"{pk}: derived NetInterestIncome")
            nii = _cell_val(inc.get("NetInterestIncome"))
            nonii = _cell_val(inc.get("NoninterestIncome"))
            # Synthetic Revenues for metrics that expect it
            if nii is not None or nonii is not None:
                total = (nii or 0.0) + (nonii or 0.0)
                template = (
                    inc.get("NetInterestIncome")
                    or inc.get("InterestIncome")
                    or inc.get("NoninterestIncome")
                    or {}
                )
                if _cell_val(inc.get("Revenues")) is None or arch == "bank_lender":
                    inc["Revenues"] = {
                        "value": total,
                        "end": template.get("end"),
                        "fy": template.get("fy"),
                        "fp": template.get("fp"),
                        "form": template.get("form"),
                        "filed": template.get("filed"),
                        "note": "derived bank revenues: NII + NoninterestIncome",
                    }
                    notes.append(f"{pk}: derived bank Revenues = NII + NoninterestIncome")

        if arch == "insurance":
            prem = _cell_val(inc.get("PremiumsEarned"))
            inv = _cell_val(inc.get("NetInvestmentIncome"))
            if prem is not None or inv is not None:
                total = (prem or 0.0) + (inv or 0.0)
                template = inc.get("PremiumsEarned") or inc.get("NetInvestmentIncome") or {}
                if _cell_val(inc.get("Revenues")) is None:
                    inc["Revenues"] = {
                        "value": total,
                        "end": template.get("end"),
                        "fy": template.get("fy"),
                        "fp": template.get("fp"),
                        "form": template.get("form"),
                        "filed": template.get("filed"),
                        "note": "derived insurer revenues: PremiumsEarned + NetInvestmentIncome",
                    }
                    notes.append(f"{pk}: derived insurance Revenues")
            # Combined ratio components when present
            claims = _cell_val(inc.get("PolicyholderBenefits"))
            if prem and prem != 0 and claims is not None:
                # loss ratio only (expense ratio needs underwriting expense)
                inc["LossRatio"] = {
                    "value": abs(claims) / prem,
                    "note": "derived: |PolicyholderBenefits| / PremiumsEarned",
                    "end": (inc.get("PremiumsEarned") or {}).get("end"),
                    "fy": (inc.get("PremiumsEarned") or {}).get("fy"),
                    "fp": (inc.get("PremiumsEarned") or {}).get("fp"),
                    "form": (inc.get("PremiumsEarned") or {}).get("form"),
                    "filed": (inc.get("PremiumsEarned") or {}).get("filed"),
                }

        if arch in ("equity_reit", "reit_real_estate"):
            # NAREIT FFO ≈ NI + RE depreciation − gains on property sales
            ni = _cell_val(inc.get("NetIncomeLoss"))
            da = _cell_val(inc.get("DepreciationRealEstate")) or _cell_val(
                cf.get("DepreciationRealEstateCF")
            )
            gain = _cell_val(inc.get("GainOnSaleOfRealEstate"))
            if ni is not None and da is not None:
                ffo = ni + abs(da) - (gain or 0.0)
                template = inc.get("NetIncomeLoss") or {}
                inc["FFO"] = {
                    "value": ffo,
                    "end": template.get("end"),
                    "fy": template.get("fy"),
                    "fp": template.get("fp"),
                    "form": template.get("form"),
                    "filed": template.get("filed"),
                    "note": (
                        "derived NAREIT-style FFO ≈ NI + |RE D&A| − property gains "
                        "(approximate; confirm vs company supplement)"
                    ),
                }
                notes.append(f"{pk}: derived FFO from NI + D&A − gains")

        income[pk] = inc
        balance[pk] = bal
        cash_flow[pk] = cf

    return {"derived_notes": notes}


def extract_statements_from_company_facts(
    facts: dict,
    *,
    archetype: str = "general",
) -> dict[str, Any]:
    """Parse raw companyfacts JSON into income / balance / cash-flow dicts.

    Uses archetype-specific XBRL concept maps so banks/REITs/insurers resolve
    core lines. Missing concepts are explicitly null with a note.
    """
    entity = facts.get("entityName")
    cik = facts.get("cik")
    maps = maps_for_archetype(archetype)

    income = _extract_statement_block(facts, maps["income"])
    _friendly_income_aliases(income)
    balance = _extract_statement_block(facts, maps["balance"])
    cash_flow = _extract_statement_block(facts, maps["cashflow"])
    _compute_fcf(cash_flow)
    derived = _derive_archetype_lines(income, balance, cash_flow, archetype)

    return {
        "entity_name": entity,
        "cik": str(cik).zfill(10) if cik is not None else None,
        "income_statement": income,
        "balance_sheet": balance,
        "cash_flow_statement": cash_flow,
        "extraction_archetype": archetype,
        "derived_notes": derived.get("derived_notes") or [],
        "incomplete": False,
        "error": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Live market (price only — no pre-baked ratios)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_live_market_snapshot(ticker: str) -> dict[str, Any]:
    """Pull live price + market cap via yfinance. No derived valuation ratios."""
    if not ticker:
        return {"error": "No ticker provided."}

    symbol = ticker.strip().upper()
    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        info = t.info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            hist = t.history(period="5d")
            if hist is not None and not hist.empty:
                price = float(hist["Close"].iloc[-1])

        return {
            "ticker": symbol,
            "as_of_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "currency": info.get("currency"),
            "price": price,
            "market_cap": info.get("marketCap"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "error": None,
        }
    except Exception as exc:
        return {"ticker": symbol, "error": f"yfinance fetch failed: {exc}"}


# ─────────────────────────────────────────────────────────────────────────────
# Options flow proxy (free — yfinance option chains; not paid flow vendors)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_options_flow(ticker: str, *, max_expiries: int = 4) -> dict[str, Any]:
    """Put/call volume & open-interest ratios from yfinance option chains.

    This is a **free proxy** for options positioning — not proprietary unusual
    options flow (no Unusual Whales / paid tape). Near-dated expiries only
    (first ``max_expiries`` listed) to bound latency.

    Returns a dict with ratio fields, raw totals, notes, and error if any.
    """
    symbol = (ticker or "").strip().upper()
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not symbol:
        return {
            "ticker": None,
            "as_of_utc": as_of,
            "source": "yfinance_option_chain",
            "error": "No ticker provided.",
            "applicable": False,
        }
    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        expiries = list(t.options or [])
        if not expiries:
            return {
                "ticker": symbol,
                "as_of_utc": as_of,
                "source": "yfinance_option_chain",
                "error": "No option expiries listed (yfinance).",
                "applicable": False,
                "expiries_used": [],
            }

        use = expiries[: max(1, int(max_expiries))]
        call_vol = put_vol = 0.0
        call_oi = put_oi = 0.0
        n_calls = n_puts = 0
        per_expiry: list[dict[str, Any]] = []

        for exp in use:
            try:
                chain = t.option_chain(exp)
            except Exception as exc:
                per_expiry.append({"expiry": exp, "error": str(exc)})
                continue
            calls = getattr(chain, "calls", None)
            puts = getattr(chain, "puts", None)
            cv = float(calls["volume"].fillna(0).sum()) if calls is not None and "volume" in calls else 0.0
            pv = float(puts["volume"].fillna(0).sum()) if puts is not None and "volume" in puts else 0.0
            co = float(calls["openInterest"].fillna(0).sum()) if calls is not None and "openInterest" in calls else 0.0
            po = float(puts["openInterest"].fillna(0).sum()) if puts is not None and "openInterest" in puts else 0.0
            call_vol += cv
            put_vol += pv
            call_oi += co
            put_oi += po
            if calls is not None:
                n_calls += len(calls)
            if puts is not None:
                n_puts += len(puts)
            per_expiry.append(
                {
                    "expiry": exp,
                    "call_volume": cv,
                    "put_volume": pv,
                    "call_oi": co,
                    "put_oi": po,
                }
            )

        total_vol = call_vol + put_vol
        total_oi = call_oi + put_oi
        pc_vol = (put_vol / call_vol) if call_vol > 0 else None
        pc_oi = (put_oi / call_oi) if call_oi > 0 else None
        # Crude "unusual" flag: high total option volume vs OI (turnover).
        vol_to_oi = (total_vol / total_oi) if total_oi > 0 else None
        unusual = bool(vol_to_oi is not None and vol_to_oi >= 0.5 and total_vol >= 5000)

        return {
            "ticker": symbol,
            "as_of_utc": as_of,
            "source": "yfinance_option_chain",
            "applicable": total_vol > 0 or total_oi > 0,
            "error": None,
            "expiries_listed": expiries[:12],
            "expiries_used": use,
            "call_volume": call_vol,
            "put_volume": put_vol,
            "call_open_interest": call_oi,
            "put_open_interest": put_oi,
            "put_call_volume_ratio": pc_vol,
            "put_call_oi_ratio": pc_oi,
            "option_volume_to_oi": vol_to_oi,
            "unusual_volume_flag": unusual,
            "n_call_contracts": n_calls,
            "n_put_contracts": n_puts,
            "per_expiry": per_expiry,
            "notes": [
                "Free yfinance chain aggregate — not paid order-flow tape.",
                f"Aggregated across {len(use)} nearest listed expiries.",
                "unusual_volume_flag = volume/OI >= 0.5 and total option volume >= 5000 "
                "(heuristic only).",
            ],
        }
    except Exception as exc:
        return {
            "ticker": symbol,
            "as_of_utc": as_of,
            "source": "yfinance_option_chain",
            "error": f"options fetch failed: {exc}",
            "applicable": False,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Insider alerts (free — yfinance + SEC Form 4 index; no paid vendors)
# ─────────────────────────────────────────────────────────────────────────────

def _insider_from_yfinance(symbol: str) -> dict[str, Any]:
    """Best-effort insider transaction summary via yfinance DataFrames."""
    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        tx = getattr(t, "insider_transactions", None)
        if tx is None:
            return {"source": "yfinance", "error": "insider_transactions unavailable", "rows": []}
        # yfinance may return empty DataFrame
        try:
            empty = tx is None or (hasattr(tx, "empty") and tx.empty)
        except Exception:
            empty = True
        if empty:
            return {"source": "yfinance", "error": None, "rows": [], "note": "empty frame"}

        rows: list[dict[str, Any]] = []
        # Column names vary by yfinance version
        df = tx.reset_index() if hasattr(tx, "reset_index") else tx
        for _, r in df.head(40).iterrows():
            rec = {str(k): (None if (hasattr(v, "isoformat") is False and v != v) else v) for k, v in r.items()}
            # stringify timestamps
            for k, v in list(rec.items()):
                if hasattr(v, "isoformat"):
                    rec[k] = v.isoformat()
                elif hasattr(v, "item"):
                    try:
                        rec[k] = v.item()
                    except Exception:
                        rec[k] = str(v)
            rows.append(rec)

        # Open-market-ish flow only — ignore grants/awards/gifts/tax withholdings
        # so we don't treat RSUs as "insider buying."
        net_shares = 0.0
        open_mkt_buys = 0.0
        open_mkt_sells = 0.0
        awards_gifts = 0.0
        share_cols = ("Shares", "shares", "Change", "change")
        text_cols = ("Text", "text", "Transaction", "transaction")
        for rec in rows:
            shares = None
            for c in share_cols:
                if c in rec and rec[c] is not None:
                    try:
                        shares = float(rec[c])
                        break
                    except (TypeError, ValueError):
                        continue
            if shares is None:
                continue
            blob = " ".join(str(rec.get(c, "")) for c in text_cols).lower()
            if any(
                k in blob
                for k in (
                    "award",
                    "grant",
                    "gift",
                    "tax",
                    "withhold",
                    "conversion",
                    "option exercise",
                    "exercise of",
                )
            ):
                awards_gifts += abs(shares)
                continue
            if any(k in blob for k in ("sale", "sell", "disposed", "dispose")):
                open_mkt_sells += abs(shares)
                net_shares -= abs(shares)
            elif any(k in blob for k in ("purchase", "buy", "acquired", "acquire")):
                open_mkt_buys += abs(shares)
                net_shares += abs(shares)
            # else: skip ambiguous rows

        return {
            "source": "yfinance",
            "error": None,
            "rows": rows[:25],
            "row_count": len(rows),
            "net_shares_heuristic": net_shares,
            "open_market_buys_shares": open_mkt_buys,
            "open_market_sells_shares": open_mkt_sells,
            "awards_gifts_shares_excluded": awards_gifts,
            "note": (
                "Net shares count open-market buy/sell text only; "
                "grants/awards/gifts/tax excluded."
            ),
        }
    except Exception as exc:
        return {"source": "yfinance", "error": str(exc), "rows": []}


def _form4_from_sec_submissions(symbol: str, *, limit: int = 15) -> dict[str, Any]:
    """List recent Form 4 filings from SEC submissions JSON (free EDGAR)."""
    try:
        cik = get_cik_for_ticker(symbol)
    except Exception as exc:
        return {"source": "sec_submissions", "error": f"CIK resolve failed: {exc}", "filings": []}
    try:
        meta = fetch_entity_metadata(cik, force_refresh=False)
        # Re-read full submissions cache for recentFilings
        padded = str(cik).zfill(10)
        path = os.path.join(_SIC_CACHE_DIR, f"CIK{padded}.json")
        if not os.path.exists(path):
            fetch_entity_metadata(cik, force_refresh=True)
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        return {"source": "sec_submissions", "error": str(exc), "filings": [], "cik": cik}

    recent = (raw.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    primaries = recent.get("primaryDocument") or []
    filings: list[dict[str, Any]] = []
    for i, form in enumerate(forms):
        if str(form).strip().upper() not in ("4", "4/A"):
            continue
        acc = accessions[i] if i < len(accessions) else ""
        acc_nodash = str(acc).replace("-", "")
        doc = primaries[i] if i < len(primaries) else ""
        url = ""
        if acc_nodash and doc:
            url = f"https://www.sec.gov/Archives/edgar/data/{int(padded)}/{acc_nodash}/{doc}"
        filings.append(
            {
                "form": form,
                "filing_date": dates[i] if i < len(dates) else None,
                "accession": acc,
                "url": url,
            }
        )
        if len(filings) >= limit:
            break

    return {
        "source": "sec_submissions",
        "error": None,
        "cik": padded,
        "entity_name": meta.get("name") if isinstance(meta, dict) else None,
        "filings": filings,
        "form4_count_recent_index": len(filings),
    }


def fetch_insider_alerts(ticker: str) -> dict[str, Any]:
    """Combine free insider signals: yfinance transactions + SEC Form 4 index.

    No paid vendors. Net-share figures from yfinance are **heuristic** and must
    be labeled as such in canonical metrics / memos.
    """
    symbol = (ticker or "").strip().upper()
    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not symbol:
        return {
            "ticker": None,
            "as_of_utc": as_of,
            "applicable": False,
            "error": "No ticker provided.",
        }

    yf_block = _insider_from_yfinance(symbol)
    sec_block = _form4_from_sec_submissions(symbol)
    net = yf_block.get("net_shares_heuristic")
    form4_n = sec_block.get("form4_count_recent_index") or 0
    has_open_mkt = bool(
        (yf_block.get("open_market_buys_shares") or 0)
        or (yf_block.get("open_market_sells_shares") or 0)
    )
    applicable = bool(
        (isinstance(net, (int, float)) and has_open_mkt)
        or form4_n > 0
    )
    notes = [
        "Free sources only (yfinance insider tables + SEC submissions Form 4 index).",
        "Net share flow is a heuristic from yfinance text/sign conventions — not a Form 4 audit.",
        "Form 4 list is presence/timing of filings, not parsed transaction dollars.",
    ]
    err_bits = [e for e in (yf_block.get("error"), sec_block.get("error")) if e]
    return {
        "ticker": symbol,
        "as_of_utc": as_of,
        "applicable": applicable,
        "error": "; ".join(err_bits) if err_bits and not applicable else None,
        "net_shares_heuristic": net if isinstance(net, (int, float)) else None,
        "yfinance_row_count": yf_block.get("row_count") or 0,
        "form4_recent_count": form4_n,
        "latest_form4_date": (sec_block.get("filings") or [{}])[0].get("filing_date")
        if sec_block.get("filings")
        else None,
        "notable_form4s": (sec_block.get("filings") or [])[:8],
        "yfinance": yf_block,
        "sec_form4": sec_block,
        "notes": notes,
    }


def fetch_market_structure_packet(ticker: str) -> dict[str, Any]:
    """Bundle options + insider free-source packets for metrics_compute."""
    return {
        "ticker": (ticker or "").strip().upper() or None,
        "as_of_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "options_flow": fetch_options_flow(ticker),
        "insider_alerts": fetch_insider_alerts(ticker),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrated gather for data_gatherer_node
# ─────────────────────────────────────────────────────────────────────────────

def gather_live_research_context(
    *,
    ticker: Optional[str],
    sector: str,
    user_query: str,
) -> dict[str, Any]:
    """Bundle SEC statements + live price + narrative Tavily research.

    Returns:
      - income_statement / balance_sheet / cash_flow_statement
      - live_market (price/mcap only)
      - web_research (formatted multi-search text)
      - queries_run, gathered_at_utc, statements_incomplete, statements_error
    """
    empty_stmt: dict[str, Any] = {
        "current_annual": {},
        "prior_annual": {},
        "current_quarter": {},
        "prior_quarter": {},
    }

    income_statement = dict(empty_stmt)
    balance_sheet = dict(empty_stmt)
    cash_flow_statement = dict(empty_stmt)
    statements_incomplete = True
    statements_error: Optional[str] = None
    entity_name = None
    cik = None
    sic = None
    sic_description = None
    extraction_archetype = "general"
    archetype_classification: dict[str, Any] = {}
    derived_notes: list[str] = []

    live_market: dict[str, Any] = {"error": "No ticker provided."}
    if ticker:
        live_market = fetch_live_market_snapshot(ticker)
        try:
            from .archetype import HARD_ARCHETYPES, classify_archetype

            cik = get_cik_for_ticker(ticker)
            meta = fetch_entity_metadata(cik)
            sic = meta.get("sic")
            sic_description = meta.get("sic_description")
            if meta.get("name"):
                entity_name = meta.get("name")

            # Preliminary classify from SIC + ticker + sector (before full extract).
            prelim = classify_archetype(
                ticker=ticker,
                sector=sector,
                sic=sic,
                industry=live_market.get("industry") or sic_description,
            )
            extraction_archetype = prelim.get("archetype") or "general"

            facts = fetch_sec_company_facts(cik)
            parsed = extract_statements_from_company_facts(
                facts, archetype=extraction_archetype
            )
            # Refine archetype with full statements; re-extract if hard type flips.
            refined = classify_archetype(
                ticker=ticker,
                sector=sector,
                sic=sic,
                industry=live_market.get("industry") or sic_description,
                income_statement=parsed["income_statement"],
                balance_sheet=parsed["balance_sheet"],
                cash_flow_statement=parsed["cash_flow_statement"],
            )
            archetype_classification = refined
            final_arch = refined.get("archetype") or extraction_archetype
            if (
                final_arch != extraction_archetype
                and (
                    final_arch in HARD_ARCHETYPES
                    or extraction_archetype in HARD_ARCHETYPES
                )
            ):
                print(
                    f"[extract] re-extract with archetype {extraction_archetype} → {final_arch}",
                    flush=True,
                )
                parsed = extract_statements_from_company_facts(
                    facts, archetype=final_arch
                )
                extraction_archetype = final_arch
            else:
                extraction_archetype = final_arch

            income_statement = parsed["income_statement"]
            balance_sheet = parsed["balance_sheet"]
            cash_flow_statement = parsed["cash_flow_statement"]
            entity_name = parsed.get("entity_name") or entity_name
            derived_notes = list(parsed.get("derived_notes") or [])
            statements_incomplete = False
            statements_error = None
        except urllib.error.HTTPError as exc:
            statements_error = f"SEC EDGAR HTTP error: {exc.code} {exc.reason}"
            statements_incomplete = True
        except Exception as exc:
            statements_error = f"SEC statement pipeline failed: {exc}"
            statements_incomplete = True

    # Narrative only — things XBRL tags cannot provide.
    # Every query is ticker-anchored when a ticker is present so Tavily does
    # not return arbitrary finance names (CULP / AT&T / Jack in the Box style misses).
    queries: list[str] = []
    if ticker:
        t = ticker.strip().upper()
        name_hint = f"{entity_name} " if entity_name else ""
        queries.extend(
            [
                f"{t} {name_hint}latest earnings call takeaways guidance changes",
                f"{t} {name_hint}analyst commentary outlook risks litigation regulatory",
                f"{t} {name_hint}management discussion MD&A themes strategy {sector}",
                f"{t} {name_hint}{sector} macro rates inflation policy impact",
            ]
        )
    else:
        queries.append(
            f"{sector} sector macro rates inflation policy impact {user_query}"
        )
    queries = queries[:5]
    web_research = multi_search(queries, max_results=5, topic="finance")
    if ticker:
        check_search_relevance(
            web_research,
            ticker=ticker,
            entity_name=entity_name,
            label="data_gatherer.search",
        )

    return {
        "entity_name": entity_name,
        "cik": cik,
        "sic": sic,
        "sic_description": sic_description,
        "extraction_archetype": extraction_archetype,
        "archetype_classification": archetype_classification,
        "derived_notes": derived_notes,
        "income_statement": income_statement,
        "balance_sheet": balance_sheet,
        "cash_flow_statement": cash_flow_statement,
        "live_market": live_market,
        "web_research": web_research,
        "queries_run": queries,
        "statements_incomplete": statements_incomplete,
        "statements_error": statements_error,
        "gathered_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def peers_by_sic_proximity(
    sic: str,
    *,
    subject: Optional[str] = None,
    limit: int = 12,
) -> list[str]:
    """Return tickers with same 4-digit SIC, else same 3-digit prefix.

    Uses cached submissions under ``.cache/submissions/`` plus a small static
    SIC→ticker seed for common US filers (no full EDGAR crawl).
    """
    from .archetype import TICKER_ARCHETYPE

    target = str(sic).zfill(4)[:4]
    prefix3 = target[:3]
    subj = (subject or "").strip().upper()
    found4: list[str] = []
    found3: list[str] = []

    # Scan submissions cache
    if os.path.isdir(_SIC_CACHE_DIR):
        for name in os.listdir(_SIC_CACHE_DIR):
            if not name.startswith("CIK") or not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(_SIC_CACHE_DIR, name), "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception:
                continue
            s = raw.get("sic") or raw.get("sicCode")
            if s is None:
                continue
            s4 = str(s).zfill(4)[:4]
            for t in raw.get("tickers") or []:
                if not isinstance(t, str):
                    continue
                tu = t.upper()
                if tu == subj:
                    continue
                if s4 == target:
                    found4.append(tu)
                elif s4.startswith(prefix3):
                    found3.append(tu)

    # Static seed: known tickers — fetch SIC if cached only (don't network here)
    seed = list(TICKER_ARCHETYPE.keys())
    for tu in seed:
        if tu == subj:
            continue
        # best-effort: if we ever cached their CIK submissions
        # skip network; already covered by cache scan

    ordered = []
    for t in found4 + found3:
        if t not in ordered:
            ordered.append(t)
    return ordered[:limit]


def gather_business_overview_context(
    *,
    ticker: Optional[str],
    sector: str,
    user_query: str,
) -> dict[str, Any]:
    """Tavily research focused on 10-K Item 1 Business narrative."""
    if ticker:
        t = ticker.strip().upper()
        queries = [
            f"{t} 10-K Item 1 Business description products segments",
            f"{t} company overview revenue streams geographic footprint",
            f"{t} competitive position history M&A strategy management priorities",
            f"{t} {sector} business model how it makes money",
        ]
    else:
        queries = [
            f"{sector} leading companies business models overview",
            f"{sector} {user_query}",
        ]
    queries = queries[:4]
    web_research = multi_search(queries, max_results=6, topic="finance")
    return {
        "web_research": web_research,
        "queries_run": queries,
        "gathered_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def gather_macro_regime_context(
    *,
    ticker: Optional[str],
    sector: str,
    user_query: str,
) -> dict[str, Any]:
    """Tavily research for debt-cycle / reflexivity / sector-cycle positioning.

    Independent of data_gatherer — focused queries for rates, inflation,
    fiscal/debt levels, central-bank posture, and sector-specific cycles.
    """
    # Keep 1–2 true top-down macro queries, then force ticker/sector anchors so
    # the digest is not a random grab-bag of unrelated equities.
    queries: list[str] = [
        "US Federal Reserve policy rate inflation CPI latest decision outlook",
        "US government debt GDP fiscal deficit Treasury yields current levels",
    ]
    if ticker:
        t = ticker.strip().upper()
        queries.extend(
            [
                f"{t} {sector} macro sensitivity rates credit cycle demand outlook",
                f"{t} {sector} sector cycle capex inventory AI demand rates",
                f"{t} {user_query} macro regime rates inflation",
            ]
        )
    else:
        queries.extend(
            [
                f"{sector} sector cycle outlook capex inventory demand rates sensitivity",
                f"{sector} {user_query} macro rates inflation policy",
            ]
        )

    queries = queries[:5]
    web_research = multi_search(queries, max_results=5, topic="finance")
    # Only flag when a ticker was requested: pure macro queries legitimately
    # omit company names, but the company-anchored rows should bring them in.
    if ticker:
        check_search_relevance(
            web_research,
            ticker=ticker,
            entity_name=None,
            label="macro_regime.search",
        )
    return {
        "web_research": web_research,
        "queries_run": queries,
        "gathered_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def gather_management_track_record_context(
    *,
    ticker: Optional[str],
    sector: str,
    user_query: str,
) -> dict[str, Any]:
    """Tavily research for executive track record, insiders, pay, governance.

    Independent of data_gatherer — people/leadership facts only (not capital
    allocation math, which uses statement numbers downstream).
    """
    if ticker:
        t = ticker.strip().upper()
        queries = [
            f"{t} CEO name tenure biography track record leadership",
            f"{t} CFO chief financial officer name biography appointment",
            f"{t} DEF 14A proxy executive compensation equity awards CEO pay",
            f"{t} Form 4 insider transactions buying selling last 12 months",
            f"{t} board of directors independence succession plan governance",
        ]
    else:
        queries = [
            f"{sector} company leadership executives track records",
            f"{sector} CEO compensation governance insider activity",
            f"{sector} {user_query} management quality succession",
        ]
    queries = queries[:5]
    web_research = multi_search(queries, max_results=5, topic="finance")
    return {
        "web_research": web_research,
        "queries_run": queries,
        "gathered_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
