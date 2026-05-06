"""Data fetching layer for Ani Terminal.

All external API calls live here. Functions are cached via Streamlit so the
UI does not refetch on every interaction. Errors are returned as None or
empty structures so the UI can render a graceful warning instead of crashing.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

try:
    from fredapi import Fred
    _FRED = Fred(api_key=FRED_API_KEY) if FRED_API_KEY else None
except Exception:
    _FRED = None


# ---------------------------------------------------------------------------
# yfinance helpers
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def yf_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Return price history for a ticker. Empty DataFrame on failure."""
    try:
        df = yf.Ticker(ticker).history(period=period, auto_adjust=False)
        if df is None or df.empty:
            return pd.DataFrame()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def yf_quote(ticker: str) -> dict:
    """Latest price + daily change + 1-month change for a ticker."""
    df = yf_history(ticker, period="3mo")
    if df.empty or "Close" not in df.columns:
        return {"ticker": ticker, "price": None, "change_pct": None, "month_change_pct": None}
    closes = df["Close"].dropna()
    if len(closes) < 2:
        return {"ticker": ticker, "price": float(closes.iloc[-1]) if len(closes) else None,
                "change_pct": None, "month_change_pct": None}
    price = float(closes.iloc[-1])
    prev = float(closes.iloc[-2])
    change_pct = (price / prev - 1) * 100 if prev else None
    month_idx = max(0, len(closes) - 22)
    month_prev = float(closes.iloc[month_idx])
    month_change_pct = (price / month_prev - 1) * 100 if month_prev else None
    return {"ticker": ticker, "price": price, "change_pct": change_pct,
            "month_change_pct": month_change_pct}


@st.cache_data(ttl=3600, show_spinner=False)
def yf_quotes(tickers: list[str]) -> dict[str, dict]:
    return {t: yf_quote(t) for t in tickers}


@st.cache_data(ttl=3600, show_spinner=False)
def yf_ytd_change(ticker: str) -> Optional[float]:
    """Year-to-date percent change for a ticker."""
    df = yf_history(ticker, period="1y")
    if df.empty or "Close" not in df.columns:
        return None
    year = datetime.now().year
    ytd = df[df.index.year == year]["Close"].dropna()
    if len(ytd) < 2:
        return None
    return float((ytd.iloc[-1] / ytd.iloc[0] - 1) * 100)


# ---------------------------------------------------------------------------
# FRED helpers
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fred_series(series_id: str, observation_start: Optional[str] = None) -> pd.Series:
    """Fetch a FRED series. Empty Series on failure."""
    if _FRED is None:
        return pd.Series(dtype=float)
    try:
        kwargs = {}
        if observation_start:
            kwargs["observation_start"] = observation_start
        s = _FRED.get_series(series_id, **kwargs)
        return s.dropna() if s is not None else pd.Series(dtype=float)
    except Exception:
        return pd.Series(dtype=float)


def fred_latest(series_id: str) -> tuple[Optional[float], Optional[float]]:
    """Return (current, prior) values for a FRED series."""
    s = fred_series(series_id)
    if s.empty:
        return None, None
    if len(s) < 2:
        return float(s.iloc[-1]), None
    return float(s.iloc[-1]), float(s.iloc[-2])


def fred_yoy(series_id: str) -> tuple[Optional[float], Optional[float]]:
    """Year-over-year percent change for a monthly FRED series.

    Returns (latest_yoy, prior_yoy) so the UI can show direction.
    """
    s = fred_series(series_id)
    if s.empty or len(s) < 13:
        return None, None
    yoy = s.pct_change(periods=12) * 100
    yoy = yoy.dropna()
    if yoy.empty:
        return None, None
    if len(yoy) < 2:
        return float(yoy.iloc[-1]), None
    return float(yoy.iloc[-1]), float(yoy.iloc[-2])


