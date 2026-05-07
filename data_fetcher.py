"""Data fetching layer for Ani Terminal."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from dotenv import load_dotenv
from fredapi import Fred

load_dotenv()


def get_secret(key):
    try:
        val = st.secrets.get(key)
        if val:
            return val
    except Exception:
        pass
    return os.getenv(key)


FRED_API_KEY = get_secret("FRED_API_KEY") or "35c497c8d13b7c40e6b3cc75fb2817dc"
NEWS_API_KEY = get_secret("NEWS_API_KEY") or "db162a8b8ca042389ce24e6b644b0143"
ANTHROPIC_API_KEY = get_secret("ANTHROPIC_API_KEY") or "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"


# ---------------------------------------------------------------------------
# yfinance — price / history
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def get_price(symbol):
    try:
        # Futures (=F) can have contract roll gaps in 5d windows; widen to 1mo
        period = "1mo" if symbol.endswith("=F") else "5d"
        ticker = yf.Ticker(symbol)
        data = ticker.history(period=period, interval="1d")
        data = data.dropna(subset=["Close"])
        if len(data) < 2:
            return None, None
        price = float(data["Close"].iloc[-1])
        prev = float(data["Close"].iloc[-2])
        pct = ((price - prev) / prev) * 100
        return price, pct
    except Exception:
        return None, None


@st.cache_data(ttl=300, show_spinner=False)
def get_history_1y(symbol):
    try:
        df = yf.Ticker(symbol).history(period="1y", interval="1d")
        return df if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def get_history_5y(symbol):
    try:
        df = yf.Ticker(symbol).history(period="5y", interval="1wk")
        return df if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def get_month_change(symbol):
    try:
        df = yf.Ticker(symbol).history(period="3mo", interval="1d").dropna()
        if len(df) < 22:
            return None
        return float((df["Close"].iloc[-1] / df["Close"].iloc[-22] - 1) * 100)
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def get_ytd_change(symbol):
    try:
        df = yf.Ticker(symbol).history(period="1y", interval="1d").dropna()
        if df.empty:
            return None
        year = datetime.now().year
        ytd = df[df.index.year == year]["Close"]
        if len(ytd) < 2:
            return None
        return float((ytd.iloc[-1] / ytd.iloc[0] - 1) * 100)
    except Exception:
        return None


# Backward-compatible helpers used across app.py
def yf_quote(ticker):
    price, pct = get_price(ticker)
    return {
        "ticker": ticker,
        "price": price,
        "change_pct": pct,
        "month_change_pct": get_month_change(ticker),
    }


def yf_quotes(tickers):
    return {t: yf_quote(t) for t in tickers}


def yf_history(ticker, period="1y"):
    if str(period).startswith("5y"):
        return get_history_5y(ticker)
    return get_history_1y(ticker)


def yf_ytd_change(ticker):
    return get_ytd_change(ticker)


# ---------------------------------------------------------------------------
# FRED
# ---------------------------------------------------------------------------
def get_fred_client():
    return Fred(api_key=FRED_API_KEY) if FRED_API_KEY else None


@st.cache_data(ttl=3600, show_spinner=False)
def get_fred(series_id):
    try:
        fred = get_fred_client()
        if fred is None:
            return None, None, None
        data = fred.get_series(series_id).dropna()
        if data.empty:
            return None, None, None
        if len(data) < 2:
            return float(data.iloc[-1]), None, data
        return float(data.iloc[-1]), float(data.iloc[-2]), data
    except Exception:
        return None, None, None


@st.cache_data(ttl=3600, show_spinner=False)
def get_fred_yoy(series_id):
    try:
        fred = get_fred_client()
        if fred is None:
            return None, None, None
        data = fred.get_series(series_id).dropna()
        yoy = (data.pct_change(periods=12) * 100).dropna()
        if yoy.empty:
            return None, None, None
        if len(yoy) < 2:
            return float(yoy.iloc[-1]), None, yoy
        return float(yoy.iloc[-1]), float(yoy.iloc[-2]), yoy
    except Exception:
        return None, None, None


def get_treasury_yields():
    """Current 2Y / 10Y / 30Y yields (%) and 2Y/10Y spread (bps) from FRED.

    Returns prior values too so callers can show daily deltas in bps.
    """
    y2, y2_prior, _ = get_fred("DGS2")
    y10, y10_prior, _ = get_fred("DGS10")
    y30, y30_prior, _ = get_fred("DGS30")

    # FRED sometimes returns yields in decimal form (0.0442) instead of
    # percent (4.42). Normalize to percent.
    def to_pct(v):
        if v is None:
            return None
        return v * 100 if v < 0.5 else v

    y2, y2_prior = to_pct(y2), to_pct(y2_prior)
    y10, y10_prior = to_pct(y10), to_pct(y10_prior)
    y30, y30_prior = to_pct(y30), to_pct(y30_prior)

    spread_bps = ((y10 - y2) * 100) if (y10 is not None and y2 is not None) else None

    return {
        "y2": y2, "y10": y10, "y30": y30,
        "y2_prior": y2_prior, "y10_prior": y10_prior, "y30_prior": y30_prior,
        "spread_bps": spread_bps,
    }


# Backward-compat shims
def fred_series(series_id, observation_start=None):
    _, _, s = get_fred(series_id)
    if s is None:
        return pd.Series(dtype=float)
    if observation_start:
        return s[s.index >= pd.Timestamp(observation_start)]
    return s


def fred_latest(series_id):
    cur, prior, _ = get_fred(series_id)
    return cur, prior


def fred_yoy(series_id):
    cur, prior, _ = get_fred_yoy(series_id)
    return cur, prior


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------
COMPANY_NAMES = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "Nvidia",
    "GOOGL": "Google",
    "AMZN": "Amazon",
    "META": "Meta",
    "TSLA": "Tesla",
    "QCOM": "Qualcomm",
    "CRM": "Salesforce",
    "BABA": "Alibaba",
    "TSM": "TSMC",
    "ASML": "ASML",
    "XIACY": "Xiaomi",
}


@st.cache_data(ttl=1800, show_spinner=False)
def get_stock_news(ticker, company_name=None):
    if company_name is None:
        company_name = COMPANY_NAMES.get(ticker, ticker)
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": company_name,
            "sortBy": "publishedAt",
            "pageSize": 5,
            "language": "en",
            "apiKey": NEWS_API_KEY,
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get("status") == "ok":
            return [
                {
                    "title": a["title"],
                    "url": a["url"],
                    "source": a["source"]["name"],
                    "date": a["publishedAt"][:10],
                }
                for a in data.get("articles", [])
                if a.get("title") and "[Removed]" not in a["title"]
            ]
        return []
    except Exception:
        return []


@st.cache_data(ttl=1800, show_spinner=False)
def news_search(query, page_size=10):
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
            if a.get("title") and "[Removed]" not in a.get("title", "")
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Earnings
# ---------------------------------------------------------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def get_earnings_data(ticker):
    try:
        t = yf.Ticker(ticker)
        qf = t.quarterly_financials
        if qf is None or qf.empty:
            return None
        latest = qf.columns[0]
        year_ago = qf.columns[4] if len(qf.columns) > 4 else None

        revenue, rev_yoy, net_income, gross_margin = None, None, None, None

        for key in ["Total Revenue", "Revenue"]:
            if key in qf.index:
                revenue = float(qf.loc[key, latest])
                if year_ago is not None:
                    prior = float(qf.loc[key, year_ago])
                    if prior:
                        rev_yoy = ((revenue - prior) / abs(prior)) * 100
                break

        for key in ["Net Income", "Net Income Common Stockholders"]:
            if key in qf.index:
                net_income = float(qf.loc[key, latest])
                break

        for key in ["Gross Profit"]:
            if key in qf.index and revenue:
                gross_margin = (float(qf.loc[key, latest]) / revenue) * 100
                break

        eps = None
        try:
            eps = t.info.get("trailingEps", None)
        except Exception:
            eps = None

        # EPS YoY — pull historical EPS from earnings_history
        eps_yoy = None
        try:
            eh = t.earnings_history
            if eh is not None and not eh.empty and "epsActual" in eh.columns:
                eps_actuals = eh["epsActual"].dropna()
                if len(eps_actuals) >= 5:
                    current_eps = float(eps_actuals.iloc[-1])
                    year_ago_eps = float(eps_actuals.iloc[-5])
                    if year_ago_eps:
                        eps_yoy = ((current_eps - year_ago_eps) / abs(year_ago_eps)) * 100
        except Exception:
            pass

        return {
            "revenue": revenue,
            "rev_yoy": rev_yoy,
            "net_income": net_income,
            "gross_margin": gross_margin,
            "eps": eps,
            "eps_yoy": eps_yoy,
            "quarter": str(latest)[:10],
        }
    except Exception:
        return None


def latest_earnings(ticker):
    """Backward-compat shim returning the dict shape used by app.py."""
    e = get_earnings_data(ticker)
    if e is None:
        return {
            "ticker": ticker, "revenue": None, "revenue_yoy": None,
            "eps": None, "eps_yoy": None, "net_income": None,
            "gross_margin": None, "quarter": None,
        }
    return {
        "ticker": ticker,
        "revenue": e["revenue"],
        "revenue_yoy": e["rev_yoy"],
        "eps": e["eps"],
        "eps_yoy": e.get("eps_yoy"),
        "net_income": e["net_income"],
        "gross_margin": e["gross_margin"],
        "quarter": e["quarter"],
    }


# ---------------------------------------------------------------------------
# Yield curve snapshot (FRED)
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
def yield_curve_snapshot():
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
        rows.append({
            "tenor": tenor,
            "current": float(s.iloc[-1]),
            "year_ago": _value_near(s, one_year_ago),
            "two_years_ago": _value_near(s, two_years_ago),
        })
    return pd.DataFrame(rows)


def _value_near(series, target):
    if series.empty:
        return None
    sub = series[series.index <= target]
    if sub.empty:
        return None
    return float(sub.iloc[-1])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
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


def has_fred():
    return bool(FRED_API_KEY)


def has_news():
    return bool(NEWS_API_KEY)
