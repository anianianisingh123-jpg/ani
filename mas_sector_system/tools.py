"""Live data tools for the sector research agents.

Two sources of truth for "what's real right now":

  1. Tavily web search  — news, filings coverage, sector developments
  2. yfinance           — prices, multiples, fundamentals for a ticker

These are plain Python helpers (not LangChain tool objects). Nodes call them
before prompting the LLM so the model is grounded in fresh external data
instead of its training cutoff.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv

# Load both package-local and repo-root .env files (either is fine).
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_PKG_DIR)
load_dotenv(os.path.join(_PKG_DIR, ".env"))
load_dotenv(os.path.join(_REPO_ROOT, ".env"))


def _tavily_key() -> Optional[str]:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return None
    # Strip accidental quotes from .env lines like KEY="tvly-..."
    return key.strip().strip('"').strip("'")


def web_search(
    query: str,
    *,
    max_results: int = 6,
    search_depth: str = "advanced",
    topic: str = "finance",
    include_answer: bool = True,
) -> dict[str, Any]:
    """Run a Tavily search and return a structured result dict.

    Returns:
        {
          "query": str,
          "answer": str | None,          # Tavily's short synthesized answer
          "results": [                   # ranked hits
            {"title", "url", "content", "score", "published_date"},
            ...
          ],
          "error": str | None,
        }
    """
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
    except Exception as exc:  # network / auth / package issues
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


def fetch_ticker_fundamentals(ticker: str) -> dict[str, Any]:
    """Pull live price + key fundamentals for a ticker via yfinance.

    Failures degrade to an error field rather than raising, so agents can
    still proceed on web-search context alone.
    """
    if not ticker:
        return {"error": "No ticker provided."}

    symbol = ticker.strip().upper()
    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        info = t.info or {}
        # Fast path for price if .info is sparse
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            hist = t.history(period="5d")
            if hist is not None and not hist.empty:
                price = float(hist["Close"].iloc[-1])

        def _g(*keys, default=None):
            for k in keys:
                v = info.get(k)
                if v is not None:
                    return v
            return default

        return {
            "ticker": symbol,
            "as_of_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "name": _g("longName", "shortName"),
            "sector": _g("sector"),
            "industry": _g("industry"),
            "currency": _g("currency"),
            "price": price,
            "market_cap": _g("marketCap"),
            "enterprise_value": _g("enterpriseValue"),
            "trailing_pe": _g("trailingPE"),
            "forward_pe": _g("forwardPE"),
            "peg_ratio": _g("pegRatio"),
            "price_to_book": _g("priceToBook"),
            "price_to_sales": _g("priceToSalesTrailing12Months"),
            "ev_to_ebitda": _g("enterpriseToEbitda"),
            "profit_margin": _g("profitMargins"),
            "operating_margin": _g("operatingMargins"),
            "gross_margin": _g("grossMargins"),
            "revenue_ttm": _g("totalRevenue"),
            "ebitda": _g("ebitda"),
            "net_income_ttm": _g("netIncomeToCommon"),
            "eps_ttm": _g("trailingEps"),
            "eps_forward": _g("forwardEps"),
            "free_cash_flow": _g("freeCashflow"),
            "operating_cash_flow": _g("operatingCashflow"),
            "total_cash": _g("totalCash"),
            "total_debt": _g("totalDebt"),
            "debt_to_equity": _g("debtToEquity"),
            "current_ratio": _g("currentRatio"),
            "return_on_equity": _g("returnOnEquity"),
            "return_on_assets": _g("returnOnAssets"),
            "revenue_growth": _g("revenueGrowth"),
            "earnings_growth": _g("earningsGrowth"),
            "dividend_yield": _g("dividendYield"),
            "52w_high": _g("fiftyTwoWeekHigh"),
            "52w_low": _g("fiftyTwoWeekLow"),
            "beta": _g("beta"),
            "shares_outstanding": _g("sharesOutstanding"),
            "float_shares": _g("floatShares"),
            "short_ratio": _g("shortRatio"),
            "target_mean_price": _g("targetMeanPrice"),
            "recommendation": _g("recommendationKey"),
            "error": None,
        }
    except Exception as exc:
        return {"ticker": symbol, "error": f"yfinance fetch failed: {exc}"}


def gather_live_research_context(
    *,
    ticker: Optional[str],
    sector: str,
    user_query: str,
) -> dict[str, Any]:
    """Bundle live market data + web research for the data-gatherer node.

    Returns a dict with:
      - fundamentals: yfinance payload (or empty if no ticker)
      - web_research: formatted multi-search text
      - queries_run: list of search queries used
    """
    queries: list[str] = []
    if ticker:
        t = ticker.strip().upper()
        queries.extend(
            [
                f"{t} stock latest earnings financial results valuation",
                f"{t} 10-K 10-Q SEC filing risk factors latest",
                f"{t} news analyst outlook risks {sector}",
            ]
        )
    queries.extend(
        [
            f"{sector} sector outlook valuation trends latest",
            f"{sector} macroeconomic rates inflation impact {user_query}",
        ]
    )
    # Cap to avoid burning Tavily quota on every run
    queries = queries[:5]

    fundamentals = (
        fetch_ticker_fundamentals(ticker) if ticker else {"error": "No ticker (screener path)."}
    )
    web_research = multi_search(queries, max_results=5, topic="finance")

    return {
        "fundamentals": fundamentals,
        "web_research": web_research,
        "queries_run": queries,
        "gathered_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
