"""Ani Terminal — personal macro and investment research dashboard.

Run with:
    streamlit run app.py
"""
from __future__ import annotations

import os
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import data_fetcher as df_
import thesis_engine as te


def get_secret(key):
    try:
        val = st.secrets.get(key)
        if val:
            return val
    except Exception:
        pass
    return os.getenv(key)


FRED_API_KEY = get_secret("FRED_API_KEY")
NEWS_API_KEY = get_secret("NEWS_API_KEY")
ANTHROPIC_API_KEY = get_secret("ANTHROPIC_API_KEY")


def _last(series: pd.Series, years: int) -> pd.Series:
    if series.empty:
        return series
    idx = pd.to_datetime(series.index)
    cutoff = idx.max() - pd.DateOffset(years=years)
    return series[idx >= cutoff]


st.set_page_config(
    page_title="Ani Terminal",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fmt(value, suffix: str = "", decimals: int = 2) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    return f"{value:,.{decimals}f}{suffix}"


def _delta_str(value, suffix: str = "%") -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return f"{value:+.2f}{suffix}"


def _metric_card(label, value, delta=None, value_suffix="", delta_suffix="%",
                 help_text=None, delta_color="normal", decimals=2):
    st.metric(
        label=label,
        value=_fmt(value, value_suffix, decimals),
        delta=_delta_str(delta, delta_suffix),
        help=help_text,
        delta_color=delta_color,
    )


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _last_updated():
    st.caption(f"Last updated: {_now_str()}")


def _api_status_warnings():
    missing = []
    if not df_.has_fred():
        missing.append("FRED_API_KEY")
    if not df_.has_news():
        missing.append("NEWS_API_KEY")
    if not te.has_anthropic():
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        st.warning(
            "Missing API keys: " + ", ".join(missing)
            + ". Some sections will be empty until configured."
        )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("ANI TERMINAL")
    st.markdown(f"**{datetime.now().strftime('%A, %B %d %Y')}**")
    st.markdown(f"`{datetime.now().strftime('%H:%M:%S')}`")
    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption("Data: yfinance, FRED, NewsAPI")
    st.caption("Theses scored by Claude")


_api_status_warnings()


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_overview, tab_debt, tab_bonds, tab_macro, tab_commodities, tab_fx, tab_equities, tab_thesis = st.tabs([
    "Overview",
    "Debt Cycle",
    "Bonds",
    "Macro Data",
    "Commodities",
    "Currencies",
    "Equities",
    "Portfolio & Thesis",
])


# ---------------------------------------------------------------------------
# Tab 1 — Overview
# ---------------------------------------------------------------------------
def render_overview():
    st.header("Overview — 30-Second Read")

    markets = {
        "^GSPC": "S&P 500",
        "^IXIC": "Nasdaq",
        "DX-Y.NYB": "DXY",
        "^VIX": "VIX",
    }
    commodities = {
        "CL=F": "WTI Crude",
        "GC=F": "Gold",
        "HG=F": "Copper",
        "NG=F": "Natural Gas",
    }
    fx = {
        "EURUSD=X": "EUR/USD",
        "CNY=X": "USD/CNY",
        "JPY=X": "USD/JPY",
        "BTC-USD": "Bitcoin",
    }

    market_quotes = df_.yf_quotes(list(markets.keys()))
    commodity_quotes = df_.yf_quotes(list(commodities.keys()))
    fx_quotes = df_.yf_quotes(list(fx.keys()))

    st.subheader("Markets")
    cols = st.columns(4)
    for col, (ticker, label) in zip(cols, markets.items()):
        q = market_quotes[ticker]
        with col:
            _metric_card(label, q["price"], q["change_pct"])

    st.subheader("Rates")
    cols = st.columns(4)
    # 2Y → ^IRX, 10Y → ^TNX, 30Y → ^TYX (yfinance returns scaled values; /100)
    y2_raw, y2_pct = df_.get_price("^IRX")
    y10_raw, y10_pct = df_.get_price("^TNX")
    y30_raw, y30_pct = df_.get_price("^TYX")
    y2 = (y2_raw / 100) if y2_raw is not None else None
    y10 = (y10_raw / 100) if y10_raw is not None else None
    y30 = (y30_raw / 100) if y30_raw is not None else None
    with cols[0]:
        _metric_card("US 2Y Yield", y2, y2_pct, value_suffix="%")
    with cols[1]:
        _metric_card("US 10Y Yield", y10, y10_pct, value_suffix="%")
    with cols[2]:
        _metric_card("US 30Y Yield", y30, y30_pct, value_suffix="%")
    with cols[3]:
        spread = (y10 - y2) * 100 if (y10 is not None and y2 is not None) else None
        spread_color = "inverse" if (spread is not None and spread < 0) else "normal"
        st.metric(
            "2Y/10Y Spread",
            f"{spread:+.0f} bps" if spread is not None else "—",
            delta="Inverted" if (spread is not None and spread < 0) else "Positive",
            delta_color=spread_color,
        )

    st.subheader("Commodities")
    cols = st.columns(4)
    for col, (ticker, label) in zip(cols, commodities.items()):
        q = commodity_quotes[ticker]
        with col:
            _metric_card(label, q["price"], q["change_pct"])

    st.subheader("Currencies & Crypto")
    cols = st.columns(4)
    for col, (ticker, label) in zip(cols, fx.items()):
        q = fx_quotes[ticker]
        with col:
            _metric_card(label, q["price"], q["change_pct"], decimals=4)

    st.divider()
    st.subheader("1-Year Asset Performance (Normalized)")
    fig = _normalized_performance_chart(
        {"SPY": "SPY (S&P 500)", "QQQ": "QQQ (Nasdaq)",
         "GLD": "GLD (Gold)", "TLT": "TLT (20Y Treasuries)"},
        period="1y",
    )
    st.plotly_chart(fig, use_container_width=True, key="overview_normalized_1y")
    _last_updated()


def _normalized_performance_chart(tickers, period="1y"):
    fig = go.Figure()
    for ticker, label in tickers.items():
        hist = df_.yf_history(ticker, period=period)
        if hist.empty or "Close" not in hist.columns:
            continue
        closes = hist["Close"].dropna()
        if closes.empty:
            continue
        normalized = closes / closes.iloc[0] * 100
        fig.add_trace(go.Scatter(x=normalized.index, y=normalized.values,
                                 mode="lines", name=label))
    fig.update_layout(
        height=420,
        margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        yaxis_title="Index (start = 100)",
        template="plotly_dark",
    )
    return fig


# ---------------------------------------------------------------------------
# Tab 2 — Debt Cycle
# ---------------------------------------------------------------------------
def render_debt_cycle():
    st.header("Dalio Debt Cycle Monitor")

    debt_to_gdp_series = df_.fred_series("GFDEGDQ188S")
    debt_to_gdp = float(debt_to_gdp_series.iloc[-1]) if not debt_to_gdp_series.empty else None
    y2_raw, _ = df_.get_price("^IRX")
    y10_raw, _ = df_.get_price("^TNX")
    y2 = (y2_raw / 100) if y2_raw is not None else None
    y10 = (y10_raw / 100) if y10_raw is not None else None
    inverted = (y2 is not None and y10 is not None and y2 > y10)

    if debt_to_gdp is not None and debt_to_gdp > 120 and inverted:
        phase = "Late-Stage Long-Term Debt Cycle"
        phase_color = "#FF4B4B"
    elif debt_to_gdp is not None and debt_to_gdp > 100:
        phase = "Mid-to-Late Long-Term Debt Cycle"
        phase_color = "#FFC107"
    else:
        phase = "Mid Long-Term Debt Cycle"
        phase_color = "#00FF94"

    st.markdown(
        f"<h3 style='color:{phase_color}'>Current Phase: {phase}</h3>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Debt/GDP: {_fmt(debt_to_gdp, '%')} · "
        f"2y/10y: {'Inverted' if inverted else 'Positive'}"
    )

    # ---- Short-term ----
    st.subheader("Short-Term Cycle Indicators")

    fed_funds, fed_funds_prior = df_.fred_latest("FEDFUNDS")
    cpi_yoy, cpi_yoy_prior = df_.fred_yoy("CPIAUCSL")
    pce_yoy, pce_yoy_prior = df_.fred_yoy("PCEPILFE")
    m2_yoy, m2_yoy_prior = df_.fred_yoy("M2SL")
    bank_credit_yoy, bank_credit_yoy_prior = df_.fred_yoy("TOTBKCR")
    consumer_credit_yoy, consumer_credit_yoy_prior = df_.fred_yoy("TOTALSL")

    short_term = [
        ("Fed Funds Rate", "FEDFUNDS", fed_funds,
         (fed_funds - fed_funds_prior) if (fed_funds and fed_funds_prior) else None,
         "%", " pp"),
        ("CPI YoY", "CPIAUCSL_yoy", cpi_yoy,
         (cpi_yoy - cpi_yoy_prior) if (cpi_yoy and cpi_yoy_prior) else None,
         "%", " pp"),
        ("Core PCE YoY", "PCEPILFE_yoy", pce_yoy,
         (pce_yoy - pce_yoy_prior) if (pce_yoy and pce_yoy_prior) else None,
         "%", " pp"),
        ("M2 YoY", "M2SL_yoy", m2_yoy,
         (m2_yoy - m2_yoy_prior) if (m2_yoy and m2_yoy_prior) else None,
         "%", " pp"),
        ("Bank Credit YoY", "TOTBKCR_yoy", bank_credit_yoy,
         (bank_credit_yoy - bank_credit_yoy_prior) if (bank_credit_yoy and bank_credit_yoy_prior) else None,
         "%", " pp"),
        ("Consumer Credit YoY", "TOTALSL_yoy", consumer_credit_yoy,
         (consumer_credit_yoy - consumer_credit_yoy_prior) if (consumer_credit_yoy and consumer_credit_yoy_prior) else None,
         "%", " pp"),
    ]

    cols = st.columns(3)
    for i, (label, key, value, delta, vsuffix, dsuffix) in enumerate(short_term):
        with cols[i % 3]:
            _metric_card(label, value, delta, value_suffix=vsuffix, delta_suffix=dsuffix)
            _sparkline(key, label, chart_key=f"spark_st_{key}_{i}")

    # ---- Long-term ----
    st.subheader("Long-Term Cycle Indicators")

    debt_to_gdp_now, debt_to_gdp_prior = df_.fred_latest("GFDEGDQ188S")
    total_debt_now, total_debt_prior = df_.fred_latest("GFDEBTN")
    interest_pay = df_.fred_series("A091RC1Q027SBEA")
    revenue = df_.fred_series("W006RC1Q027SBEA")
    interest_pct = None
    interest_pct_prior = None
    if not interest_pay.empty and not revenue.empty:
        ratio = (interest_pay / revenue * 100).dropna()
        if len(ratio) >= 1:
            interest_pct = float(ratio.iloc[-1])
        if len(ratio) >= 2:
            interest_pct_prior = float(ratio.iloc[-2])
    dsr_now, dsr_prior = df_.fred_latest("TDSP")
    hy_now, hy_prior = df_.fred_latest("BAMLH0A0HYM2")
    delinq_now, delinq_prior = df_.fred_latest("DRCCLACBS")

    long_term = [
        ("Federal Debt / GDP", "GFDEGDQ188S", debt_to_gdp_now,
         (debt_to_gdp_now - debt_to_gdp_prior) if (debt_to_gdp_now and debt_to_gdp_prior) else None,
         "%", " pp"),
        ("Total Public Debt ($B)", "GFDEBTN",
         total_debt_now / 1000 if total_debt_now else None,
         ((total_debt_now - total_debt_prior) / 1000) if (total_debt_now and total_debt_prior) else None,
         "B", " B"),
        ("Interest / Revenue", "INTEREST_RATIO", interest_pct,
         (interest_pct - interest_pct_prior) if (interest_pct and interest_pct_prior) else None,
         "%", " pp"),
        ("HH Debt Service Ratio", "TDSP", dsr_now,
         (dsr_now - dsr_prior) if (dsr_now and dsr_prior) else None,
         "%", " pp"),
        ("HY Credit Spread", "BAMLH0A0HYM2", hy_now,
         (hy_now - hy_prior) if (hy_now and hy_prior) else None,
         "%", " pp"),
        ("Consumer Loan Delinq.", "DRCCLACBS", delinq_now,
         (delinq_now - delinq_prior) if (delinq_now and delinq_prior) else None,
         "%", " pp"),
    ]
    cols = st.columns(3)
    for i, (label, key, value, delta, vsuffix, dsuffix) in enumerate(long_term):
        with cols[i % 3]:
            _metric_card(label, value, delta, value_suffix=vsuffix, delta_suffix=dsuffix)
            _sparkline_10y(key, label, chart_key=f"spark_lt_{key}_{i}")

    st.subheader("US Federal Debt to GDP (1970–present)")
    st.plotly_chart(_debt_to_gdp_chart(), use_container_width=True, key="debt_gdp_chart")

    st.subheader("M2 Money Supply vs CPI (last 20 years)")
    st.plotly_chart(_m2_vs_cpi_chart(), use_container_width=True, key="debt_m2_cpi")
    _last_updated()


def _sparkline(key, label, chart_key):
    series_id = key.replace("_yoy", "")
    s = df_.fred_series(series_id)
    if s.empty:
        return
    if key.endswith("_yoy"):
        s = (s.pct_change(periods=12) * 100).dropna()
    s = _last(s, 2) if not s.empty else s
    if s.empty:
        return
    fig = go.Figure(go.Scatter(x=s.index, y=s.values, mode="lines",
                               line=dict(color="#00FF94", width=2)))
    fig.update_layout(height=80, margin=dict(l=0, r=0, t=0, b=0),
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      template="plotly_dark", showlegend=False)
    st.plotly_chart(fig, use_container_width=True, key=chart_key)


def _sparkline_10y(key, label, chart_key):
    if key == "INTEREST_RATIO":
        ip = df_.fred_series("A091RC1Q027SBEA")
        rv = df_.fred_series("W006RC1Q027SBEA")
        if ip.empty or rv.empty:
            return
        s = _last((ip / rv * 100).dropna(), 10)
    else:
        s = df_.fred_series(key)
        if s.empty:
            return
        s = _last(s, 10)
    if s.empty:
        return
    fig = go.Figure(go.Scatter(x=s.index, y=s.values, mode="lines",
                               line=dict(color="#00FF94", width=2)))
    fig.update_layout(height=100, margin=dict(l=0, r=0, t=0, b=0),
                      xaxis=dict(visible=False), yaxis=dict(visible=True),
                      template="plotly_dark", showlegend=False)
    st.plotly_chart(fig, use_container_width=True, key=chart_key)


def _debt_to_gdp_chart():
    s = df_.fred_series("GFDEGDQ188S", observation_start="1970-01-01")
    rec = df_.fred_series("USREC", observation_start="1970-01-01")
    fig = go.Figure()
    if not s.empty:
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines",
                                 name="Debt/GDP", line=dict(color="#00FF94", width=2)))
        current = float(s.iloc[-1])
        fig.add_hline(y=current, line=dict(color="#FFC107", dash="dash"),
                      annotation_text=f"Current: {current:.0f}%")
    if not rec.empty:
        rec.index = pd.to_datetime(rec.index)
        in_recession = False
        start = None
        for date, val in rec.items():
            if val == 1 and not in_recession:
                start = date
                in_recession = True
            elif val == 0 and in_recession:
                fig.add_vrect(x0=start, x1=date, fillcolor="gray",
                              opacity=0.2, line_width=0)
                in_recession = False
        if in_recession and start is not None:
            fig.add_vrect(x0=start, x1=rec.index[-1], fillcolor="gray",
                          opacity=0.2, line_width=0)
    fig.update_layout(height=420, template="plotly_dark",
                      margin=dict(l=20, r=20, t=20, b=20),
                      yaxis_title="% of GDP")
    return fig


