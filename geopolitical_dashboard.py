"""
Geopolitical Market Dashboard: USA-Iran-Israel Conflict Monitor
Tracks live market data across commodities, stocks, indices, sectors,
sovereign bonds, and currencies most affected by Middle East tensions.
"""

import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime, timedelta
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── Page Config ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Geopolitical Market Dashboard | USA-Iran-Israel",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Asset Definitions ────────────────────────────────────────────────────
ASSETS = {
    "Commodities": {
        "Crude Oil (WTI)":      "CL=F",
        "Brent Crude":          "BZ=F",
        "Natural Gas":          "NG=F",
        "Gold":                 "GC=F",
        "Silver":               "SI=F",
        "Platinum":             "PL=F",
        "Palladium":            "PA=F",
        "Wheat":                "ZW=F",
        "Corn":                 "ZC=F",
        "Copper":               "HG=F",
        "Uranium (Sprott)":     "SRUUF",
    },
    "Defense & Energy Stocks": {
        "Lockheed Martin":      "LMT",
        "Raytheon (RTX)":       "RTX",
        "Northrop Grumman":     "NOC",
        "General Dynamics":     "GD",
        "L3Harris":             "LHX",
        "Boeing":               "BA",
        "ExxonMobil":           "XOM",
        "Chevron":              "CVX",
        "ConocoPhillips":       "COP",
        "Halliburton":          "HAL",
        "Schlumberger":         "SLB",
        "Occidental Petroleum": "OXY",
    },
    "Country Indices": {
        "S&P 500 (USA)":        "^GSPC",
        "NASDAQ (USA)":         "^IXIC",
        "Dow Jones (USA)":      "^DJI",
        "FTSE 100 (UK)":        "^FTSE",
        "DAX (Germany)":        "^GDAXI",
        "CAC 40 (France)":      "^FCHI",
        "Nikkei 225 (Japan)":   "^N225",
        "Shanghai (China)":     "000001.SS",
        "SENSEX (India)":       "^BSESN",
        "TA-35 (Israel)":       "^TA125.TA",
        "Tadawul (Saudi)":      "^TASI.SR",
        "ADX (UAE)":            "^ADI",
        "Istanbul (Turkey)":    "XU100.IS",
        "EGX 30 (Egypt)":       "^EGX30.CA",
    },
    "Sector ETFs": {
        "Energy (XLE)":         "XLE",
        "Defense (ITA)":        "ITA",
        "Aerospace (PPA)":      "PPA",
        "Cybersecurity (CIBR)": "CIBR",
        "Utilities (XLU)":      "XLU",
        "Financials (XLF)":     "XLF",
        "Tech (XLK)":           "XLK",
        "Consumer Staples":     "XLP",
        "Materials (XLB)":      "XLB",
        "Industrials (XLI)":    "XLI",
        "Airlines (JETS)":      "JETS",
        "Shipping (SIA)":       "SIA",
    },
    "Sovereign Bonds & Safe Havens": {
        "US 10Y Treasury":      "^TNX",
        "US 30Y Treasury":      "^TYX",
        "US 5Y Treasury":       "^FVX",
        "US 2Y Treasury":       "2YY=F",
        "Germany 10Y Bund":     "BUND-10Y.DE",
        "Gold ETF (GLD)":       "GLD",
        "Silver ETF (SLV)":     "SLV",
        "Bitcoin":              "BTC-USD",
        "VIX (Fear Index)":     "^VIX",
        "MOVE Index ETF":       "IVOL",
    },
    "Currencies": {
        "USD Index (DXY)":      "DX-Y.NYB",
        "EUR/USD":              "EURUSD=X",
        "GBP/USD":              "GBPUSD=X",
        "USD/JPY":              "JPY=X",
        "USD/CHF":              "CHF=X",
        "USD/TRY":              "TRY=X",
        "USD/ILS":              "ILS=X",
        "USD/SAR":              "SAR=X",
        "USD/AED":              "AED=X",
        "USD/INR":              "INR=X",
        "USD/CNY":              "CNY=X",
        "USD/RUB":              "RUB=X",
        "USD/EGP":              "EGP=X",
        "XAU/USD (Gold)":       "XAUUSD=X",
    },
}

