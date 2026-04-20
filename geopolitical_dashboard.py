"""
Geopolitical Market Dashboard: USA-Iran-Israel Conflict Monitor
"""
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd
import requests
from io import StringIO
from datetime import datetime
import feedparser
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
</style>
""", unsafe_allow_html=True)

# ─── Asset Definitions (your original) ─────────────────────────────────────
ASSETS = {
    "Commodities": {"Crude Oil (WTI)": "CL=F", "Brent Crude": "BZ=F", "Natural Gas": "NG=F", "Gold": "GC=F", "Silver": "SI=F", "Platinum": "PL=F", "Palladium": "PA=F", "Wheat": "ZW=F", "Corn": "ZC=F", "Copper": "HG=F", "Uranium (Sprott)": "SRUUF"},
    "Defense & Energy Stocks": {"Lockheed Martin": "LMT", "Raytheon (RTX)": "RTX", "Northrop Grumman": "NOC", "General Dynamics": "GD", "L3Harris": "LHX", "Boeing": "BA", "ExxonMobil": "XOM", "Chevron": "CVX", "ConocoPhillips": "COP", "Halliburton": "HAL", "Schlumberger": "SLB", "Occidental Petroleum": "OXY"},
    "Country Indices": {"S&P 500 (USA)": "^GSPC", "NASDAQ (USA)": "^IXIC", "Dow Jones (USA)": "^DJI", "FTSE 100 (UK)": "^FTSE", "DAX (Germany)": "^GDAXI", "CAC 40 (France)": "^FCHI", "Nikkei 225 (Japan)": "^N225", "Shanghai (China)": "000001.SS", "SENSEX (India)": "^BSESN", "TA-35 (Israel)": "^TA125.TA", "Tadawul (Saudi)": "^TASI.SR", "ADX (UAE)": "^ADI", "Istanbul (Turkey)": "XU100.IS", "EGX 30 (Egypt)": "^EGX30.CA"},
    "Sector ETFs": {"Energy (XLE)": "XLE", "Defense (ITA)": "ITA", "Aerospace (PPA)": "PPA", "Cybersecurity (CIBR)": "CIBR", "Utilities (XLU)": "XLU", "Financials (XLF)": "XLF", "Tech (XLK)": "XLK", "Consumer Staples": "XLP", "Materials (XLB)": "XLB", "Industrials (XLI)": "XLI", "Airlines (JETS)": "JETS", "Shipping (SIA)": "SIA"},
    "Sovereign Bonds & Safe Havens": {"US 10Y Treasury": "^TNX", "US 30Y Treasury": "^TYX", "US 5Y Treasury": "^FVX", "US 2Y Treasury": "2YY=F", "Germany 10Y Bund": "BUND-10Y.DE", "Gold ETF (GLD)": "GLD", "Silver ETF (SLV)": "SLV", "Bitcoin": "BTC-USD", "VIX (Fear Index)": "^VIX", "MOVE Index ETF": "IVOL"},
    "Currencies": {"USD Index (DXY)": "DX-Y.NYB", "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X", "USD/CHF": "CHF=X", "USD/TRY": "TRY=X", "USD/ILS": "ILS=X", "USD/SAR": "SAR=X", "USD/AED": "AED=X", "USD/INR": "INR=X", "USD/CNY": "CNY=X", "USD/RUB": "RUB=X", "USD/EGP": "EGP=X", "XAU/USD (Gold)": "XAUUSD=X"},
}

# ─── ROBUST DATA COLLECTION ─────────────────────────────

# Stooq symbols (near real-time, no 15-min exchange delay like Yahoo imposes on futures).
STOOQ_MAP = {
    "CL=F": "cl.f", "BZ=F": "bz.f", "NG=F": "ng.f",
    "GC=F": "gc.f", "SI=F": "si.f", "PL=F": "pl.f", "PA=F": "pa.f",
    "ZW=F": "zw.f", "ZC=F": "zc.f", "HG=F": "hg.f",
    "^GSPC": "^spx", "^DJI": "^dji", "^IXIC": "^ndq", "^VIX": "^vix",
    "^TNX": "^tnx", "^TYX": "^tyx", "^FVX": "^fvx",
    "^FTSE": "^ftm", "^GDAXI": "^dax", "^FCHI": "^cac", "^N225": "^nkx",
    "BTC-USD": "btcusd",
    "EURUSD=X": "eurusd", "GBPUSD=X": "gbpusd", "JPY=X": "usdjpy",
    "CHF=X": "usdchf", "TRY=X": "usdtry", "ILS=X": "usdils",
    "INR=X": "usdinr", "CNY=X": "usdcny", "RUB=X": "usdrub",
    "XAUUSD=X": "xauusd",
    "DX-Y.NYB": "^dxy",
}

_STOOQ_SESSION = requests.Session()
_STOOQ_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; GeopoliticalDashboard/1.0)"})

def _fetch_stooq_quote(symbol):
    """Pull the latest live quote + % change from Stooq. Returns None on failure."""
    stooq_sym = STOOQ_MAP.get(symbol)
    if not stooq_sym:
        return None
    try:
        # Bust any intermediary cache with a timestamp query param.
        url = f"https://stooq.com/q/l/?s={stooq_sym}&f=sd2t2ohlcvp&h&e=csv&_={int(time.time())}"
        r = _STOOQ_SESSION.get(url, timeout=6)
        r.raise_for_status()
        lines = [x for x in r.text.splitlines() if x.strip()]
        if len(lines) < 2:
            return None
        # Header: Symbol,Date,Time,Open,High,Low,Close,Volume,Change%
        fields = [f.strip() for f in lines[1].split(",")]
        if len(fields) < 7 or fields[6] in ("N/D", "", "0"):
            return None
        current = float(fields[6])
        pct = None
        if len(fields) >= 9 and fields[8] not in ("N/D", ""):
            try:
                pct = float(fields[8].replace("%", "").replace("+", ""))
            except ValueError:
                pct = None
        prev = None
        if pct is not None and (1 + pct / 100) != 0:
            prev = current / (1 + pct / 100)
        return {"price": current, "prev_close": prev, "pct": pct}
    except Exception:
        return None

def _fetch_stooq_history(symbol):
    """Pull daily OHLCV history from Stooq for sparklines/correlation."""
    stooq_sym = STOOQ_MAP.get(symbol)
    if not stooq_sym:
        return pd.DataFrame()
    try:
        url = f"https://stooq.com/q/d/l/?s={stooq_sym}&i=d&_={int(time.time())}"
        r = _STOOQ_SESSION.get(url, timeout=8)
        r.raise_for_status()
        if not r.text or "Date,Open" not in r.text:
            return pd.DataFrame()
        df = pd.read_csv(StringIO(r.text))
        if df.empty or "Close" not in df.columns:
            return pd.DataFrame()
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index().tail(30)
        return df
    except Exception:
        return pd.DataFrame()

def _fast_info_get(fi, *names):
    """Safely pull a value from yfinance FastInfo via attribute or dict access."""
    for n in names:
        try:
            val = fi[n] if hasattr(fi, "__getitem__") else None
        except Exception:
            val = None
        if val is None:
            val = getattr(fi, n, None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None

def _yf_session():
    """Return a plain requests.Session so yfinance doesn't reuse its cached HTTP client."""
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; GeopoliticalDashboard/1.0)"})
    return s