def _m2_vs_cpi_chart():
    m2 = df_.fred_series("M2SL", observation_start="2005-01-01")
    cpi = df_.fred_series("CPIAUCSL", observation_start="2005-01-01")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if not m2.empty:
        fig.add_trace(go.Scatter(x=m2.index, y=m2.values, mode="lines",
                                 name="M2 ($B)", line=dict(color="#00FF94")),
                      secondary_y=False)
    if not cpi.empty:
        fig.add_trace(go.Scatter(x=cpi.index, y=cpi.values, mode="lines",
                                 name="CPI Index", line=dict(color="#FFC107")),
                      secondary_y=True)
    fig.update_layout(height=420, template="plotly_dark",
                      margin=dict(l=20, r=20, t=20, b=20),
                      legend=dict(orientation="h", y=1.05))
    fig.update_yaxes(title_text="M2 ($B)", secondary_y=False)
    fig.update_yaxes(title_text="CPI Index", secondary_y=True)
    return fig


# ---------------------------------------------------------------------------
# Tab 3 — Bonds
# ---------------------------------------------------------------------------
def render_bonds():
    st.header("Bonds & Yield Curve")

    curve = df_.yield_curve_snapshot()
    if curve.empty or curve["current"].isna().all():
        st.warning("Yield curve data unavailable (FRED key missing).")
    else:
        fig = go.Figure()
        for col, label, color in [
            ("two_years_ago", "2 Years Ago", "#666666"),
            ("year_ago", "1 Year Ago", "#FFC107"),
            ("current", "Current", "#00FF94"),
        ]:
            fig.add_trace(go.Scatter(
                x=curve["tenor"], y=curve[col], mode="lines+markers",
                name=label, line=dict(color=color,
                                       width=3 if col == "current" else 2)))
        fig.update_layout(height=420, template="plotly_dark",
                          margin=dict(l=20, r=20, t=20, b=20),
                          xaxis_title="Tenor", yaxis_title="Yield (%)",
                          legend=dict(orientation="h", y=1.05))
        st.plotly_chart(fig, use_container_width=True, key="yield_curve_chart")

    st.subheader("Key Spreads")
    y3m, _ = df_.fred_latest("DGS3MO")
    y2, _ = df_.fred_latest("DGS2")
    y10, _ = df_.fred_latest("DGS10")
    y30, _ = df_.fred_latest("DGS30")
    hy, _ = df_.fred_latest("BAMLH0A0HYM2")
    ig, _ = df_.fred_latest("BAMLC0A0CM")

    cols = st.columns(5)
    s_2_10 = (y10 - y2) * 100 if (y10 and y2) else None
    s_3m_10 = (y10 - y3m) * 100 if (y10 and y3m) else None
    s_10_30 = (y30 - y10) * 100 if (y30 and y10) else None
    with cols[0]:
        st.metric("2Y/10Y Spread",
                  f"{s_2_10:+.0f} bps" if s_2_10 is not None else "—",
                  delta="Inverted" if (s_2_10 is not None and s_2_10 < 0) else "Positive",
                  delta_color="inverse" if (s_2_10 is not None and s_2_10 < 0) else "normal")
    with cols[1]:
        st.metric("3M/10Y Spread",
                  f"{s_3m_10:+.0f} bps" if s_3m_10 is not None else "—",
                  delta="Inverted" if (s_3m_10 is not None and s_3m_10 < 0) else "Positive",
                  delta_color="inverse" if (s_3m_10 is not None and s_3m_10 < 0) else "normal")
    with cols[2]:
        st.metric("10Y/30Y Spread",
                  f"{s_10_30:+.0f} bps" if s_10_30 is not None else "—")
    with cols[3]:
        _metric_card("HY Credit Spread", hy, value_suffix="%")
    with cols[4]:
        _metric_card("IG Credit Spread", ig, value_suffix="%")

    if s_2_10 is not None and s_2_10 < 0:
        st.error("Yield curve inverted (2Y > 10Y). Historical recession signal.")

    st.subheader("Inflation Expectations")
    be5, _ = df_.fred_latest("T5YIE")
    be10, _ = df_.fred_latest("T10YIE")
    fwd5y5y, _ = df_.fred_latest("T5YIFR")
    cols = st.columns(3)
    with cols[0]:
        _metric_card("5Y Breakeven", be5, value_suffix="%")
    with cols[1]:
        _metric_card("10Y Breakeven", be10, value_suffix="%")
    with cols[2]:
        _metric_card("5Y5Y Forward", fwd5y5y, value_suffix="%")

    fig = go.Figure()
    for series_id, label, color in [("T5YIE", "5Y Breakeven", "#00FF94"),
                                     ("T10YIE", "10Y Breakeven", "#FFC107"),
                                     ("T5YIFR", "5Y5Y Forward", "#FF6B9D")]:
        s = df_.fred_series(series_id)
        if s.empty:
            continue
        s = _last(s, 2)
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines",
                                 name=label, line=dict(color=color)))
    fig.update_layout(height=320, template="plotly_dark",
                      margin=dict(l=20, r=20, t=20, b=20),
                      legend=dict(orientation="h", y=1.05),
                      yaxis_title="%")
    st.plotly_chart(fig, use_container_width=True, key="bonds_inflation_exp")

    st.subheader("Bond ETFs")
    bond_etfs = {"TLT": "TLT (20Y+ Treasury)", "IEF": "IEF (7-10Y)",
                 "HYG": "HYG (High Yield)", "LQD": "LQD (Inv Grade)",
                 "TIP": "TIP (TIPS)"}
    quotes = df_.yf_quotes(list(bond_etfs.keys()))
    cols = st.columns(5)
    for col, (ticker, label) in zip(cols, bond_etfs.items()):
        q = quotes[ticker]
        with col:
            _metric_card(label, q["price"], q["change_pct"])

    fig = _normalized_performance_chart(bond_etfs, period="1y")
    st.plotly_chart(fig, use_container_width=True, key="bonds_etfs_norm")
    _last_updated()


