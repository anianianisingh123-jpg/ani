"""
Geopolitical Market Dashboard: USA-Iran-Israel Conflict Monitor
"""
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# ─── Force Dark Theme ─────────────────
st.set_page_config(
    page_title="Geopolitical Market Dashboard | USA-Iran-Israel",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown("""
<style>
    [data-testid="stAppViewContainer"] { background-color: #0E1117 !important; }
    [data-testid="stSidebar"] { background-color: #161B26 !important; }
    .main-header { font-size: 2.2rem; font-weight: 800; color: #FF4B4B; text-align: center; margin-bottom: 0; }
    .sub-header { font-size: 1rem; color: #888; text-align: center; margin-bottom: 1.5rem; }
    .section-title { font-size: 1.3rem; font-weight: 700; margin-top: 1.5rem; margin-bottom: 0.5rem; padding: 8px 12px; border-radius: 6px; background: linear-gradient(90deg, #1a1a2e, #16213e); color: #e0e0e0; }
    .news-card { background:#1E1E1E; border-radius:12px; padding:16px; margin:8px 0; border-left:5px solid #FF1744; }
    div[data-testid='stMetric'] { background-color: #0e1117; border: 1px solid #262730; border-radius: 8px; padding: 10px 14px; }
</style>
""", unsafe_allow_html=True)

# ─── Asset Definitions ─────────────────────────────────────
ASSETS = {
    "Commodities": {"Crude Oil (WTI)": "CL=F", "Brent Crude": "BZ=F", "Natural Gas": "NG=F", "Gold": "GC=F", "Silver": "SI=F", "Platinum": "PL=F", "Palladium": "PA=F", "Wheat": "ZW=F", "Corn": "ZC=F", "Copper": "HG=F", "Uranium (Sprott)": "SRUUF"},
    "Defense & Energy Stocks": {"Lockheed Martin": "LMT", "Raytheon (RTX)": "RTX", "Northrop Grumman": "NOC", "General Dynamics": "GD", "L3Harris": "LHX", "Boeing": "BA", "ExxonMobil": "XOM", "Chevron": "CVX", "ConocoPhillips": "COP", "Halliburton": "HAL", "Schlumberger": "SLB", "Occidental Petroleum": "OXY"},
    "Country Indices": {"S&P 500 (USA)": "^GSPC", "NASDAQ (USA)": "^IXIC", "Dow Jones (USA)": "^DJI", "FTSE 100 (UK)": "^FTSE", "DAX (Germany)": "^GDAXI", "CAC 40 (France)": "^FCHI", "Nikkei 225 (Japan)": "^N225", "Shanghai (China)": "000001.SS", "SENSEX (India)": "^BSESN", "TA-35 (Israel)": "^TA125.TA", "Tadawul (Saudi)": "^TASI.SR", "ADX (UAE)": "^ADI", "Istanbul (Turkey)": "XU100.IS", "EGX 30 (Egypt)": "^EGX30.CA"},
    "Sector ETFs": {"Energy (XLE)": "XLE", "Defense (ITA)": "ITA", "Aerospace (PPA)": "PPA", "Cybersecurity (CIBR)": "CIBR", "Utilities (XLU)": "XLU", "Financials (XLF)": "XLF", "Tech (XLK)": "XLK", "Consumer Staples": "XLP", "Materials (XLB)": "XLB", "Industrials (XLI)": "XLI", "Airlines (JETS)": "JETS", "Shipping (SIA)": "SIA"},
    "Sovereign Bonds & Safe Havens": {"US 10Y Treasury": "^TNX", "US 30Y Treasury": "^TYX", "US 5Y Treasury": "^FVX", "US 2Y Treasury": "2YY=F", "Germany 10Y Bund": "BUND-10Y.DE", "Gold ETF (GLD)": "GLD", "Silver ETF (SLV)": "SLV", "Bitcoin": "BTC-USD", "VIX (Fear Index)": "^VIX", "MOVE Index ETF": "IVOL"},
    "Currencies": {"USD Index (DXY)": "DX-Y.NYB", "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X", "USD/CHF": "CHF=X", "USD/TRY": "TRY=X", "USD/ILS": "ILS=X", "USD/SAR": "SAR=X", "USD/AED": "AED=X", "USD/INR": "INR=X", "USD/CNY": "CNY=X", "USD/RUB": "RUB=X", "USD/EGP": "EGP=X", "XAU/USD (Gold)": "XAUUSD=X"},
}

# ─── ROBUST DATA COLLECTION ─────────────────────────────
# KEY FIX: Fetch 1 month of history so the correlation chart has ~20 data
# points.  The old code fetched only 2 days, which left just 1 row after
# pct_change().dropna() -- making every correlation NaN.

@st.cache_data(ttl=30, show_spinner=False)
def fetch_ticker_data(symbol):
    """Fetch price + 1-month history for a single ticker with retry."""
    for attempt in range(3):
        try:
            ticker = yf.Ticker(symbol)

            # Pull 1 month of daily history -- enough for sparklines AND correlation
            hist = ticker.history(period="1mo", interval="1d")

            # Drop any rows where Close is NaN (fixes Shanghai, Tadawul, etc.)
            if not hist.empty:
                hist = hist.dropna(subset=["Close"])

            if hist.empty or len(hist) < 1:
                raise ValueError("No valid Close data")

            current = float(hist["Close"].iloc[-1])

            # % change vs prior day: use the last two valid closes
            if len(hist) >= 2:
                prev = float(hist["Close"].iloc[-2])
            else:
                prev = current

            # Sanity-check: if prev is 0 or NaN, skip
            if prev == 0 or np.isnan(prev) or np.isnan(current):
                return None

            change = current - prev
            pct = (change / prev) * 100

            return {
                "price": round(current, 4),
                "change": round(change, 4),
                "pct_change": round(pct, 2),
                "history": hist,
            }

        except Exception:
            if attempt < 2:
                time.sleep(0.8 * (attempt + 1))
                continue
            return None


def fetch_all_data(assets_dict):
    """Fetch data for all tickers in parallel."""
    results = {}
    all_symbols = [
        (cat, name, sym)
        for cat, tickers in assets_dict.items()
        for name, sym in tickers.items()
    ]
    with ThreadPoolExecutor(max_workers=25) as executor:
        futures = {
            executor.submit(fetch_ticker_data, sym): (cat, name)
            for cat, name, sym in all_symbols
        }
        for future in as_completed(futures):
            cat, name = futures[future]
            if cat not in results:
                results[cat] = {}
            try:
                data = future.result()
                if data is not None:
                    results[cat][name] = data
            except Exception:
                pass
    return results

# ─── Helper Functions ──────────────────────────────────────────
def make_sparkline(history, name):
    fig = go.Figure()
    closes = history["Close"].dropna()
    if closes.empty:
        return fig
    color = "#00C853" if closes.iloc[-1] >= closes.iloc[0] else "#FF1744"
    fill_color = "rgba(0,200,83,0.1)" if color == "#00C853" else "rgba(255,23,68,0.1)"
    fig.add_trace(go.Scatter(
        x=closes.index, y=closes, mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy", fillcolor=fill_color,
    ))
    fig.update_layout(
        height=120, margin=dict(l=0, r=0, t=20, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False, xaxis=dict(visible=False), yaxis=dict(visible=False),
        title=dict(text=name, font=dict(size=11, color="#aaa"), x=0.02, y=0.95),
    )
    return fig


def make_category_chart(category_data, title):
    names = list(category_data.keys())
    pcts = [category_data[n]["pct_change"] for n in names]
    colors = ["#00C853" if p >= 0 else "#FF1744" for p in pcts]
    fig = go.Figure(go.Bar(
        x=pcts, y=names, orientation="h", marker_color=colors,
        text=[f"{p:+.2f}%" for p in pcts], textposition="outside", textfont=dict(size=11),
    ))
    fig.update_layout(
        title=title, height=max(300, len(names) * 35),
        margin=dict(l=10, r=40, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(title="% Change", color="#aaa"),
        yaxis=dict(autorange="reversed", color="#aaa"),
        font=dict(color="#ccc"),
    )
    return fig


def make_heatmap(all_data):
    categories, names, values = [], [], []
    for cat, items in all_data.items():
        for name, data in items.items():
            categories.append(cat)
            names.append(name)
            values.append(data["pct_change"])
    df = pd.DataFrame({"Category": categories, "Asset": names, "Change %": values})
    fig = go.Figure()
    for cat in df["Category"].unique():
        sub = df[df["Category"] == cat].sort_values("Change %", ascending=False)
        fig.add_trace(go.Bar(
            name=cat, x=sub["Asset"], y=sub["Change %"],
            marker_color=["#00C853" if v >= 0 else "#FF1744" for v in sub["Change %"]],
            text=[f"{v:+.2f}%" for v in sub["Change %"]], textposition="outside",
        ))
    fig.update_layout(
        title="All Assets % Change Overview", barmode="group", height=500,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(tickangle=-45, color="#aaa"),
        yaxis=dict(title="% Change", color="#aaa"),
        font=dict(color="#ccc"), legend=dict(orientation="h", y=1.12),
    )
    return fig


def get_top_movers(all_data, n=8):
    movers = []
    for cat, items in all_data.items():
        for name, data in items.items():
            movers.append({"Asset": name, "Category": cat, "Price": data["price"], "Change %": data["pct_change"]})
    df = pd.DataFrame(movers)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    return df.nlargest(n, "Change %"), df.nsmallest(n, "Change %")


# ─── News via RSS (feedparser optional) ─────
@st.cache_data(ttl=120)
def fetch_iran_usa_news():
    """Fetch Iran-USA conflict news from Google News RSS."""
    try:
        import feedparser
    except ImportError:
        return []
    try:
        rss_url = (
            "https://news.google.com/rss/search?"
            "q=Iran+US+war+OR+Iran+USA+conflict+OR+Iran+Israel+strike"
            "+OR+Tehran+Washington+OR+Hormuz+closure&hl=en-US&gl=US&ceid=US:en"
        )
        feed = feedparser.parse(rss_url)
        articles = []
        for entry in feed.entries[:12]:
            pub_time = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                dt = datetime(*entry.published_parsed[:6])
                pub_time = dt.strftime("%b %d, %Y %I:%M %p")
            else:
                pub_time = entry.get("published", "Just now")
            source = entry.get("source", {}).get("title", "Google News")
            summary = entry.get("summary", "")
            if len(summary) > 320:
                summary = summary[:320] + "..."
            articles.append({
                "title": entry.title,
                "published": pub_time,
                "source": source,
                "summary": summary,
                "link": entry.link,
            })
        return articles
    except Exception:
        return []


# ─── Sidebar ─────────────────────────────────────
with st.sidebar:
    st.markdown("## Dashboard Controls")
    selected_categories = st.multiselect(
        "Categories to Display",
        options=list(ASSETS.keys()),
        default=list(ASSETS.keys()),
    )
    chart_type = st.radio("Chart View", ["Bar Charts", "Sparklines", "Both"], index=2)
    st.markdown("---")
    if st.button("Refresh Dashboard Now", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("News is 100% automatic. Click the button above to update everything instantly.")

# ─── Header + Tabs ───────────────────────────────────────
st.markdown('<div class="main-header">GEOPOLITICAL MARKET DASHBOARD</div>', unsafe_allow_html=True)
timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
st.markdown(
    f'<div class="sub-header">USA - IRAN - ISRAEL Conflict Monitor | '
    f'Live Market Data | Last Updated: {timestamp}</div>',
    unsafe_allow_html=True,
)

tab_news, tab_markets, tab_risk = st.tabs([
    "Iran-USA War & Tensions - LIVE",
    "Markets",
    "Risk & Correlations",
])

# ─── NEWS TAB ────────────────────────
with tab_news:
    st.markdown('<div class="section-title">Iran-USA War & Tensions - LIVE</div>', unsafe_allow_html=True)
    st.caption("Most recent first. Powered by Google News RSS. Click Refresh Now for the latest headlines.")
    articles = fetch_iran_usa_news()
    if articles:
        cols = st.columns(3)
        for i, art in enumerate(articles):
            with cols[i % 3]:
                st.markdown(
                    f'<div class="news-card">'
                    f'<div style="font-size:0.85rem;color:#FF1744;">'
                    f'{art["source"]} - {art["published"]}</div>'
                    f'<strong>{art["title"]}</strong>'
                    f'<div style="font-size:0.9rem;color:#ddd;margin-top:8px;">'
                    f'{art["summary"]}</div>'
                    f'<a href="{art["link"]}" target="_blank" '
                    f'style="color:#00C853;margin-top:12px;display:block;">'
                    f'Read full story</a>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
    else:
        st.info("No current Iran-USA conflict news found. Install feedparser (`pip install feedparser`) to enable live news.")

# ─── MARKETS TAB ────────────────────────
with tab_markets:
    filtered_assets = {k: v for k, v in ASSETS.items() if k in selected_categories}
    with st.spinner("Fetching live market data..."):
        all_data = fetch_all_data(filtered_assets)
    if not all_data:
        st.error("Unable to fetch market data. Please check your connection and try again.")
        st.stop()

    gainers, losers = get_top_movers(all_data, n=8)
    col_g, col_l = st.columns(2)
    with col_g:
        st.markdown("### Top Gainers")
        if not gainers.empty:
            for _, row in gainers.iterrows():
                st.markdown(
                    f"**{row['Asset']}** ({row['Category']}) -- "
                    f"<span style='color:#00C853'>{row['Price']:,.2f} "
                    f"({row['Change %']:+.2f}%)</span>",
                    unsafe_allow_html=True,
                )
    with col_l:
        st.markdown("### Top Losers")
        if not losers.empty:
            for _, row in losers.iterrows():
                st.markdown(
                    f"**{row['Asset']}** ({row['Category']}) -- "
                    f"<span style='color:#FF1744'>{row['Price']:,.2f} "
                    f"({row['Change %']:+.2f}%)</span>",
                    unsafe_allow_html=True,
                )
    st.markdown("---")
    st.plotly_chart(make_heatmap(all_data), use_container_width=True)

    for category in selected_categories:
        if category not in all_data or not all_data[category]:
            continue
        cat_data = all_data[category]
        st.markdown(f'<div class="section-title">{category}</div>', unsafe_allow_html=True)
        cols = st.columns(min(len(cat_data), 6))
        for i, (name, data) in enumerate(cat_data.items()):
            with cols[i % len(cols)]:
                st.metric(
                    label=name,
                    value=f"{data['price']:,.2f}",
                    delta=f"{data['pct_change']:+.2f}%",
                )
        if chart_type in ["Bar Charts", "Both"]:
            st.plotly_chart(
                make_category_chart(cat_data, f"{category} -- % Change"),
                use_container_width=True,
            )
        if chart_type in ["Sparklines", "Both"]:
            spark_cols = st.columns(min(len(cat_data), 4))
            for i, (name, data) in enumerate(cat_data.items()):
                hist = data.get("history")
                if hist is not None and not hist.empty:
                    with spark_cols[i % len(spark_cols)]:
                        st.plotly_chart(make_sparkline(hist, name), use_container_width=True)
        st.markdown("---")

# ─── RISK TAB (CORRELATION FIX) ────────────────────────
with tab_risk:
    st.markdown('<div class="section-title">Geopolitical Risk Indicators</div>', unsafe_allow_html=True)
    risk_col1, risk_col2, risk_col3, risk_col4 = st.columns(4)

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
        st.metric("Oil Stress", f"{oil_chg:+.2f}%" if oil_chg is not None else "N/A")
    with risk_col2:
        st.metric("Gold Flight", f"{gold_chg:+.2f}%" if gold_chg is not None else "N/A")
    with risk_col3:
        st.metric("VIX Fear Level", f"{vix_price:.1f}" if vix_price is not None else "N/A")
    with risk_col4:
        st.metric("USD Strength", f"{dxy_chg:+.2f}%" if dxy_chg is not None else "N/A")

    # ─── CORRELATION MATRIX (FIXED) ──────────────────────────────────
    st.markdown('<div class="section-title">Key Conflict-Sensitive Correlations</div>', unsafe_allow_html=True)

    key_assets = {
        "Oil (WTI)": ("Commodities", "Crude Oil (WTI)"),
        "Gold": ("Commodities", "Gold"),
        "Defense (ITA)": ("Sector ETFs", "Defense (ITA)"),
        "Energy (XLE)": ("Sector ETFs", "Energy (XLE)"),
        "S&P 500": ("Country Indices", "S&P 500 (USA)"),
        "VIX": ("Sovereign Bonds & Safe Havens", "VIX (Fear Index)"),
    }

    # Build a dict of daily return series from the 1-month history
    corr_series = {}
    debug_info = []
    for label, (cat, name) in key_assets.items():
        try:
            if cat not in all_data or name not in all_data[cat]:
                debug_info.append(f"{label}: not in fetched data")
                continue
            hist = all_data[cat][name].get("history")
            if hist is None or hist.empty:
                debug_info.append(f"{label}: empty history")
                continue
            closes = hist["Close"].dropna()
            if len(closes) < 5:
                debug_info.append(f"{label}: only {len(closes)} close prices (need 5+)")
                continue
            returns = closes.pct_change().dropna()
            returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
            if len(returns) < 4:
                debug_info.append(f"{label}: only {len(returns)} returns after cleanup")
                continue
            corr_series[label] = returns
            debug_info.append(f"{label}: OK ({len(returns)} data points)")
        except Exception as e:
            debug_info.append(f"{label}: error - {e}")

    if len(corr_series) >= 2:
        # Align all series to their common date index
        corr_df = pd.DataFrame(corr_series)
        corr_df = corr_df.dropna()

        if len(corr_df) >= 3:
            corr_matrix = corr_df.corr()
            # Drop any assets that produced all-NaN correlations
            valid_cols = corr_matrix.columns[corr_matrix.notna().any()]
            corr_matrix = corr_matrix.loc[valid_cols, valid_cols]

            if len(corr_matrix) >= 2:
                fig_corr = go.Figure(data=go.Heatmap(
                    z=corr_matrix.values,
                    x=list(corr_matrix.columns),
                    y=list(corr_matrix.index),
                    colorscale="RdYlGn",
                    zmin=-1, zmax=1,
                    text=corr_matrix.round(2).values,
                    texttemplate="%{text}",
                    textfont=dict(size=12),
                ))
                fig_corr.update_layout(
                    title=f"1-Month Return Correlations ({len(corr_df)} trading days)",
                    height=450,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#ccc"),
                    margin=dict(l=10, r=10, t=40, b=10),
                )
                st.plotly_chart(fig_corr, use_container_width=True)
            else:
                st.warning("Not enough valid correlations to display the matrix.")
        else:
            st.warning(f"Only {len(corr_df)} overlapping data points across assets. Need at least 3.")
    else:
        st.warning(f"Only {len(corr_series)} assets have enough history (need at least 2).")

    with st.expander("Correlation data diagnostics"):
        for line in debug_info:
            st.text(line)

# ─── Footer ────────────────────────────────────────────────────────────────
st.markdown("---")
total_instruments = sum(len(v) for v in ASSETS.values())
st.markdown(
    f"<div style='text-align:center;color:#555;font-size:0.8rem;'>"
    f"Click Refresh Dashboard Now to update all data and news | "
    f"Tracking {total_instruments} instruments | "
    f"Built for geopolitical risk monitoring"
    f"</div>",
    unsafe_allow_html=True,
)