@st.cache_data(ttl=20, show_spinner=False)
def fetch_ticker_data(symbol):
    for attempt in range(3):
        try:
            # ── PRIMARY (live, un-delayed): Stooq for mapped symbols.
            stooq_quote = _fetch_stooq_quote(symbol)
            stooq_hist = _fetch_stooq_history(symbol) if stooq_quote else pd.DataFrame()

            # ── yfinance for the rest, bypassing its internal HTTP cache.
            ticker = yf.Ticker(symbol, session=_yf_session())

            yf_intraday = pd.DataFrame()
            if stooq_quote is None:
                for period, interval in (("1d", "1m"), ("5d", "5m"), ("1mo", "1h")):
                    try:
                        yf_intraday = ticker.history(period=period, interval=interval, prepost=True, auto_adjust=False)
                        if yf_intraday is not None and not yf_intraday.empty:
                            break
                    except Exception:
                        continue

            yf_hist = pd.DataFrame()
            if stooq_hist.empty:
                try:
                    yf_hist = ticker.history(period="1mo", interval="1d", auto_adjust=False)
                except Exception:
                    pass

            # ── Resolve current price: Stooq first (live), then yfinance intraday, then fast_info, then daily.
            current = None
            if stooq_quote and stooq_quote.get("price") is not None:
                current = float(stooq_quote["price"])
            elif yf_intraday is not None and not yf_intraday.empty:
                current = float(yf_intraday["Close"].dropna().iloc[-1])

            prev = stooq_quote["prev_close"] if (stooq_quote and stooq_quote.get("prev_close")) else None
            if current is None or prev is None:
                try:
                    fi = ticker.fast_info
                    if current is None:
                        current = _fast_info_get(fi, "last_price", "lastPrice", "regular_market_price", "regularMarketPrice")
                    if prev is None:
                        prev = _fast_info_get(fi, "previous_close", "previousClose", "regular_market_previous_close", "regularMarketPreviousClose")
                except Exception:
                    pass

            if current is None and not yf_hist.empty:
                current = float(yf_hist["Close"].dropna().iloc[-1])
            if current is None:
                raise ValueError("no price available")

            if prev is None:
                src = yf_hist if not yf_hist.empty else stooq_hist
                if not src.empty:
                    closes = src["Close"].dropna()
                    if len(closes) >= 2:
                        prev = float(closes.iloc[-2])
                    elif len(closes) == 1:
                        prev = float(closes.iloc[-1])
            if prev is None:
                prev = current

            change = current - prev
            pct = (change / prev * 100) if prev != 0 else 0.0

            # ── Pick the best history dataframe for charts.
            hist = stooq_hist if not stooq_hist.empty else yf_hist
            if not hist.empty:
                try:
                    today = pd.Timestamp.utcnow()
                    if hist.index.tz is not None:
                        today = today.tz_convert(hist.index.tz)
                    else:
                        today = today.tz_localize(None)
                    if hist.index[-1].normalize() == today.normalize():
                        hist.iloc[-1, hist.columns.get_loc("Close")] = current
                except Exception:
                    pass

            return {
                "price": round(float(current), 4),
                "change": float(change),
                "pct_change": round(float(pct), 2),
                "history": hist,
            }

        except Exception:
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            return None