# ---------------------------------------------------------------------------
# Tab 4 — Macro Data
# ---------------------------------------------------------------------------
def render_macro():
    st.header("Macro Data")

    st.subheader("US Economic Indicators")
    indicators = [
        ("CPI Headline YoY", "CPIAUCSL", "yoy", "%"),
        ("Core CPI YoY", "CPILFESL", "yoy", "%"),
        ("PCE YoY", "PCEPI", "yoy", "%"),
        ("Core PCE YoY", "PCEPILFE", "yoy", "%"),
        ("Unemployment Rate", "UNRATE", "level", "%"),
        ("Nonfarm Payrolls (MoM, K)", "PAYEMS", "diff", "K"),
        ("ISM Mfg PMI proxy (NAPM)", "NAPM", "level", ""),
        ("Retail Sales MoM", "RSAFS", "pct_change", "%"),
        ("Industrial Production", "INDPRO", "level", ""),
        ("Housing Starts (K)", "HOUST", "level", "K"),
        ("Consumer Sentiment", "UMCSENT", "level", ""),
        ("GDP Growth Rate", "A191RL1Q225SBEA", "level", "%"),
    ]
    rows = []
    for label, series_id, mode, suffix in indicators:
        s = df_.fred_series(series_id)
        if s.empty or len(s) < 2:
            rows.append({"Indicator": label, "Current": "—", "Prior": "—",
                         "Change": "—", "Direction": "—"})
            continue
        if mode == "yoy":
            yoy = (s.pct_change(periods=12) * 100).dropna()
            current = float(yoy.iloc[-1])
            prior = float(yoy.iloc[-2])
        elif mode == "pct_change":
            pc = (s.pct_change() * 100).dropna()
            current = float(pc.iloc[-1])
            prior = float(pc.iloc[-2]) if len(pc) > 1 else None
        elif mode == "diff":
            d = s.diff().dropna()
            current = float(d.iloc[-1])
            prior = float(d.iloc[-2]) if len(d) > 1 else None
        else:
            current = float(s.iloc[-1])
            prior = float(s.iloc[-2])
        change = (current - prior) if prior is not None else None
        if change is None:
            arrow = "—"
        elif change > 0:
            arrow = "▲"
        elif change < 0:
            arrow = "▼"
        else:
            arrow = "—"
        rows.append({
            "Indicator": label,
            "Current": f"{current:,.2f}{suffix}",
            "Prior": f"{prior:,.2f}{suffix}" if prior is not None else "—",
            "Change": f"{change:+.2f}" if change is not None else "—",
            "Direction": arrow,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**CPI vs Core PCE YoY (5y)**")
        fig = go.Figure()
        for sid, label, color in [("CPIAUCSL", "CPI", "#00FF94"),
                                   ("PCEPILFE", "Core PCE", "#FFC107")]:
            s = df_.fred_series(sid)
            if s.empty:
                continue
            yoy = _last((s.pct_change(periods=12) * 100).dropna(), 5)
            fig.add_trace(go.Scatter(x=yoy.index, y=yoy.values, mode="lines",
                                     name=label, line=dict(color=color)))
        fig.update_layout(height=300, template="plotly_dark",
                          margin=dict(l=20, r=20, t=20, b=20),
                          legend=dict(orientation="h", y=1.05))
        st.plotly_chart(fig, use_container_width=True, key="macro_cpi_pce")

        st.markdown("**GDP Growth Rate (10y)**")
        s = df_.fred_series("A191RL1Q225SBEA")
        fig = go.Figure()
        if not s.empty:
            s = _last(s, 10)
            fig.add_trace(go.Bar(x=s.index, y=s.values, name="GDP",
                                 marker_color="#00FF94"))
        fig.update_layout(height=300, template="plotly_dark",
                          margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig, use_container_width=True, key="macro_gdp")

    with c2:
        st.markdown("**Unemployment Rate (10y)**")
        s = df_.fred_series("UNRATE")
        fig = go.Figure()
        if not s.empty:
            s = _last(s, 10)
            fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines",
                                     line=dict(color="#FF6B9D", width=2)))
        fig.update_layout(height=300, template="plotly_dark",
                          margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig, use_container_width=True, key="macro_unemployment")

        st.markdown("**Retail Sales (5y)**")
        s = df_.fred_series("RSAFS")
        fig = go.Figure()
        if not s.empty:
            s = _last(s, 5)
            fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines",
                                     line=dict(color="#FFC107", width=2)))
        fig.update_layout(height=300, template="plotly_dark",
                          margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig, use_container_width=True, key="macro_retail")

    st.divider()
    st.subheader("Global Indicators")
    quotes = df_.yf_quotes(list(df_.GLOBAL_ETFS.keys()))
    cols = st.columns(6)
    for col, (ticker, label) in zip(cols, df_.GLOBAL_ETFS.items()):
        q = quotes[ticker]
        with col:
            _metric_card(label, q["price"], q["change_pct"])
    _last_updated()