# ---------------------------------------------------------------------------
# NewsAPI
# ---------------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def news_search(query: str, page_size: int = 10) -> list[dict]:
    """Search NewsAPI. Returns list of {title, description, url, publishedAt, source}."""
    if not NEWS_API_KEY:
        return []
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": page_size,
                "apiKey": NEWS_API_KEY,
            },
            timeout=10,
        )
        if r.status_code != 200:
            return []
        articles = r.json().get("articles", [])
        return [
            {
                "title": a.get("title", ""),
                "description": a.get("description", "") or "",
                "url": a.get("url", ""),
                "publishedAt": a.get("publishedAt", ""),
                "source": (a.get("source") or {}).get("name", ""),
            }
            for a in articles
            if a.get("title")
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Convenience: the yield curve as one structure
# ---------------------------------------------------------------------------
YIELD_CURVE_SERIES = [
    ("1M", "DGS1MO"),
    ("3M", "DGS3MO"),
    ("6M", "DGS6MO"),
    ("1Y", "DGS1"),
    ("2Y", "DGS2"),
    ("3Y", "DGS3"),
    ("5Y", "DGS5"),
    ("7Y", "DGS7"),
    ("10Y", "DGS10"),
    ("20Y", "DGS20"),
    ("30Y", "DGS30"),
]


@st.cache_data(ttl=3600, show_spinner=False)
def yield_curve_snapshot() -> pd.DataFrame:
    """Return DataFrame with columns: tenor, current, year_ago, two_years_ago."""
    rows = []
    today = pd.Timestamp(datetime.now().date())
    one_year_ago = today - pd.Timedelta(days=365)
    two_years_ago = today - pd.Timedelta(days=730)
    for tenor, series_id in YIELD_CURVE_SERIES:
        s = fred_series(series_id)
        if s.empty:
            rows.append({"tenor": tenor, "current": None, "year_ago": None,
                         "two_years_ago": None})
            continue
        s.index = pd.to_datetime(s.index)
        current = float(s.iloc[-1])
        year_ago = _value_near(s, one_year_ago)
        two_years = _value_near(s, two_years_ago)
        rows.append({"tenor": tenor, "current": current, "year_ago": year_ago,
                     "two_years_ago": two_years})
    return pd.DataFrame(rows)


def _value_near(series: pd.Series, target: pd.Timestamp) -> Optional[float]:
    """Return the series value at-or-before target date."""
    if series.empty:
        return None
    sub = series[series.index <= target]
    if sub.empty:
        return None
    return float(sub.iloc[-1])


# ---------------------------------------------------------------------------
# Earnings via yfinance
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def latest_earnings(ticker: str) -> dict:
    """Pull most recent quarterly fundamentals via yfinance.

    Returns dict with revenue, revenue_yoy, eps, eps_yoy, net_income, gross_margin.
    Any field may be None when yfinance does not surface it.
    """
    out = {
        "ticker": ticker,
        "revenue": None,
        "revenue_yoy": None,
        "eps": None,
        "eps_yoy": None,
        "net_income": None,
        "gross_margin": None,
    }
    try:
        t = yf.Ticker(ticker)
        qf = None
        try:
            qf = t.quarterly_financials
        except Exception:
            qf = None
        if qf is not None and not qf.empty:
            cols = list(qf.columns)
            if cols:
                latest = cols[0]
                rev = _safe_lookup(qf, "Total Revenue", latest)
                ni = _safe_lookup(qf, "Net Income", latest)
                gp = _safe_lookup(qf, "Gross Profit", latest)
                out["revenue"] = rev
                out["net_income"] = ni
                if rev and gp:
                    out["gross_margin"] = (gp / rev) * 100
                if len(cols) >= 5:
                    yoy_col = cols[4]
                    rev_yoy = _safe_lookup(qf, "Total Revenue", yoy_col)
                    if rev and rev_yoy:
                        out["revenue_yoy"] = (rev / rev_yoy - 1) * 100
        # EPS via earnings_history
        try:
            hist = t.earnings_history
            if hist is not None and not hist.empty:
                eps_col = "epsActual" if "epsActual" in hist.columns else (
                    "EPS Actual" if "EPS Actual" in hist.columns else None)
                if eps_col:
                    eps_series = hist[eps_col].dropna()
                    if len(eps_series) >= 1:
                        out["eps"] = float(eps_series.iloc[-1])
                    if len(eps_series) >= 5:
                        prior = float(eps_series.iloc[-5])
                        if prior:
                            out["eps_yoy"] = (out["eps"] / prior - 1) * 100
        except Exception:
            pass
    except Exception:
        pass
    return out


def _safe_lookup(df: pd.DataFrame, row: str, col) -> Optional[float]:
    try:
        if row in df.index:
            v = df.loc[row, col]
            if pd.notna(v):
                return float(v)
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Tickers used across the app
# ---------------------------------------------------------------------------
OVERVIEW_MARKETS = ["SPY", "QQQ", "DX-Y.NYB", "^VIX"]
OVERVIEW_COMMODITIES = ["CL=F", "GC=F", "HG=F", "NG=F"]
OVERVIEW_FX = ["EURUSD=X", "CNY=X", "JPY=X", "BTC-USD"]

SECTOR_ETFS = {
    "XLK": "Tech",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communications",
}

MAJOR_STOCKS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
                "QCOM", "CRM", "BABA", "TSM", "ASML"]

EARNINGS_STOCKS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
                   "QCOM", "CRM"]

GLOBAL_ETFS = {
    "EEM": "Emerging Markets",
    "EWJ": "Japan",
    "FXI": "China",
    "EWZ": "Brazil",
    "EWG": "Germany",
    "EWY": "South Korea",
}


def has_fred() -> bool:
    return _FRED is not None


def has_news() -> bool:
    return bool(NEWS_API_KEY)