def fetch_all_data(assets_dict):
    results = {}
    all_symbols = [(cat, name, sym) for cat, tickers in assets_dict.items() for name, sym in tickers.items()]
    with ThreadPoolExecutor(max_workers=25) as executor:
        futures = {executor.submit(fetch_ticker_data, sym): (cat, name) for cat, name, sym in all_symbols}
        for future in as_completed(futures):
            cat, name = futures[future]
            if cat not in results: results[cat] = {}
            data = future.result()
            if data: results[cat][name] = data
    return results

# ─── Helper Functions ──────────────────────────────────────────
def make_sparkline(history, name):
    fig = go.Figure()
    color = "#00C853" if history["Close"].iloc[-1] >= history["Close"].iloc[0] else "#FF1744"
    fill_color = "rgba(0, 200, 83, 0.1)" if color == "#00C853" else "rgba(255, 23, 68, 0.1)"
    fig.add_trace(go.Scatter(x=history.index, y=history["Close"], mode="lines", line=dict(color=color, width=2), fill="tozeroy", fillcolor=fill_color))
    fig.update_layout(height=120, margin=dict(l=0,r=0,t=20,b=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False, xaxis=dict(visible=False), yaxis=dict(visible=False), title=dict(text=name, font=dict(size=11, color="#aaa"), x=0.02, y=0.95))
    return fig

def make_category_chart(category_data, title):
    names = list(category_data.keys())
    pcts = [category_data[n]["pct_change"] for n in names]
    colors = ["#00C853" if p >= 0 else "#FF1744" for p in pcts]
    fig = go.Figure(go.Bar(x=pcts, y=names, orientation="h", marker_color=colors, text=[f"{p:+.2f}%" for p in pcts], textposition="outside", textfont=dict(size=11)))
    fig.update_layout(title=title, height=max(300, len(names)*35), margin=dict(l=10,r=40,t=40,b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(title="% Change", color="#aaa"), yaxis=dict(autorange="reversed", color="#aaa"), font=dict(color="#ccc"))
    return fig

def make_heatmap(all_data):
    categories, names, values = [], [], []
    for cat, items in all_data.items():
        for name, data in items.items():
            categories.append(cat); names.append(name); values.append(data["pct_change"])
    df = pd.DataFrame({"Category": categories, "Asset": names, "Change %": values})
    fig = go.Figure()
    for cat in df["Category"].unique():
        sub = df[df["Category"] == cat].sort_values("Change %", ascending=False)
        fig.add_trace(go.Bar(name=cat, x=sub["Asset"], y=sub["Change %"], marker_color=["#00C853" if v >= 0 else "#FF1744" for v in sub["Change %"]], text=[f"{v:+.2f}%" for v in sub["Change %"]], textposition="outside"))
    fig.update_layout(title="All Assets % Change Overview", barmode="group", height=500, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(tickangle=-45, color="#aaa"), yaxis=dict(title="% Change", color="#aaa"), font=dict(color="#ccc"), legend=dict(orientation="h", y=1.12))
    return fig

def get_top_movers(all_data, n=8):
    movers = []
    for cat, items in all_data.items():
        for name, data in items.items():
            movers.append({"Asset": name, "Category": cat, "Price": data["price"], "Change %": data["pct_change"]})
    df = pd.DataFrame(movers)
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    return df.nlargest(n, "Change %"), df.nsmallest(n, "Change %")

# ─── Automatic Iran-USA War News ─────
@st.cache_data(ttl=60)
def fetch_iran_usa_news():
    rss_url = "https://news.google.com/rss/search?q=Iran+US+war+OR+Iran+USA+conflict+OR+Iran+United+States+tensions+OR+Iran+Trump+strike+OR+Iran+Israel+strike+OR+Hormuz+closure&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(rss_url)
    articles = []
    for entry in feed.entries[:12]:
        pub_time = ""
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            dt = datetime(*entry.published_parsed[:6])
            pub_time = dt.strftime("%b %d, %Y %I:%M %p")
        else:
            pub_time = entry.get('published', 'Just now')
        source = entry.get('source', {}).get('title', 'Google News')
        articles.append({
            'title': entry.title,
            'published': pub_time,
            'source': source,
            'summary': entry.get('summary', 'No summary available')[:320] + "..." if len(entry.get('summary', '')) > 320 else entry.get('summary', ''),
            'link': entry.link
        })
    return articles

# ─── Sidebar ─────────────────────────────────────
with st.sidebar:
    st.markdown("## Dashboard Controls")
    selected_categories = st.multiselect("Categories to Display", options=list(ASSETS.keys()), default=list(ASSETS.keys()))
    chart_type = st.radio("Chart View", ["Bar Charts", "Sparklines", "Both"], index=2)
    st.markdown("---")
    if st.button("🔄 Refresh Dashboard Now", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("📰 News is 100% automatic • Click the button above to update everything instantly")

# ─── Header + Tabs ─────────────────────────────────────────────────────────
st.markdown('<div class="main-header">GEOPOLITICAL MARKET DASHBOARD</div>', unsafe_allow_html=True)
timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
st.markdown(f'<div class="sub-header">USA - IRAN - ISRAEL Conflict Monitor | Live Market Data | Last Updated: {timestamp}</div>', unsafe_allow_html=True)

tab_news, tab_markets, tab_risk = st.tabs(["🇮🇷 Iran-USA War & Tensions – LIVE", "📊 Markets", "⚠️ Risk & Correlations"])

# ─── NEWS TAB ────────────────────────
with tab_news:
    st.markdown('<div class="section-title">Iran-USA War & Tensions – LIVE</div>', unsafe_allow_html=True)
    st.caption("🔥 Most recent first • Powered by Google News RSS • Click Refresh Now to get the latest headlines")
    articles = fetch_iran_usa_news()
    if articles:
        cols = st.columns(2)
        for i, art in enumerate(articles):
            with cols[i % 2]:
                st.markdown(f"""
                <div class="news-card">
                    <div style="font-size:0.85rem;color:#FF1744;">{art['source']} • {art['published']}</div>
                    <strong>{art['title']}</strong>
                    <div style="font-size:0.9rem;color:#ddd;margin-top:8px;">{art['summary']}</div>
                    <a href="{art['link']}" target="_blank" style="color:#00C853;margin-top:12px;display:block;">Read full story →</a>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.warning("No current Iran-USA conflict news found.")

# ─── MARKETS TAB (Sparklines removed as requested) ────────────────────────
with tab_markets:
    st.markdown("---")
    filtered_assets = {k: v for k, v in ASSETS.items() if k in selected_categories}
    with st.spinner("Fetching live market data..."):
        all_data = fetch_all_data(filtered_assets)
    if not all_data:
        st.error("Unable to fetch market data.")
        st.stop()
    gainers, losers = get_top_movers(all_data, n=8)
    col_g, col_l = st.columns(2)
    with col_g:
        st.markdown("### Top Gainers")
        if not gainers.empty:
            for _, row in gainers.iterrows():
                st.markdown(f"**{row['Asset']}** ({row['Category']}) — <span style='color:#00C853'>{row['Price']:,.2f} ({row['Change %']:+.2f}%)</span>", unsafe_allow_html=True)
    with col_l:
        st.markdown("### Top Losers")
        if not losers.empty:
            for _, row in losers.iterrows():
                st.markdown(f"**{row['Asset']}** ({row['Category']}) — <span style='color:#FF1744'>{row['Price']:,.2f} ({row['Change %']:+.2f}%)</span>", unsafe_allow_html=True)
    st.markdown("---")
    st.plotly_chart(make_heatmap(all_data), use_container_width=True)
    for category in selected_categories:
        if category not in all_data or not all_data[category]: continue
        cat_data = all_data[category]
        st.markdown(f'<div class="section-title">{category}</div>', unsafe_allow_html=True)
        cols = st.columns(min(len(cat_data), 2))
        for i, (name, data) in enumerate(cat_data.items()):
            with cols[i % len(cols)]:
                st.metric(label=name, value=f"{data['price']:,.2f}", delta=f"{data['pct_change']:+.2f}%")
        if chart_type in ["Bar Charts", "Both"]:
            st.plotly_chart(make_category_chart(cat_data, f"{category} — % Change"), use_container_width=True)
        # Sparklines removed as requested
        st.markdown("---")

# ─── RISK TAB (Fixed - shows with less data) ────────────────────────
with tab_risk:
    st.markdown('<div class="section-title">Geopolitical Risk Indicators</div>', unsafe_allow_html=True)
    def safe_get(category, name, field="pct_change"):
        try:
            return all_data[category][name][field]
        except (KeyError, TypeError):
            return None
    oil_chg = safe_get("Commodities", "Crude Oil (WTI)")
    gold_chg = safe_get("Commodities", "Gold")
    vix_price = safe_get("Sovereign Bonds & Safe Havens", "VIX (Fear Index)", "price")
    dxy_chg = safe_get("Currencies", "USD Index (DXY)")
    risk_row1_col1, risk_row1_col2 = st.columns(2)
    with risk_row1_col1: st.metric("Oil Stress", f"{oil_chg:+.2f}%" if oil_chg is not None else "N/A")
    with risk_row1_col2: st.metric("Gold Flight", f"{gold_chg:+.2f}%" if gold_chg is not None else "N/A")
    risk_row2_col1, risk_row2_col2 = st.columns(2)
    with risk_row2_col1: st.metric("VIX Fear Level", f"{vix_price:.1f}" if vix_price is not None else "N/A")
    with risk_row2_col2: st.metric("USD Strength", f"{dxy_chg:+.2f}%" if dxy_chg is not None else "N/A")

    st.markdown('<div class="section-title">Key Conflict-Sensitive Correlations</div>', unsafe_allow_html=True)
    key_assets = {"Oil (WTI)": ("Commodities", "Crude Oil (WTI)"), "Gold": ("Commodities", "Gold"), "Defense (ITA)": ("Sector ETFs", "Defense (ITA)"), "Energy (XLE)": ("Sector ETFs", "Energy (XLE)"), "S&P 500": ("Country Indices", "S&P 500 (USA)"), "VIX": ("Sovereign Bonds & Safe Havens", "VIX (Fear Index)")}
    corr_data = {}
    for label, (cat, name) in key_assets.items():
        try:
            hist = all_data[cat][name]["history"]
            if hist is not None and not hist.empty and len(hist) >= 3:
                corr_data[label] = hist["Close"].pct_change().dropna()
        except:
            pass
    if len(corr_data) >= 2:
        corr_df = pd.DataFrame(corr_data)
        corr_matrix = corr_df.corr()
        fig_corr = go.Figure(data=go.Heatmap(z=corr_matrix.values, x=corr_matrix.columns, y=corr_matrix.index, colorscale="RdYlGn", zmin=-1, zmax=1, text=corr_matrix.round(2).values, texttemplate="%{text}"))
        fig_corr.update_layout(title="5-Day Return Correlations", height=450, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#ccc"))
        st.plotly_chart(fig_corr, use_container_width=True)
    else:
        st.info("Not enough historical data yet. Click Refresh Dashboard Now a few times.")

# ─── Footer ────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    f"<div style='text-align:center;color:#555;font-size:0.8rem;'>"
    f"Click 'Refresh Dashboard Now' to update all data & news | "
    f"Tracking {sum(len(v) for v in ASSETS.values())} instruments | "
    f"Built for geopolitical risk monitoring"
    f"</div>",
    unsafe_allow_html=True,
)