# ---------------------------------------------------------------------------
# Tab 5 — Commodities
# ---------------------------------------------------------------------------
def render_commodities():
    st.header("Commodities")

    energy = {"CL=F": "WTI Crude", "BZ=F": "Brent",
              "NG=F": "Natural Gas", "RB=F": "Gasoline"}
    metals = {"GC=F": "Gold", "SI=F": "Silver",
              "HG=F": "Copper", "PL=F": "Platinum"}
    agri = {"ZW=F": "Wheat", "ZC=F": "Corn",
            "ZS=F": "Soybeans", "KC=F": "Coffee"}

    for section, mapping in [("Energy", energy), ("Metals", metals),
                              ("Agriculture", agri)]:
        st.subheader(section)
        quotes = df_.yf_quotes(list(mapping.keys()))
        cols = st.columns(4)
        for col, (ticker, label) in zip(cols, mapping.items()):
            q = quotes[ticker]
            with col:
                st.metric(
                    label,
                    _fmt(q["price"]),
                    delta=(_delta_str(q["change_pct"]) or "—") + "  ·  1m: "
                          + (_delta_str(q["month_change_pct"]) or "—"),
                )

    st.divider()
    st.subheader("Macro Signals")
    gold_q = df_.yf_quote("GC=F")
    copper_q = df_.yf_quote("HG=F")
    wti_q = df_.yf_quote("CL=F")
    cu_au = (copper_q["price"] / gold_q["price"]) if (copper_q["price"] and gold_q["price"]) else None
    au_oil = (gold_q["price"] / wti_q["price"]) if (gold_q["price"] and wti_q["price"]) else None

    risk_signal = None
    cu_hist = df_.yf_history("HG=F", period="1y")
    au_hist = df_.yf_history("GC=F", period="1y")
    if not cu_hist.empty and not au_hist.empty:
        cu = cu_hist["Close"].dropna()
        au = au_hist["Close"].dropna()
        common = cu.index.intersection(au.index)
        if len(common) > 22:
            ratio = (cu.loc[common] / au.loc[common]).dropna()
            if len(ratio) > 22:
                risk_signal = "Risk-On" if ratio.iloc[-1] > ratio.iloc[-22] else "Risk-Off"

    cols = st.columns(3)
    with cols[0]:
        st.metric(
            "Copper/Gold Ratio",
            _fmt(cu_au, decimals=4),
            delta=risk_signal,
            delta_color="normal" if risk_signal == "Risk-On" else "inverse",
        )
    with cols[1]:
        _metric_card("Gold/Oil Ratio", au_oil)

    st.subheader("WTI — 50/200 day MA")
    st.plotly_chart(_price_with_mas("CL=F", "WTI Crude"),
                    use_container_width=True, key="commodities_wti_ma")
    st.subheader("Gold — 50/200 day MA")
    st.plotly_chart(_price_with_mas("GC=F", "Gold"),
                    use_container_width=True, key="commodities_gold_ma")

    st.subheader("1-Year Normalized Performance")
    fig = _normalized_performance_chart(
        {"CL=F": "WTI", "GC=F": "Gold", "HG=F": "Copper", "NG=F": "Nat Gas"},
        period="1y",
    )
    st.plotly_chart(fig, use_container_width=True, key="commodities_norm")
    _last_updated()