# ─── Styling ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 800;
        color: #FF4B4B;
        text-align: center;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 1rem;
        color: #888;
        text-align: center;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background: #1E1E1E;
        border-radius: 10px;
        padding: 12px 16px;
        margin: 4px 0;
        border-left: 4px solid #444;
    }
    .metric-card.up { border-left-color: #00C853; }
    .metric-card.down { border-left-color: #FF1744; }
    .section-title {
        font-size: 1.3rem;
        font-weight: 700;
        margin-top: 1.5rem;
        margin-bottom: 0.5rem;
        padding: 8px 12px;
        border-radius: 6px;
        background: linear-gradient(90deg, #1a1a2e, #16213e);
        color: #e0e0e0;
    }
    div[data-testid='stMetric'] {
        background-color: #0e1117;
        border: 1px solid #262730;
        border-radius: 8px;
        padding: 10px 14px;
    }
</style>
""", unsafe_allow_html=True)

# ─── Helper Functions ──────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def fetch_ticker_data(symbol, period="5d", interval="1d"):
    """Fetch data for a single ticker."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval)
        if hist.empty:
            return None
        info = {}
        try:
            info = ticker.fast_info
            info = {
                "currentPrice": getattr(info, "last_price", None),
                "previousClose": getattr(info, "previous_close", None),
            }
        except Exception:
            pass
        current = hist["Close"].iloc[-1]
        prev = hist["Close"].iloc[-2] if len(hist) >= 2 else current
        change = current - prev
        pct = (change / prev * 100) if prev != 0 else 0
        return {
            "price": current,
            "change": change,
            "pct_change": pct,
            "history": hist,
        }
    except Exception:
        return None


def fetch_all_data(assets_dict):
    """Fetch data for all tickers in parallel."""
    results = {}
    all_symbols = []
    for category, tickers in assets_dict.items():
        for name, symbol in tickers.items():
            all_symbols.append((category, name, symbol))

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {
            executor.submit(fetch_ticker_data, sym): (cat, name, sym)
            for cat, name, sym in all_symbols
        }
        for future in as_completed(futures):
            cat, name, sym = futures[future]
            if cat not in results:
                results[cat] = {}
            try:
                data = future.result()
                if data:
                    results[cat][name] = data
            except Exception:
                pass
    return results


def render_metric_card(name, data):
    """Render a single metric with price and change."""
    price = data["price"]
    change = data["change"]
    pct = data["pct_change"]
    direction = "up" if change >= 0 else "down"
    arrow = "+" if change >= 0 else ""
    change_color = "#00C853" if change >= 0 else "#FF1744"
    return (
        f'<div class="metric-card {direction}">'
        f'<div style="font-size:0.85rem;color:#aaa;margin-bottom:2px;">{name}</div>'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;">'
        f'<span style="font-size:1.2rem;font-weight:700;color:#fff;">'
        f'{price:,.2f}'
        f'</span>'
        f'<span style="font-size:0.9rem;color:{change_color};">'
        f'{arrow}{change:,.2f} ({arrow}{pct:.2f}%)'
        f'</span>'
        f'</div>'
        f'</div>'
    )


def make_sparkline(history, name):
    """Create a small sparkline chart."""
    fig = go.Figure()
    color = "#00C853" if history["Close"].iloc[-1] >= history["Close"].iloc[0] else "#FF1744"
    fig.add_trace(go.Scatter(
        x=history.index,
        y=history["Close"],
        mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy",
        fillcolor=color.replace(")", ",0.1)").replace("rgb", "rgba") if "rgb" in color else f"{color}18",
        name=name,
    ))
    fig.update_layout(
        height=120,
        margin=dict(l=0, r=0, t=20, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        title=dict(text=name, font=dict(size=11, color="#aaa"), x=0.02, y=0.95),
    )
    return fig


def make_category_chart(category_data, title):
    """Bar chart of % changes for a category."""
    names = list(category_data.keys())
    pcts = [category_data[n]["pct_change"] for n in names]
    colors = ["#00C853" if p >= 0 else "#FF1744" for p in pcts]

    fig = go.Figure(go.Bar(
        x=pcts,
        y=names,
        orientation="h",
        marker_color=colors,
        text=[f"{p:+.2f}%" for p in pcts],
        textposition="outside",
        textfont=dict(size=11),
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color="#e0e0e0")),
        height=max(300, len(names) * 35),
        margin=dict(l=10, r=40, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            title="% Change",
            gridcolor="#333",
            zerolinecolor="#555",
            color="#aaa",
        ),
        yaxis=dict(
            autorange="reversed",
            color="#aaa",
        ),
        font=dict(color="#ccc"),
    )
    return fig


def make_heatmap(all_data):
    """Create an overall heatmap of all assets."""
    categories = []
    names = []
    values = []
    for cat, items in all_data.items():
        for name, data in items.items():
            categories.append(cat)
            names.append(name)
            values.append(data["pct_change"])

    df = pd.DataFrame({"Category": categories, "Asset": names, "Change %": values})

    # Build heatmap per category
    fig = go.Figure()
    cats_unique = df["Category"].unique()
    for cat in cats_unique:
        sub = df[df["Category"] == cat].sort_values("Change %", ascending=False)
        fig.add_trace(go.Bar(
            name=cat,
            x=sub["Asset"],
            y=sub["Change %"],
            marker_color=[
                "#00C853" if v >= 0 else "#FF1744" for v in sub["Change %"]
            ],
            text=[f"{v:+.2f}%" for v in sub["Change %"]],
            textposition="outside",
            textfont=dict(size=9),
        ))

    fig.update_layout(
        title="All Assets % Change Overview",
        barmode="group",
        height=500,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(tickangle=-45, color="#aaa", gridcolor="#222"),
        yaxis=dict(title="% Change", color="#aaa", gridcolor="#333", zerolinecolor="#555"),
        font=dict(color="#ccc", size=10),
        legend=dict(orientation="h", y=1.12),
        margin=dict(b=120),
    )
    return fig


def get_top_movers(all_data, n=10):
    """Get top gainers and losers across all assets."""
    movers = []
    for cat, items in all_data.items():
        for name, data in items.items():
            movers.append({
                "Asset": name,
                "Category": cat,
                "Price": data["price"],
                "Change": data["change"],
                "Change %": data["pct_change"],
            })
    df = pd.DataFrame(movers)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    gainers = df.nlargest(n, "Change %")
    losers = df.nsmallest(n, "Change %")
    return gainers, losers


# ─── Sidebar ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Dashboard Controls")
    auto_refresh = st.checkbox("Auto-Refresh (30s)", value=True)
    selected_categories = st.multiselect(
        "Categories to Display",
        options=list(ASSETS.keys()),
        default=list(ASSETS.keys()),
    )
    chart_type = st.radio("Chart View", ["Bar Charts", "Sparklines", "Both"], index=2)
    st.markdown("---")
    st.markdown(
        "**Data Source:** Yahoo Finance (yfinance)  \n"
        "**Refresh Rate:** ~30 seconds  \n"
        "**Coverage:** 70+ instruments"
    )
    st.markdown("---")
    st.markdown(
        "**Conflict Context:**  \n"
        "Monitors assets sensitive to USA-Iran-Israel "
        "geopolitical tensions including energy supply "
        "disruption, defense spending, safe-haven flows, "
        "and regional market stress."
    )
    if st.button("Force Refresh Now"):
        st.cache_data.clear()
        st.rerun()

# ─── Header ───────────────────────────────────────────────────────────────
st.markdown('<div class="main-header">GEOPOLITICAL MARKET DASHBOARD</div>', unsafe_allow_html=True)
timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
st.markdown(
    f'<div class="sub-header">USA - IRAN - ISRAEL Conflict Monitor | '
    f'Live Market Data | Last Updated: {timestamp}</div>',
    unsafe_allow_html=True,
)

# ─── Data Loading ─────────────────────────────────────────────────────────
filtered_assets = {k: v for k, v in ASSETS.items() if k in selected_categories}

with st.spinner("Fetching live market data across 70+ instruments..."):
    all_data = fetch_all_data(filtered_assets)

if not all_data:
    st.error("Unable to fetch market data. Please check your connection and try again.")
    st.stop()

# ─── Top Movers Summary ──────────────────────────────────────────────────
gainers, losers = get_top_movers(all_data, n=8)

st.markdown("---")
col_g, col_l = st.columns(2)

with col_g:
    st.markdown("### Top Gainers")
    if not gainers.empty:
        for _, row in gainers.iterrows():
            st.markdown(
                f"**{row['Asset']}** ({row['Category']}) — "
                f"<span style='color:#00C853'>{row['Price']:,.2f} "
                f"({row['Change %']:+.2f}%)</span>",
                unsafe_allow_html=True,
            )

with col_l:
    st.markdown("### Top Losers")
    if not losers.empty:
        for _, row in losers.iterrows():
            st.markdown(
                f"**{row['Asset']}** ({row['Category']}) — "
                f"<span style='color:#FF1744'>{row['Price']:,.2f} "
                f"({row['Change %']:+.2f}%)</span>",
                unsafe_allow_html=True,
            )

# ─── Overall Heatmap ─────────────────────────────────────────────────────
st.markdown("---")
st.plotly_chart(make_heatmap(all_data), use_container_width=True)

# ─── Category Sections ───────────────────────────────────────────────────
for category in selected_categories:
    if category not in all_data or not all_data[category]:
        continue

    cat_data = all_data[category]
    st.markdown(f'<div class="section-title">{category}</div>', unsafe_allow_html=True)

    # Metrics row
    cols = st.columns(min(len(cat_data), 6))
    for i, (name, data) in enumerate(cat_data.items()):
        with cols[i % len(cols)]:
            arrow = "+" if data["change"] >= 0 else ""
            delta_color = "normal"
            st.metric(
                label=name,
                value=f"{data['price']:,.2f}",
                delta=f"{arrow}{data['pct_change']:.2f}%",
            )

    # Charts
    if chart_type in ["Bar Charts", "Both"]:
        st.plotly_chart(
            make_category_chart(cat_data, f"{category} — % Change"),
            use_container_width=True,
        )

    if chart_type in ["Sparklines", "Both"]:
        spark_cols = st.columns(min(len(cat_data), 4))
        for i, (name, data) in enumerate(cat_data.items()):
            if data["history"] is not None and not data["history"].empty:
                with spark_cols[i % len(spark_cols)]:
                    st.plotly_chart(
                        make_sparkline(data["history"], name),
                        use_container_width=True,
                    )

    st.markdown("---")

# ─── Risk Dashboard ──────────────────────────────────────────────────────
st.markdown('<div class="section-title">Geopolitical Risk Indicators</div>', unsafe_allow_html=True)

risk_col1, risk_col2, risk_col3, risk_col4 = st.columns(4)

# Extract key indicators
def safe_get(category, name, field="pct_change"):
    try:
        return all_data[category][name][field]
    except (KeyError, TypeError):
        return None

oil_chg = safe_get("Commodities", "Crude Oil (WTI)")
gold_chg = safe_get("Commodities", "Gold")
vix_price = safe_get("Sovereign Bonds & Safe Havens", "VIX (Fear Index)", "price")
dxy_chg = safe_get("Currencies", "USD Index (DXY)")

with risk_col1:
    if oil_chg is not None:
        st.metric("Oil Stress", f"{oil_chg:+.2f}%",
                  "Elevated" if abs(oil_chg) > 2 else "Normal",
                  delta_color="inverse")
    else:
        st.metric("Oil Stress", "N/A")

with risk_col2:
    if gold_chg is not None:
        st.metric("Gold Flight", f"{gold_chg:+.2f}%",
                  "Safe Haven Active" if gold_chg > 0.5 else "Calm",
                  delta_color="normal")
    else:
        st.metric("Gold Flight", "N/A")

with risk_col3:
    if vix_price is not None:
        level = "Extreme Fear" if vix_price > 30 else "Elevated" if vix_price > 20 else "Low"
        st.metric("VIX Fear Level", f"{vix_price:.1f}", level,
                  delta_color="inverse")
    else:
        st.metric("VIX Fear Level", "N/A")

with risk_col4:
    if dxy_chg is not None:
        st.metric("USD Strength", f"{dxy_chg:+.2f}%",
                  "Dollar Rally" if dxy_chg > 0.3 else "Weakening" if dxy_chg < -0.3 else "Stable")
    else:
        st.metric("USD Strength", "N/A")

# ─── Correlation Table ────────────────────────────────────────────────────
st.markdown('<div class="section-title">Key Conflict-Sensitive Correlations</div>', unsafe_allow_html=True)

key_assets = {
    "Oil (WTI)": ("Commodities", "Crude Oil (WTI)"),
    "Gold": ("Commodities", "Gold"),
    "Defense (ITA)": ("Sector ETFs", "Defense (ITA)"),
    "Energy (XLE)": ("Sector ETFs", "Energy (XLE)"),
    "S&P 500": ("Country Indices", "S&P 500 (USA)"),
    "TA-35 Israel": ("Country Indices", "TA-35 (Israel)"),
    "USD/ILS": ("Currencies", "USD/ILS"),
    "VIX": ("Sovereign Bonds & Safe Havens", "VIX (Fear Index)"),
}

# Gather 5-day close data for correlation
corr_data = {}
for label, (cat, name) in key_assets.items():
    try:
        hist = all_data[cat][name]["history"]
        if hist is not None and not hist.empty:
            corr_data[label] = hist["Close"].pct_change().dropna()
    except (KeyError, TypeError):
        pass

if len(corr_data) >= 2:
    corr_df = pd.DataFrame(corr_data)
    corr_matrix = corr_df.corr()

    fig_corr = go.Figure(data=go.Heatmap(
        z=corr_matrix.values,
        x=corr_matrix.columns,
        y=corr_matrix.index,
        colorscale="RdYlGn",
        zmin=-1, zmax=1,
        text=corr_matrix.round(2).values,
        texttemplate="%{text}",
        textfont=dict(size=11),
    ))
    fig_corr.update_layout(
        title="5-Day Return Correlations",
        height=450,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig_corr, use_container_width=True)

# ─── Footer ──────────────────────────────────────────────────────────────
st.markdown("---")
total_instruments = sum(len(v) for v in ASSETS.values())
st.markdown(
    f"<div style='text-align:center;color:#555;font-size:0.8rem;'>"
    f"Dashboard refreshes every 30 seconds | Data from Yahoo Finance | "
    f"Tracking {total_instruments} instruments | "
    f"Built for geopolitical risk monitoring"
    f"</div>",
    unsafe_allow_html=True,
)

# ─── Auto-refresh ────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(30)
    st.rerun()