def _price_with_mas(ticker, label):
    hist = df_.yf_history(ticker, period="1y")
    fig = go.Figure()
    if hist.empty:
        return fig
    closes = hist["Close"].dropna()
    fig.add_trace(go.Scatter(x=closes.index, y=closes.values, mode="lines",
                             name=label, line=dict(color="#00FF94", width=2)))
    if len(closes) > 50:
        ma50 = closes.rolling(50).mean()
        fig.add_trace(go.Scatter(x=ma50.index, y=ma50.values, mode="lines",
                                 name="50d MA", line=dict(color="#FFC107", width=1)))
    if len(closes) > 200:
        ma200 = closes.rolling(200).mean()
        fig.add_trace(go.Scatter(x=ma200.index, y=ma200.values, mode="lines",
                                 name="200d MA", line=dict(color="#FF6B9D", width=1)))
    fig.update_layout(height=320, template="plotly_dark",
                      margin=dict(l=20, r=20, t=20, b=20),
                      legend=dict(orientation="h", y=1.05))
    return fig


# ---------------------------------------------------------------------------
# Tab 6 — Currencies
# ---------------------------------------------------------------------------
def render_fx():
    st.header("Currencies")

    dxy_q = df_.yf_quote("DX-Y.NYB")
    st.metric("DXY (US Dollar Index)", _fmt(dxy_q["price"]),
              delta=_delta_str(dxy_q["change_pct"]))
    dxy_hist = df_.yf_history("DX-Y.NYB", period="1y")
    if not dxy_hist.empty:
        fig = go.Figure(go.Scatter(x=dxy_hist.index, y=dxy_hist["Close"],
                                   mode="lines", line=dict(color="#00FF94", width=2)))
        fig.update_layout(height=300, template="plotly_dark",
                          margin=dict(l=20, r=20, t=20, b=20),
                          yaxis_title="DXY")
        st.plotly_chart(fig, use_container_width=True, key="fx_dxy_1y")

    st.subheader("Major Pairs")
    majors = {"EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD",
              "JPY=X": "USD/JPY", "CHF=X": "USD/CHF",
              "AUDUSD=X": "AUD/USD", "CAD=X": "USD/CAD"}
    quotes = df_.yf_quotes(list(majors.keys()))
    cols = st.columns(6)
    for col, (ticker, label) in zip(cols, majors.items()):
        q = quotes[ticker]
        with col:
            _metric_card(label, q["price"], q["change_pct"], decimals=4)

    st.subheader("EM & Strategic Pairs")
    em = {"CNY=X": "USD/CNY", "INR=X": "USD/INR",
          "BRL=X": "USD/BRL", "MXN=X": "USD/MXN",
          "SAR=X": "USD/SAR", "RUB=X": "USD/RUB"}
    quotes = df_.yf_quotes(list(em.keys()))
    cols = st.columns(6)
    for col, (ticker, label) in zip(cols, em.items()):
        q = quotes[ticker]
        with col:
            _metric_card(label, q["price"], q["change_pct"], decimals=4)

    st.subheader("Crypto as Macro Signal")
    crypto = {"BTC-USD": "Bitcoin", "ETH-USD": "Ethereum"}
    quotes = df_.yf_quotes(list(crypto.keys()))
    cols = st.columns(2)
    for col, (ticker, label) in zip(cols, crypto.items()):
        q = quotes[ticker]
        with col:
            _metric_card(label, q["price"], q["change_pct"])

    st.subheader("DXY vs EUR/USD vs USD/CNY (1y normalized)")
    fig = _normalized_performance_chart(
        {"DX-Y.NYB": "DXY", "EURUSD=X": "EUR/USD", "CNY=X": "USD/CNY"},
        period="1y",
    )
    st.plotly_chart(fig, use_container_width=True, key="fx_3way_norm")
    st.caption(
        "DXY strength = dollar hegemony signal. CNY weakness = capital flight / "
        "trade war pressure."
    )
    _last_updated()


# ---------------------------------------------------------------------------
# Tab 7 — Equities
# ---------------------------------------------------------------------------
def render_equities():
    st.header("Equities")

    st.subheader("Market Breadth")
    breadth = {"SPY": "S&P 500 (SPY)", "QQQ": "Nasdaq (QQQ)",
               "IWM": "Russell 2000 (IWM)", "DIA": "Dow (DIA)"}
    quotes = df_.yf_quotes(list(breadth.keys()))
    cols = st.columns(4)
    for col, (ticker, label) in zip(cols, breadth.items()):
        q = quotes[ticker]
        with col:
            _metric_card(label, q["price"], q["change_pct"])

    st.subheader("SPY — 50/200 day MA")
    st.plotly_chart(_price_with_mas("SPY", "SPY"),
                    use_container_width=True, key="equities_spy_ma")

    st.subheader("Sector Performance YTD")
    sector_data = []
    for ticker, label in df_.SECTOR_ETFS.items():
        ytd = df_.yf_ytd_change(ticker)
        if ytd is not None:
            sector_data.append({"sector": f"{ticker} — {label}", "ytd": ytd})
    if sector_data:
        sector_df = pd.DataFrame(sector_data).sort_values("ytd")
        colors = ["#00FF94" if v >= 0 else "#FF4B4B" for v in sector_df["ytd"]]
        fig = go.Figure(go.Bar(x=sector_df["ytd"], y=sector_df["sector"],
                               orientation="h", marker_color=colors))
        fig.update_layout(height=420, template="plotly_dark",
                          margin=dict(l=20, r=20, t=20, b=20),
                          xaxis_title="YTD %")
        st.plotly_chart(fig, use_container_width=True, key="equities_sectors")

    st.subheader("Major Stock Performance")
    quotes = df_.yf_quotes(df_.MAJOR_STOCKS)
    rows = []
    for ticker in df_.MAJOR_STOCKS:
        q = quotes[ticker]
        ytd = df_.yf_ytd_change(ticker)
        rows.append({"Ticker": ticker, "Price": _fmt(q["price"]),
                     "Daily %": _delta_str(q["change_pct"]) or "—",
                     "YTD %": f"{ytd:+.2f}%" if ytd is not None else "—"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("Recent Earnings — Last Reported Quarter")
    earnings_rows = []
    for ticker in df_.EARNINGS_STOCKS:
        e = df_.latest_earnings(ticker)
        earnings_rows.append({
            "Ticker": ticker,
            "Quarter": e.get("quarter") or "—",
            "Revenue": f"${e['revenue']/1e9:,.2f}B" if e["revenue"] else "—",
            "Rev YoY": f"{e['revenue_yoy']:+.2f}%" if e["revenue_yoy"] else "—",
            "EPS (TTM)": f"{e['eps']:.2f}" if e["eps"] is not None else "—",
            "Net Income": f"${e['net_income']/1e9:,.2f}B" if e["net_income"] else "—",
            "Gross Margin": f"{e['gross_margin']:.1f}%" if e["gross_margin"] else "—",
        })
    st.dataframe(pd.DataFrame(earnings_rows), use_container_width=True, hide_index=True)

    st.subheader("Analyst Headlines")
    if not df_.has_news():
        st.info("Set NEWS_API_KEY to populate this section.")
    else:
        for ticker in df_.EARNINGS_STOCKS:
            with st.expander(f"{ticker} — recent coverage"):
                articles = df_.get_stock_news(ticker)
                if not articles:
                    st.caption("No recent headlines.")
                    continue
                for a in articles:
                    st.markdown(
                        f"**[{a['title']}]({a['url']})** — "
                        f"_{a.get('source', '')} · {a.get('date', '')}_"
                    )
    _last_updated()


# ---------------------------------------------------------------------------
# Tab 8 — Portfolio & Thesis
# ---------------------------------------------------------------------------
def render_thesis():
    st.header("Portfolio & Thesis Tracker")
    st.caption("Thesis integrity monitor — no P&L, cost basis, or dollar amounts.")

    if not te.has_anthropic() or not df_.has_news():
        st.warning(
            "Thesis scoring requires both ANTHROPIC_API_KEY and NEWS_API_KEY."
        )

    if "thesis_results" not in st.session_state:
        st.session_state["thesis_results"] = {}

    if st.button("Re-Score All Theses", type="primary"):
        te.score_position.clear()
        with st.spinner("Pulling news and running Claude scoring..."):
            for key in te.POSITIONS:
                st.session_state["thesis_results"][key] = te.score_position(key)

    if not st.session_state["thesis_results"]:
        with st.spinner("Initial thesis scoring..."):
            for key in te.POSITIONS:
                st.session_state["thesis_results"][key] = te.score_position(key)

    results = st.session_state["thesis_results"]

    st.subheader("Summary")
    summary_rows = []
    for key, res in results.items():
        scores = res.get("scores") or {}
        overall = scores.get("overall_score")
        verdict = scores.get("overall_verdict") or (res.get("error") or "—")
        summary_rows.append({
            "Position": f"{res['name']} ({res['ticker']})",
            "Overall Score": f"{overall}/10" if overall is not None else "—",
            "Verdict": verdict,
            "Last Checked": res.get("timestamp", "—"),
        })
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    st.divider()

    for key, res in results.items():
        _render_position(key, res)
        st.divider()
    _last_updated()


def _render_position(key, res):
    st.subheader(f"{res['name']} ({res['ticker']})")
    with st.expander("Thesis"):
        st.write(res["thesis"])

    if res.get("error") and not res.get("scores"):
        st.error(res["error"])
        return

    scores = res.get("scores") or {}
    overall = scores.get("overall_score")
    pillar_scores = scores.get("pillar_scores") or []

    slug = key.lower()
    c1, c2 = st.columns([1, 2])
    with c1:
        st.plotly_chart(_score_gauge(overall),
                        use_container_width=True,
                        key=f"thesis_{slug}_gauge")
        verdict = scores.get("overall_verdict")
        if verdict:
            st.markdown(f"**Verdict:** {verdict}")

    with c2:
        if pillar_scores:
            labels = [p.get("pillar", "") for p in pillar_scores]
            values = [p.get("score", 0) for p in pillar_scores]
            colors = [_score_color(v) for v in values]
            fig = go.Figure(go.Bar(
                x=values, y=labels, orientation="h",
                marker_color=colors,
                text=[f"{v}/10" for v in values],
                textposition="auto",
            ))
            fig.update_layout(height=320, template="plotly_dark",
                              margin=dict(l=20, r=20, t=20, b=20),
                              xaxis=dict(range=[0, 10], title="Score"))
            st.plotly_chart(fig, use_container_width=True,
                            key=f"thesis_{slug}_pillars")
            with st.expander("Pillar reasoning"):
                for p in pillar_scores:
                    st.markdown(
                        f"- **{p.get('pillar', '')}** — {p.get('score', '?')}/10: "
                        f"{p.get('reasoning', '')}"
                    )

    confirming = scores.get("confirming_headlines") or []
    contradicting = scores.get("contradicting_headlines") or []
    c1, c2 = st.columns(2)
    with c1:
        with st.expander(f"Supporting Headlines ({len(confirming)})"):
            if confirming:
                for h in confirming:
                    st.markdown(
                        f"<span style='color:#00FF94'>✓</span> {h}",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("None.")
    with c2:
        with st.expander(f"Contradicting Headlines ({len(contradicting)})"):
            if contradicting:
                for h in contradicting:
                    st.markdown(
                        f"<span style='color:#FF4B4B'>✗</span> {h}",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("None.")

    st.caption(f"Last updated: {res.get('timestamp', '—')}")


def _score_gauge(score):
    if score is None:
        score = 0
    color = _score_color(score)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={"suffix": "/10"},
        gauge={
            "axis": {"range": [0, 10]},
            "bar": {"color": color},
            "steps": [
                {"range": [0, 4], "color": "#3a1a1a"},
                {"range": [4, 7], "color": "#3a3a1a"},
                {"range": [7, 10], "color": "#1a3a2a"},
            ],
        },
    ))
    fig.update_layout(height=260, template="plotly_dark",
                      margin=dict(l=10, r=10, t=20, b=10))
    return fig


def _score_color(score):
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "#888888"
    if s < 4:
        return "#FF4B4B"
    if s < 7:
        return "#FFC107"
    return "#00FF94"


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
with tab_overview:
    render_overview()
with tab_debt:
    render_debt_cycle()
with tab_bonds:
    render_bonds()
with tab_macro:
    render_macro()
with tab_commodities:
    render_commodities()
with tab_fx:
    render_fx()
with tab_equities:
    render_equities()
with tab_thesis:
    render_thesis()
