"""
SIGNAL — Ani Singh Private Research Agent  ·  Bloomberg-terminal build.

Sections:
  I/II  RESEARCH   — full daily cycle + topic deep dive
  III   GLOBE      — 3-layer interactive globe: Markets / Geopolitics / Debt Cycle
  IV    MARKETS    — global valuation screener + sovereign credit-stress monitor
  V     DEBT CYCLE — Dalio MP tracker, central-bank policy, currency debasement
  VI    PORTFOLIO  — Thesis War Room: position pulse + stress tests + macro theses
  VII   EARNINGS   — calendar + pre-earnings briefs
PDF download on every research output.

Data sourcing is hybrid: market prices/valuations and currency-vs-gold are LIVE
from yfinance (cached 1h); structural baselines (debt/GDP, CAPE, MP phase) are
clearly labelled; the live AI+web-search layer fires lazily on demand.
"""

from __future__ import annotations

import html as _html
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic
import streamlit as st
import streamlit.components.v1 as components

from signal_core import (
    MODEL, get_api_key, today_str, now_str,
    stream_research, call_research, call_json, parse_status,
)
import theme
import market_data as mkt
import valuation as val
import debt_cycle as dc
import signal_ai as ai
import pdf_export

# ── Component ────────────────────────────────────────────────────────────────
import os
_GLOBE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "globe_component")
globe_component = components.declare_component("signal_globe", path=_GLOBE_DIR)

st.set_page_config(page_title="SIGNAL · Ani Singh", page_icon="◆",
                   layout="wide", initial_sidebar_state="collapsed")
theme.inject_theme()

# ── Hero ─────────────────────────────────────────────────────────────────────
st.markdown(
    f"""
<div style="text-align:center; margin-top:0.4rem; margin-bottom:1.4rem;">
    <div class="signal-title">SIGNAL</div>
    <div class="signal-subtitle">Ani Singh · Private Research Agent</div>
    <div class="signal-meta">{now_str()}</div>
</div>
""",
    unsafe_allow_html=True,
)

api_key = get_api_key()
if not api_key:
    st.error(
        "ANTHROPIC_API_KEY not set. Add it to .env locally, or to Streamlit "
        "Cloud secrets as `ANTHROPIC_API_KEY=\"sk-ant-…\"`."
    )
    st.stop()


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT BUILDERS  (research cycle / deep dive / market / pulse / earnings)
# ─────────────────────────────────────────────────────────────────────────────

def prompt_macro(today):
    return f"""Today is {today}. Use web search for all current data.

Produce the MACRO & RATES section. Cover:
- Federal Reserve: latest statements, rate path, balance sheet trajectory
- US Treasury: 10Y yield, real yield, term premium
- Inflation and labor: latest prints, gap between what's printed and what's priced
- Global central banks: ECB, PBOC, BOJ divergence signals
- Credit cycle: Dalio long-term debt cycle positioning — where are we?
- Market sentiment: positioning, risk appetite, fund flows, fear/greed indicators — what is the crowd doing and is it a contrarian signal?
- Dollar: DXY, reserve currency dynamics

Apply Dalio: where are we in the machine? Apply Marks: what is being priced for perfection in rates? Specific numbers only."""


def prompt_earnings(today):
    return f"""Today is {today}. Use web search for all current data.

Produce the EARNINGS & CORPORATE section. Cover:
- Major earnings in trailing 48-72 hours: actual vs estimate, guidance revision, margin trajectory, what management didn't say
- Key reports due this week that move the macro or sector picture
- Semiconductor sector specifically: supply, pricing, capex, design wins (critical for QCOM thesis)
- Capital markets: debt issuance, refinancing stress, downgrades, defaults
- Major M&A, restructurings, corporate strategy shifts

Signal vs noise filter applied. Reflexivity lens: is any earnings narrative becoming self-reinforcing?"""


def prompt_ai_tech(today):
    return f"""Today is {today}. Use web search for all current data.

Produce the AI & TECHNOLOGY section. Cover:
- Edge AI inference adoption curve: on-device compute developments — this is the core QCOM structural thesis. New design wins, partnerships, adoption evidence?
- Inference AI news specifically: developments in AI inference (NOT training) — cost curves, inference-optimized chips, deployment at scale
- Semiconductor fab capacity — TSMC ONLY: production capacity growth, node ramp (N2, N3), capex, utilization, AI chip allocation. Focus exclusively on TSMC.
- Qualcomm, Apple, Nvidia, AMD silicon roadmap news as it relates to inference
- AI model releases and capability announcements relevant to inference demand
- One emerging inference-related signal most investors are not watching yet

Frame edge AI through Dalio: early-to-middle cycle technology shift. What is the reflexivity loop forming?"""


def prompt_geo(today):
    return f"""Today is {today}. Use web search for all current data.

Produce the GEOPOLITICAL section. Cover:
- Middle East energy: current status, escalation or de-escalation, oil supply implications (relevant to KMI energy thesis)
- US-China: trade actions, tech and semiconductor export restrictions, Taiwan developments (critical for TSMC capacity), capital flow implications
- Energy infrastructure and natural gas: policy, demand drivers including AI data center power buildout (relevant to KMI)
- Europe: energy security, political developments with market implications
- One flashpoint being underpriced by markets right now

Changing world order lens: which developments signal the structural transition Dalio describes?"""


def prompt_cross_asset(today):
    return f"""Today is {today}. Use web search for all current data.

Produce the CROSS-ASSET section. Cover:
- Equities: index levels, sector rotation, market breadth — is the rally narrow or broad?
- Rates: yield curve shape (2s10s spread), credit spreads IG and HY, MOVE index
- Commodities: WTI oil, gold (central bank demand signal), copper (growth signal)
- FX: DXY, key crosses, stress signals
- Volatility: VIX — fear or complacency?
- One cross-asset relationship breaking down or forming that most haven't noticed

Marks lens: where is risk being mispriced across these asset classes right now?"""


def prompt_synthesis(today):
    return f"""Today is {today}. Based on all research today, produce the SYNTHESIS section. Cover:

POSITION DESK — Thesis check for each (strengthened or challenged by today's data, be blunt):
- QUALCOMM (QCOM, 40% weight): edge AI inference, automotive ramp, QTL licensing
- KINDER MORGAN (KMI, 17% weight): energy midstream, natural gas demand including AI data center power, dividend, inflation-resilient real assets
- SALESFORCE (CRM): agentic AI enterprise consolidation
- XIAOMI (1810.HK): China consumer recovery, EV optionality

WHAT CONSENSUS IS MISSING — The dominant market narrative right now and exactly where it is wrong. One specific contrarian read.

TAIL RISKS — 2-3 risks that are real and unpriced. Not consensus risks. Make the reader uncomfortable.

THE ANCHOR — One paragraph. What should a concentrated macro investor be thinking this week that most aren't? End with a historical parallel that rhymes today (Weimar, 1970s stagflation, 1998, 2008) and the lesson.

SUBSTACK ANGLE — 1 essay idea from today's research. Give the hook and the structural argument in 3 sentences."""


def prompt_deep_dive(today, query):
    return f"""Today is {today}. Topic: "{query}"

Use web search aggressively. Pull all current data, recent developments, analyst views, policy updates on this topic.

Produce a complete memo covering:
1. THE CURRENT SITUATION — What is actually happening right now, specific numbers and dates
2. HISTORICAL CONTEXT — How does this fit the longer debt cycle or historical pattern? Where have we seen this before?
3. DALIO LENS — Where does this sit in the long-term debt cycle and changing world order?
4. REFLEXIVITY LOOP — Is there a self-reinforcing dynamic forming between narrative and fundamentals?
5. MARKET IMPLICATIONS — What is priced, what is mispriced, where is the asymmetry?
6. PORTFOLIO RELEVANCE — Impact on QCOM (40%), Kinder Morgan (17%), Salesforce, or Xiaomi. Any thesis implications?
7. WHAT CONSENSUS IS MISSING — The contrarian read. What is the dominant narrative getting wrong?
8. TAIL RISK — The scenario that breaks everything in this situation.

Specific numbers only. Skip definitions. Write for a sophisticated investor who already knows the basics."""


def prompt_market_analysis(today, country):
    return f"""Today is {today}. Produce a complete market intelligence memo on {country} financial markets.

Use web search aggressively for current data.

Structure the memo as follows:

DEBT CYCLE STAGE
Where is {country} in the Dalio long-term debt cycle right now? Early, mid, late, or deleveraging? What are the key indicators telling you this — credit growth, debt/GDP, central bank posture, private sector leverage? Be specific with numbers.

GEOPOLITICAL LANDSCAPE
Key geopolitical risks or tensions involving {country} right now. Any active conflicts, trade disputes, political instability, or election risk. What is the market pricing vs what is actually happening?

MARKET VALUATION
Current equity market valuation — P/E, P/B, EV/EBITDA vs historical average and vs global peers. Cheap, fair, or expensive? Where is the asymmetry?

EARNINGS GROWTH
Current and forward earnings growth estimates for the broad market. Which sectors are driving or dragging? Any guidance revision trends?

TOP SECTORS
The 3-4 dominant sectors by market cap and by growth. What is the structural story of each?

MACRO DATA
GDP growth rate, inflation, unemployment, current account balance, currency trend. Any divergence from consensus expectations?

TOP EXPORTS & IMPORTS
The 5 most important exports and imports by value. What does this tell you about the country's structural position in global trade?

TOP TRADING PARTNERS
The 5 most important trading partners by volume. Any geopolitical tension with key partners?

DALIO/MARKS SYNTHESIS
One paragraph. Where is this market in the changing world order framework? Is this a rising, peak, or declining power in Dalio's model? What would Marks say about the current risk/reward? Is this a market worth having exposure to right now?

PORTFOLIO RELEVANCE
Any direct relevance to QCOM (40%), KMI (17%), Salesforce, or Xiaomi positions?

Write in Howard Marks memo style. Specific numbers only. No generic statements."""


SECTIONS = [
    ("MACRO & RATES", prompt_macro),
    ("EARNINGS & CORPORATE", prompt_earnings),
    ("AI & TECHNOLOGY", prompt_ai_tech),
    ("GEOPOLITICAL", prompt_geo),
    ("CROSS-ASSET", prompt_cross_asset),
    ("SYNTHESIS · POSITIONS · RISKS · SUBSTACK", prompt_synthesis),
]

POSITIONS = [
    {"ticker": "QCOM", "yf_ticker": "QCOM", "name": "QUALCOMM", "weight": "40%",
     "thesis": ("Edge AI inference dominance in power-constrained environments, automotive "
                "revenue ramp targeting $4B by 2026, QTL licensing moat, structural multi-year "
                "advantage over Nvidia and AMD at the edge due to mobile power-constraint "
                "engineering heritage. TSMC N2 capacity ramp is a direct tailwind for QCOM product roadmap.")},
    {"ticker": "KMI", "yf_ticker": "KMI", "name": "KINDER MORGAN", "weight": "17%",
     "thesis": ("Cash-flow-generative midstream energy infrastructure, natural gas demand growth "
                "driven by AI data center power buildout, 4–6% dividend yield, inflation-resilient "
                "real asset, long-duration pipeline contracts insulated from commodity price swings.")},
    {"ticker": "CRM", "yf_ticker": "CRM", "name": "SALESFORCE", "weight": "13%",
     "thesis": ("Agentic AI platform consolidation, enterprise software stickiness, Agentforce as "
                "the dominant AI workflow layer for enterprise, remaining performance obligation as "
                "forward revenue visibility signal.")},
    {"ticker": "XIAOMI", "yf_ticker": "1810.HK", "name": "XIAOMI", "weight": "9%",
     "thesis": ("China consumer recovery, EV optionality with growing delivery numbers, global "
                "hardware ecosystem expansion, India smartphone market share. Watch India revenue "
                "concentration — if above 30% of total, India credit cycle becomes position-sizing concern.")},
]

MACRO_THESES = [
    {"name": "Dalio Late-Cycle Debt Dynamics",
     "established": "2024-01",
     "desc": ("US fiscal dominance / MP3 transition — deficits ~6-7% of GDP at full employment, "
              "debt monetization pressure, term premium and currency-debasement risk rising.")},
    {"name": "Edge AI Inference Era",
     "established": "2024-03",
     "desc": ("QCOM heterogeneous-compute thesis — the AI value shift from training to inference, "
              "inference moving on-device/edge, power-constrained engineering as the structural moat.")},
    {"name": "Strait of Hormuz / Petrodollar Architecture",
     "established": "2024-06",
     "desc": ("Operation Epic Fury framework — energy chokepoint risk at Hormuz, petrodollar "
              "recycling shifts, oil-supply disruption optionality with KMI/energy-infrastructure relevance.")},
]


def prompt_pulse(today, pos):
    return f"""Today is {today}. Use web search.

Position check for {pos['yf_ticker']} ({pos['name']}), {pos['weight']} of portfolio.

Core thesis: {pos['thesis']}

In 4–5 sentences cover:
1. Any material news, earnings, analyst actions, or price target changes in the last 48 hours
2. Any development that directly strengthens or challenges the core thesis
3. Status verdict: THESIS INTACT, WATCH, or ALERT and one sentence explaining why

Be direct. No filler. If nothing material happened say so plainly."""


def prompt_earnings_calendar(today):
    return f"""Today is {today}. Use web search to find the next confirmed earnings date for each ticker below.

PORTFOLIO POSITIONS: QCOM, KMI, CRM, 1810.HK
SECTOR WATCH: NVDA, AMD, TSM, MSFT, GOOGL, META, OXY, ET, WMB, ENB, ORCL, SAP, SNOW

Output ONE line per ticker in EXACTLY this pipe-delimited format:
TICKER | YYYY-MM-DD | EPS_ESTIMATE | CONFIDENCE

- YYYY-MM-DD: expected earnings date; use TBD if not confirmed
- EPS_ESTIMATE: consensus EPS with $ (e.g. $2.35) or TBD
- CONFIDENCE: one of confirmed, estimated, unknown

Output ONLY these lines — no commentary, no headers, no markdown fences."""


def prompt_pre_earnings(today, ticker, earnings_date):
    blocks = {
        "QCOM": "For QCOM watch: Automotive segment revenue (thesis $4B by 2026); IoT revenue trend; handset unit guidance and ASP; edge/on-device AI design-win commentary; QTL licensing revenue and royalty rate.",
        "KMI": "For KMI watch: natural gas throughput volumes; gas-demand commentary incl. AI data center customers; LNG export capacity utilization; dividend guidance / coverage ratio.",
        "CRM": "For CRM watch: Agentforce seat adoption and attach rate; Remaining Performance Obligation growth; AI-driven deal sizes vs traditional; net revenue retention.",
        "1810.HK": "For Xiaomi watch: EV delivery numbers and margin per unit; India revenue as % of total (alert if >30%); gross-margin trajectory; China consumer demand commentary.",
    }
    watch = blocks.get(ticker.upper(), "")
    return f"""Today is {today}. Use web search.

Pre-earnings intelligence brief for {ticker} reporting approximately {earnings_date}.

1. CONSENSUS EXPECTATIONS — Street EPS, revenue, key segment metrics; whisper vs official.
2. WHAT TO WATCH — the 2–3 data points/guidance language that will move the stock. {watch}
3. THESIS CHECK SCENARIOS — what results strengthen vs challenge the thesis. Specific numbers.
4. HISTORICAL EARNINGS PATTERN — reaction to beats vs misses over last 4 quarters.
5. POSITIONING INTO THE PRINT — rational response to a beat, a miss, an in-line result.

Howard Marks memo style. Specific numbers only. No generic statements."""


# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
_defaults = {
    "research": None,           # {kind, topic, sections:[(title,text)]}
    "globe_output": None,       # {country, text}
    "last_globe_click_id": None,
    "globe_layer": "MARKETS",
    "geo_data": None,
    "val_signals": None,
    "cds_data": None,
    "cb_data": None,
    "debase_comment": None,
    "pulse_results": {},
    "stress_results": {},
    "run_stress": None,
    "macro_results": {},
    "run_macro": None,
    "debt_memo": {},            # country -> text
    "earnings_calendar": None,
    "pre_earnings_briefs": {},
    "active_brief_ticker": None,
    "valuation_alerts": None,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─────────────────────────────────────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def fmt_num(v, dec=2, suffix=""):
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.0f}{suffix}"
    return f"{v:.{dec}f}{suffix}"


def fmt_pct(v, dec=1):
    if v is None or (isinstance(v, float) and v != v):
        return '<span class="mut">—</span>'
    cls = "pos" if v >= 0 else "neg"
    return f'<span class="{cls}">{v:+.{dec}f}%</span>'


def run_stream(prompt, err_prefix="Error"):
    """Stream a memo into a bordered container; return full text (or error str)."""
    try:
        with st.container(border=True):
            out = st.write_stream(stream_research(prompt, api_key))
        return out if isinstance(out, str) else "".join(out or [])
    except anthropic.APIStatusError as e:
        msg = getattr(e, "message", str(e))
        st.error(f"{err_prefix}: {msg}")
        return f"_{err_prefix}: {msg}_"
    except Exception as e:  # noqa: BLE001
        st.error(f"{err_prefix}: {e}")
        return f"_{err_prefix}: {e}_"


def pdf_button(label, section_code, title, subtitle, body, suffix="", key=""):
    try:
        data = pdf_export.memo_to_pdf(title, subtitle, body)
        st.download_button(
            label, data=data,
            file_name=pdf_export.filename(section_code, suffix),
            mime="application/pdf", use_container_width=True, key=key,
        )
    except Exception as e:  # noqa: BLE001
        st.error(f"PDF generation failed: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# I / II — RESEARCH
# ═════════════════════════════════════════════════════════════════════════════
theme.section_header("I · II", "RESEARCH", "research")

c_full, c_dive, c_btn = st.columns([1.1, 2.2, 0.9])
with c_full:
    run_full = st.button("◆  Full Research Cycle", key="run_full", use_container_width=True)
with c_dive:
    topic = st.text_input("topic", placeholder="Deep dive — e.g. Japan yield crisis · private credit stress",
                          label_visibility="collapsed", key="topic_input")
with c_btn:
    run_deep = st.button("Research", key="run_deep", use_container_width=True)

if run_full:
    today = today_str()
    sections = []
    prog = st.progress(0.0, text="initializing…")
    for i, (title, builder) in enumerate(SECTIONS):
        st.markdown(f'<div class="sig-sub">{i+1:02d} / {len(SECTIONS):02d} · {title}</div>',
                    unsafe_allow_html=True)
        prog.progress(i / len(SECTIONS), text=f"{title} …")
        text = run_stream(builder(today), err_prefix=f"Error in {title}")
        sections.append((title, text))
        prog.progress((i + 1) / len(SECTIONS), text=f"{title} complete")
    prog.progress(1.0, text="memo complete")
    st.session_state.research = {"kind": "full", "topic": "", "sections": sections}

elif run_deep and topic.strip():
    st.markdown(f'<div class="sig-sub">DEEP DIVE · {_html.escape(topic.strip())}</div>',
                unsafe_allow_html=True)
    text = run_stream(prompt_deep_dive(today_str(), topic.strip()), err_prefix="Error")
    st.session_state.research = {"kind": "deep", "topic": topic.strip(),
                                 "sections": [(topic.strip().upper(), text)]}
elif run_deep:
    st.warning("Enter a topic first.")

# Render cached research (on plain reruns) + PDF
_r = st.session_state.research
if _r and not (run_full or run_deep):
    if _r["kind"] == "full":
        for title, text in _r["sections"]:
            st.markdown(f'<div class="sig-sub">{title}</div>', unsafe_allow_html=True)
            with st.container(border=True):
                st.markdown(f'<div class="memo-body">{text}</div>', unsafe_allow_html=True)
    else:
        with st.container(border=True):
            st.markdown(f'<div class="memo-body">{_r["sections"][0][1]}</div>', unsafe_allow_html=True)

if _r:
    body = "\n\n---\n\n".join(f"## {t}\n\n{x}" for t, x in _r["sections"])
    if _r["kind"] == "deep":
        pdf_button("⬇  Download Deep Dive (PDF)", "DeepDive", "DEEP DIVE",
                   f'{_r["topic"]} · {today_str()}', body, _r["topic"], key="dl_deep")
    else:
        pdf_button("⬇  Download Full Memo (PDF)", "FullCycle", "FULL RESEARCH CYCLE",
                   today_str(), body, key="dl_full")


# ═════════════════════════════════════════════════════════════════════════════
# III — GLOBE  (Markets / Geopolitics / Debt Cycle)
# ═════════════════════════════════════════════════════════════════════════════
theme.section_header("III", "GLOBE", "globe")

with st.spinner("◆ loading live market valuations…"):
    market_dict = mkt.fetch_market_data()

# valuation history / divergence alerts off the live labels
if st.session_state.valuation_alerts is None:
    st.session_state.valuation_alerts = val.update_history_and_alerts(
        mkt.country_label_map(market_dict)
    )
valuation_alerts = st.session_state.valuation_alerts
position_alerts = val.alerts_for_position(valuation_alerts)

layer = st.radio("Globe layer", ["MARKETS", "GEOPOLITICS", "DEBT CYCLE"],
                 horizontal=True, label_visibility="collapsed",
                 key="globe_layer_radio",
                 index=["MARKETS", "GEOPOLITICS", "DEBT CYCLE"].index(st.session_state.globe_layer))
st.session_state.globe_layer = layer

# Build nodes for the active layer
if layer == "MARKETS":
    theme.caption("Nodes color-coded by P/E vs each market's own 10-year average. Tap a node for a country memo.")
    base_nodes = mkt.globe_nodes(market_dict)
    nodes = []
    for n in base_nodes:
        pe = f"{n['pe']:.1f}x" if n.get("pe") is not None else "n/a"
        ytd = f"{n['ytd']:+.1f}% YTD" if n.get("ytd") is not None else ""
        lines = [{"text": f"{n['index']} · P/E {pe}", "color": "#e8e3d6"},
                 {"text": n["band"], "color": n["color"]}]
        if ytd:
            lines.append({"text": ytd, "color": "#8a8470"})
        nodes.append({**n, "lines": lines})
    globe_title = "◆ Markets · valuation"

elif layer == "GEOPOLITICS":
    theme.caption("Nodes color-coded by current geopolitical-risk intensity (live AI + web search).")
    if st.session_state.geo_data is None:
        if st.button("⟲  Load geopolitical risk map", key="load_geo"):
            with st.spinner("◆ assessing global geopolitical risk…"):
                countries = [n["name"] for n in mkt.globe_nodes(market_dict)]
                st.session_state.geo_data = ai.load_geopolitics(api_key, countries)
            st.rerun()
    geo = st.session_state.geo_data or {}
    nodes = []
    for n in mkt.globe_nodes(market_dict):
        rec = geo.get(n["name"], {})
        lvl = (rec.get("level") or "UNKNOWN").upper()
        color = ai.geo_color(lvl)
        lines = [{"text": lvl, "color": color}]
        if rec.get("brief"):
            lines.append({"text": rec["brief"], "color": "#e8e3d6"})
        if rec.get("assets"):
            lines.append({"text": "↳ " + ", ".join(rec["assets"][:2]), "color": "#8a8470"})
        elif not rec:
            lines.append({"text": "tap Load above", "color": "#8a8470"})
        nodes.append({**n, "color": color, "lines": lines})
    globe_title = "◆ Geopolitics · risk"

else:  # DEBT CYCLE
    theme.caption("Nodes color-coded by Dalio Monetary-Policy phase (framework baseline). Deep profiles in Section V.")
    nodes = []
    for country, b in dc.COUNTRY_BASELINES.items():
        color = dc.phase_color(b["phase"])
        lines = [{"text": dc.phase_label(b["phase"]), "color": color}]
        if b.get("sub"):
            lines.append({"text": b["sub"], "color": "#8a8470"})
        nodes.append({"name": country, "lat": b["lat"], "lng": b["lng"],
                      "color": color, "lines": lines})
    globe_title = "◆ Debt cycle · MP phase"

# Divergence alert banners (markets layer)
if layer == "MARKETS":
    for a in valuation_alerts:
        cls = "neg" if a["direction"] == "expensive" else "pos"
        arrow = "▲" if a["direction"] == "expensive" else "▼"
        st.markdown(
            f'<div class="hotspot" style="border-left-color:'
            f'{"#e05c5c" if a["direction"]=="expensive" else "#4ade80"};">'
            f'<span class="hs-name">{arrow} VALUATION SHIFT</span> '
            f'<span class="hs-brief" style="display:inline;">{theme.esc(a["country"])}: '
            f'{a["prev_band"]} → {a["new_band"]}</span></div>',
            unsafe_allow_html=True,
        )

globe_event = globe_component(markets=nodes, height=560, title=globe_title,
                              key="signal_globe", default=None)

# Legend per layer
if layer == "MARKETS":
    legend = [("CHEAP", mkt.VAL_COLORS["CHEAP"]), ("FAIR", mkt.VAL_COLORS["FAIR"]),
              ("RICH", mkt.VAL_COLORS["RICH"]), ("EXPENSIVE", mkt.VAL_COLORS["EXPENSIVE"]),
              ("NO DATA", mkt.VAL_COLORS["NO DATA"])]
elif layer == "GEOPOLITICS":
    legend = [(lv, ai.GEO_RISK_COLORS[lv]) for lv in ai.GEO_RISK_ORDER]
else:
    legend = [(dc.phase_label(p), dc.phase_color(p)) for p in
              ["MP1", "MP2", "MP3", "TRANSITIONING"]]
st.markdown(
    '<div class="legend-row">' +
    "".join(f'<span><span class="legend-dot" style="background:{c}"></span>{theme.esc(l)}</span>'
            for l, c in legend) +
    "</div>",
    unsafe_allow_html=True,
)

# Hotspots panel (geopolitics)
if layer == "GEOPOLITICS" and st.session_state.geo_data:
    hot = [(name, r) for name, r in st.session_state.geo_data.items()
           if (r.get("level") or "").upper() in ("ESCALATING", "HOT", "CRISIS")]
    order = {"CRISIS": 0, "HOT": 1, "ESCALATING": 2}
    hot.sort(key=lambda x: order.get((x[1].get("level") or "").upper(), 9))
    if hot:
        theme.subheader("Hotspots")
        for name, r in hot[:5]:
            lvl = (r.get("level") or "").upper()
            col = ai.geo_color(lvl)
            st.markdown(
                f'<div class="hotspot"><span class="hs-name">{theme.esc(name)}</span>'
                f'<span class="hs-lvl" style="background:{col}33;color:{col};">{lvl}</span>'
                f'<div class="hs-brief">{theme.esc(r.get("brief",""))}</div></div>',
                unsafe_allow_html=True,
            )

# Globe click → country market memo
new_click = None
if isinstance(globe_event, dict):
    cid = globe_event.get("click_id")
    if cid and cid != st.session_state.last_globe_click_id:
        st.session_state.last_globe_click_id = cid
        new_click = globe_event.get("country")

if new_click:
    theme.subheader(f"Country Memo · {new_click}")
    text = run_stream(prompt_market_analysis(today_str(), new_click), err_prefix="Error")
    st.session_state.globe_output = {"country": new_click, "text": text}
elif st.session_state.globe_output:
    go = st.session_state.globe_output
    theme.subheader(f"Country Memo · {go['country']}")
    with st.container(border=True):
        st.markdown(f'<div class="memo-body">{go["text"]}</div>', unsafe_allow_html=True)

if st.session_state.globe_output:
    go = st.session_state.globe_output
    pdf_button("⬇  Download Country Memo (PDF)", "Globe", f'GLOBAL MARKETS — {go["country"]}',
               today_str(), f'## {go["country"]}\n\n{go["text"]}', go["country"], key="dl_globe")


# ═════════════════════════════════════════════════════════════════════════════
# IV — GLOBAL MARKETS  (valuation screener + credit stress)
# ═════════════════════════════════════════════════════════════════════════════
theme.section_header("IV", "GLOBAL MARKETS", "markets")
theme.caption(f"Live prices &amp; P/E from yfinance (cached 1h). CAPE &amp; 10yr-avg P/E are "
              f"structural baselines ({mkt.BASELINE_ASOF}). Valuation = live P/E vs that market's 10yr avg.")

rows = list(market_dict.values())

f1, f2, f3 = st.columns(3)
with f1:
    region = st.selectbox("Region", mkt.REGION_FILTERS, key="scr_region")
with f2:
    valfilter = st.selectbox("Valuation", ["All", "Cheap+Fair", "Rich+Expensive"], key="scr_val")
with f3:
    sort_by = st.selectbox("Sort by", ["Valuation (rich→cheap)", "P/E (high→low)",
                                       "YTD (high→low)", "CAPE (high→low)", "Country (A→Z)"],
                           key="scr_sort")

def _region_ok(r):
    if region == "All":
        return True
    if region == "EM":
        return r["em"]
    if region == "ME+Africa":
        return r["continent"] == "ME-Africa"
    return r["continent"] == region

def _val_ok(r):
    if valfilter == "Cheap+Fair":
        return r["valuation"] in ("CHEAP", "FAIR")
    if valfilter == "Rich+Expensive":
        return r["valuation"] in ("RICH", "EXPENSIVE")
    return True

filtered = [r for r in rows if _region_ok(r) and _val_ok(r)]

_valrank = {"EXPENSIVE": 4, "RICH": 3, "FAIR": 2, "CHEAP": 1, "NO DATA": 0}
def _key(r):
    if sort_by.startswith("Valuation"):
        return -_valrank.get(r["valuation"], 0)
    if sort_by.startswith("P/E"):
        return -(r["pe"] if r["pe"] is not None else -1)
    if sort_by.startswith("YTD"):
        return -(r["ytd"] if r["ytd"] is not None else -9999)
    if sort_by.startswith("CAPE"):
        return -(r["cape"] if r["cape"] is not None else -1)
    return r["country"]
filtered.sort(key=_key)

signals = (st.session_state.val_signals or {}).get("signals", {}) if st.session_state.val_signals else {}
SIGNAL_COLORS = {"AVOID": "#e05c5c", "WATCH": "#d6c645", "ACCUMULATE": "#a3e635", "BUY": "#4ade80"}

thead = ("<tr><th class='l'>Market</th><th class='l'>Index</th><th>Price</th><th>P/E</th>"
         "<th>CAPE†</th><th>P/B</th><th>YTD</th><th>52w hi</th><th>Valuation</th><th>Signal</th></tr>")
trows = []
for r in filtered:
    sig = signals.get(r["country"], "")
    sig_html = (f'<span class="pill" style="background:{SIGNAL_COLORS.get(sig,"#8a8470")}22;'
                f'color:{SIGNAL_COLORS.get(sig,"#8a8470")};">{sig}</span>') if sig else '<span class="mut">—</span>'
    val_html = (f'<span class="pill" style="background:{r["color"]}22;color:{r["color"]};">'
                f'{r["valuation"]}</span>')
    trows.append(
        "<tr>"
        f"<td class='l tk'>{theme.esc(r['country'])}</td>"
        f"<td class='l mut'>{theme.esc(r['index'])}</td>"
        f"<td>{fmt_num(r['price'])}</td>"
        f"<td>{fmt_num(r['pe'],1)}</td>"
        f"<td>{fmt_num(r['cape'],1)}</td>"
        f"<td>{fmt_num(r['pb'],1)}</td>"
        f"<td>{fmt_pct(r['ytd'])}</td>"
        f"<td>{fmt_pct(r['hi52'])}</td>"
        f"<td>{val_html}</td>"
        f"<td>{sig_html}</td>"
        "</tr>"
    )
st.markdown(f'<div class="table-scroll"><table class="sig-table">{thead}{"".join(trows)}</table></div>',
            unsafe_allow_html=True)
st.markdown('<div class="sig-caption">† CAPE = cyclically-adjusted P/E, structural baseline estimate; '
            'verify via the AI commentary below.</div>', unsafe_allow_html=True)

if st.button("⟲  Load AI signals & world valuation read", key="load_signals"):
    with st.spinner("◆ scoring global valuations through the framework…"):
        st.session_state.val_signals = ai.load_valuation_signals(
            api_key, [r for r in filtered if r["pe"] is not None] or filtered)
    st.rerun()

if st.session_state.val_signals and st.session_state.val_signals.get("commentary"):
    with st.container(border=True):
        st.markdown(f'<div class="memo-body">{st.session_state.val_signals["commentary"]}</div>',
                    unsafe_allow_html=True)

# ── Credit Stress Monitor ────────────────────────────────────────────────────
theme.subheader("Credit Stress Monitor · Sovereign CDS")
theme.caption("5-year sovereign CDS spreads (bps) — the market's price of default risk. "
              "CDS is not free real-time; figures are best-available estimates from public data.")

if st.button("⟲  Load sovereign CDS spreads", key="load_cds"):
    with st.spinner("◆ pulling sovereign credit-default-swap spreads…"):
        st.session_state.cds_data = ai.load_cds(api_key)
    st.rerun()

def _cds_stress(bps):
    if bps is None:
        return ("—", "#8a8470")
    if bps < 100:
        return ("LOW", "#4ade80")
    if bps < 300:
        return ("ELEVATED", "#d6c645")
    if bps < 600:
        return ("HIGH", "#e0954c")
    return ("SEVERE", "#e05c5c")

cds = st.session_state.cds_data
if cds and cds.get("rows"):
    crows = sorted(cds["rows"], key=lambda x: -(x.get("cds") or 0))
    thead = ("<tr><th class='l'>Country</th><th>CDS 5Y</th><th>1W</th><th>1M</th>"
             "<th>Trend</th><th>Stress</th><th class='l'>Driver</th></tr>")
    body = []
    for r in crows[:25]:
        lvl, col = _cds_stress(r.get("cds"))
        body.append(
            "<tr>"
            f"<td class='l tk'>{theme.esc(r.get('country',''))}</td>"
            f"<td>{fmt_num(r.get('cds'),0,' bps')}</td>"
            f"<td>{fmt_pct(r.get('w_chg'),0) if r.get('w_chg') is not None else '<span class=mut>—</span>'}</td>"
            f"<td>{fmt_pct(r.get('m_chg'),0) if r.get('m_chg') is not None else '<span class=mut>—</span>'}</td>"
            f"<td class='mut'>{theme.esc(r.get('trend',''))}</td>"
            f"<td><span class='pill' style='background:{col}22;color:{col};'>{lvl}</span></td>"
            f"<td class='l mut'>{theme.esc(r.get('note',''))}</td>"
            "</tr>"
        )
    st.markdown(f'<div class="table-scroll"><table class="sig-table">{thead}{"".join(body)}</table></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="sig-caption">As of: {theme.esc(cds.get("asof","recent estimate"))}</div>',
                unsafe_allow_html=True)
else:
    st.markdown('<div class="sig-caption">No CDS data loaded yet.</div>', unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
# V — DEBT CYCLE TRACKER
# ═════════════════════════════════════════════════════════════════════════════
theme.section_header("V", "DEBT CYCLE TRACKER", "debtcycle")
theme.caption(f"Ray Dalio MP0–MP3 framework. Structural indicators are a framework baseline "
              f"({dc.DEBT_ASOF}); the generated memo verifies current figures via web search.")

sel = st.selectbox("Country", dc.COUNTRY_ORDER, key="dc_country")
b = dc.COUNTRY_BASELINES[sel]
pcol = dc.phase_color(b["phase"])
st.markdown(
    f'<div class="dc-card"><div class="dc-name">{theme.esc(sel)}</div>'
    f'<span class="dc-phase" style="background:{pcol}33;color:{pcol};">'
    f'{dc.phase_label(b["phase"])} · {theme.esc(b["sub"])}</span>'
    f'<div class="dc-ind">'
    f'<span class="k">Debt / GDP</span><span class="v">{b["debt_gdp"]}%</span>'
    f'<span class="k">Real policy rate</span><span class="v">{b["real_rate"]:+.1f}%</span>'
    f'<span class="k">CB balance sheet</span><span class="v">{b["cb_bs"]}% GDP</span>'
    f'<span class="k">Fiscal balance</span><span class="v">{b["deficit"]:+.1f}% GDP</span>'
    f'</div>'
    f'<div class="sig-caption" style="margin-top:0.8rem;">Cycle marker — {theme.esc(b["start"])}</div>'
    f'<div class="sig-caption">Parallel — {theme.esc(b["parallel"])}</div>'
    f'</div>',
    unsafe_allow_html=True,
)

if st.button(f"◆  Generate {sel} debt-cycle memo", key="gen_debt_memo"):
    st.session_state.debt_memo.pop(sel, None)
    theme.subheader(f"Debt Cycle Memo · {sel}")
    text = run_stream(ai.prompt_debt_memo(today_str(), sel, b), err_prefix="Error")
    st.session_state.debt_memo[sel] = text
elif st.session_state.debt_memo.get(sel):
    theme.subheader(f"Debt Cycle Memo · {sel}")
    with st.container(border=True):
        st.markdown(f'<div class="memo-body">{st.session_state.debt_memo[sel]}</div>',
                    unsafe_allow_html=True)

if st.session_state.debt_memo.get(sel):
    pdf_button("⬇  Download Debt-Cycle Memo (PDF)", "DebtCycle", f"DEBT CYCLE — {sel}",
               today_str(), f"## {sel}\n\n{st.session_state.debt_memo[sel]}", sel, key="dl_debt")

# ── Central Bank Policy Tracker ──────────────────────────────────────────────
theme.subheader("Central Bank Policy Tracker")
if st.button("⟲  Load central-bank policy tracker", key="load_cb"):
    with st.spinner("◆ pulling current policy rates…"):
        st.session_state.cb_data = ai.load_central_banks(api_key)
    st.rerun()

cb = st.session_state.cb_data
if cb and cb.get("rows"):
    thead = ("<tr><th class='l'>Central Bank</th><th class='l'>Country</th><th>Rate</th>"
             "<th>Dir</th><th>CPI</th><th>Real</th><th>MP</th><th class='l'>Next</th></tr>")
    body = []
    DIRC = {"HIKING": ("▲ HIKING", "#e05c5c"), "CUTTING": ("▼ CUTTING", "#4ade80"),
            "PAUSED": ("— PAUSED", "#8a8470")}
    for r in cb["rows"]:
        dlabel, dcol = DIRC.get((r.get("direction") or "").upper(), ("—", "#8a8470"))
        rate = r.get("rate"); cpi = r.get("cpi")
        real = (rate - cpi) if (isinstance(rate, (int, float)) and isinstance(cpi, (int, float))) else None
        real_html = (f'<span class="{"neg" if real < 0 else "pos"}">{real:+.1f}%</span>'
                     if real is not None else '<span class="mut">—</span>')
        mp = (r.get("mp_phase") or "").upper()
        mpcol = dc.phase_color(mp) if mp in ("MP1", "MP2", "MP3", "TRANSITIONING") else "#8a8470"
        body.append(
            "<tr>"
            f"<td class='l tk'>{theme.esc(r.get('bank',''))}</td>"
            f"<td class='l mut'>{theme.esc(r.get('country',''))}</td>"
            f"<td>{fmt_num(rate,2,'%')}</td>"
            f"<td style='color:{dcol};'>{dlabel}</td>"
            f"<td>{fmt_num(cpi,1,'%')}</td>"
            f"<td>{real_html}</td>"
            f"<td><span class='pill' style='background:{mpcol}22;color:{mpcol};'>{mp or '—'}</span></td>"
            f"<td class='l mut'>{theme.esc(r.get('next_meeting','TBD'))}</td>"
            "</tr>"
        )
    st.markdown(f'<div class="table-scroll"><table class="sig-table">{thead}{"".join(body)}</table></div>',
                unsafe_allow_html=True)
    if cb.get("commentary"):
        with st.container(border=True):
            st.markdown(f'<div class="memo-body">{cb["commentary"]}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="sig-caption">No central-bank data loaded yet.</div>', unsafe_allow_html=True)

# ── Currency Debasement Dashboard ────────────────────────────────────────────
theme.subheader("Currency Debasement vs Gold")
theme.caption("5-year change of each currency measured against gold (negative = debased). "
              "Live from yfinance gold + FX histories.")

with st.spinner("◆ computing currency debasement vs gold…"):
    debase = mkt.fetch_currency_debasement()

valid = [d for d in debase if d.get("chg5y") is not None]
if valid:
    lo = min(d["chg5y"] for d in valid)
    hi = max(d["chg5y"] for d in valid)
    span = max(abs(lo), abs(hi), 1.0)
    bars = []
    for d in sorted(valid, key=lambda x: x["chg5y"]):
        v = d["chg5y"]
        clipped = max(-100.0, min(100.0, v))
        width = abs(clipped) / 100.0 * 50.0  # half-track max 50%
        color = "#4ade80" if v >= 0 else ("#e05c5c" if v > -90 else "#8b0000")
        side = "left:50%;" if v >= 0 else f"left:{50 - width}%;"
        tag = f"{v:+.0f}%" + (" (clipped)" if abs(v) > 100 else "")
        bars.append(
            f'<div style="display:flex;align-items:center;gap:8px;margin:3px 0;font-size:11px;">'
            f'<span style="width:120px;color:#c9a84c;">{theme.esc(d["label"])}</span>'
            f'<div style="position:relative;flex:1;height:14px;background:#141414;border:1px solid #1e1e1e;">'
            f'<div style="position:absolute;top:0;height:100%;width:1px;left:50%;background:#3a3a3a;"></div>'
            f'<div style="position:absolute;top:0;height:100%;{side}width:{width}%;background:{color};"></div>'
            f'</div>'
            f'<span style="width:90px;text-align:right;color:{color};">{tag}</span>'
            f'</div>'
        )
    st.markdown('<div class="table-scroll" style="padding:10px;">' + "".join(bars) + "</div>",
                unsafe_allow_html=True)

    srt = sorted(valid, key=lambda x: x["chg5y"])
    dcol1, dcol2 = st.columns(2)
    with dcol1:
        theme.subheader("Most Debased (5y)")
        for d in srt[:5]:
            st.markdown(f'<div class="sig-caption" style="font-size:12px;">'
                        f'<span style="color:#e05c5c;">▼</span> {theme.esc(d["label"])} '
                        f'{d["chg5y"]:+.0f}%</div>', unsafe_allow_html=True)
    with dcol2:
        theme.subheader("Most Stable (5y)")
        for d in reversed(srt[-5:]):
            st.markdown(f'<div class="sig-caption" style="font-size:12px;">'
                        f'<span style="color:#4ade80;">▲</span> {theme.esc(d["label"])} '
                        f'{d["chg5y"]:+.0f}%</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="sig-caption">Debasement data unavailable (FX feed unreachable).</div>',
                unsafe_allow_html=True)

if st.button("⟲  Load debasement commentary", key="load_debase"):
    with st.spinner("◆ connecting debasement to the MP3 thesis…"):
        st.session_state.debase_comment = ai.load_debasement_commentary(api_key, debase)
    st.rerun()
if st.session_state.debase_comment:
    with st.container(border=True):
        st.markdown(f'<div class="memo-body">{st.session_state.debase_comment}</div>',
                    unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
# VI — THESIS WAR ROOM
# ═════════════════════════════════════════════════════════════════════════════
theme.section_header("VI", "THESIS WAR ROOM", "portfolio")
theme.caption("Live agent check on every position (auto-fires once per session). "
              "Run a stress test on demand; track the standing macro theses.")

if st.button("↻  Refresh Pulse", key="pulse_refresh"):
    st.session_state.pulse_results = {}
    st.rerun()


def _alert_html(ticker):
    rows = position_alerts.get(ticker, [])
    if not rows:
        return ""
    pieces = [f"◈ VALUATION SIGNAL {a['country']}: {a['prev_band']} → {a['new_band']}" for a in rows]
    return '<div class="val-signal">' + "<br>".join(pieces) + "</div>"


def card_html(pos, text):
    if text is None:
        return (f'<div class="pulse-card skeleton"><div class="ticker">{pos["ticker"]}</div>'
                f'<div class="company">{pos["name"]}</div>'
                f'<div class="weight">{pos["weight"]} weight</div><div class="body"></div></div>')
    label, color = parse_status(text)
    body = _html.escape(text).replace("\n", "<br>")
    return (f'<div class="pulse-card"><div class="ticker">{pos["ticker"]}</div>'
            f'<div class="company">{pos["name"]}</div>'
            f'<div class="weight">{pos["weight"]} weight</div>'
            f'<span class="status-badge" style="background:{color}20;color:{color};border:1px solid {color};">{label}</span>'
            f'<div class="body">{body}</div>{_alert_html(pos["ticker"])}</div>')


def stress_card_html(res):
    momentum = (res.get("momentum") or "NEUTRAL").upper()
    cls = {"STRENGTHENING": "strong", "WEAKENING": "weak"}.get(momentum, "neutral")
    mcol = {"STRENGTHENING": "#4ade80", "WEAKENING": "#e05c5c"}.get(momentum, "#c9a84c")
    helps = "".join(f"<div class='row' style='color:#86efac;'>+ {theme.esc(h)}</div>"
                    for h in (res.get("helps") or [])[:4])
    hurts = "".join(f"<div class='row' style='color:#fca5a5;'>− {theme.esc(h)}</div>"
                    for h in (res.get("hurts") or [])[:4])
    return (f'<div class="stress-card {cls}">'
            f'<div class="lbl">Helps (+{res.get("help_score","?")})</div>{helps or "<div class=row>—</div>"}'
            f'<div class="lbl" style="margin-top:8px;">Hurts (−{res.get("hurt_score","?")})</div>{hurts or "<div class=row>—</div>"}'
            f'<div style="margin-top:10px;">'
            f'<span class="pill" style="background:{mcol}22;color:{mcol};">{momentum}</span> '
            f'<span class="pill" style="background:#c9a84c22;color:#c9a84c;">ACTION: {theme.esc(res.get("action","WATCH"))}</span>'
            f'</div>'
            f'<div class="row" style="margin-top:8px;color:#e8e3d6;">{theme.esc(res.get("summary",""))}</div>'
            f'</div>')


pulse_status = st.empty()
slots, stress_slots = {}, {}
for row_positions in (POSITIONS[:2], POSITIONS[2:]):
    cols = st.columns(2, gap="small")
    for col, pos in zip(cols, row_positions):
        with col:
            slots[pos["ticker"]] = st.empty()
            if st.button(f"⚡ Stress Test · {pos['ticker']}", key=f"stress_{pos['ticker']}"):
                st.session_state.run_stress = pos["ticker"]
            stress_slots[pos["ticker"]] = st.empty()

# initial render (cached or skeleton)
for pos in POSITIONS:
    slots[pos["ticker"]].markdown(
        card_html(pos, st.session_state.pulse_results.get(pos["ticker"])),
        unsafe_allow_html=True)

# fire missing pulse calls sequentially (15s gaps, with countdown)
missing = [p for p in POSITIONS if p["ticker"] not in st.session_state.pulse_results]
if missing:
    today = today_str()
    for j, pos in enumerate(missing):
        if j > 0:
            for rem in range(15, 0, -1):
                pulse_status.markdown(
                    f'<div class="sig-caption">⏳ rate-limit pause · next position ({pos["ticker"]}) in {rem}s…</div>',
                    unsafe_allow_html=True)
                time.sleep(1)
        pulse_status.markdown(
            f'<div class="sig-caption"><span class="dot" style="background:#c9a84c;"></span>'
            f'researching {pos["ticker"]}…</div>', unsafe_allow_html=True)
        try:
            text = call_research(prompt_pulse(today, pos), api_key, max_tokens=1500) or "_No response._"
        except anthropic.APIStatusError as e:
            text = f"_API error: {getattr(e, 'message', str(e))}_"
        except Exception as e:  # noqa: BLE001
            text = f"_Error: {e}_"
        st.session_state.pulse_results[pos["ticker"]] = text
        slots[pos["ticker"]].markdown(card_html(pos, text), unsafe_allow_html=True)
    pulse_status.empty()

# render any existing stress results
for pos in POSITIONS:
    res = st.session_state.stress_results.get(pos["ticker"])
    if res:
        stress_slots[pos["ticker"]].markdown(stress_card_html(res), unsafe_allow_html=True)

# handle a freshly requested stress test
if st.session_state.run_stress:
    tkr = st.session_state.run_stress
    st.session_state.run_stress = None
    pos = next((p for p in POSITIONS if p["ticker"] == tkr), None)
    if pos:
        with st.spinner(f"◆ stress-testing {tkr}…"):
            res = ai.load_stress_test(api_key, tkr, pos["name"], pos["thesis"])
        if res:
            st.session_state.stress_results[tkr] = res
            stress_slots[tkr].markdown(stress_card_html(res), unsafe_allow_html=True)

# Portfolio Pulse PDF
if len(st.session_state.pulse_results) >= len(POSITIONS):
    lines = [f"# THESIS WAR ROOM · PORTFOLIO PULSE\n*{today_str()}*\n"]
    for pos in POSITIONS:
        text = st.session_state.pulse_results.get(pos["ticker"], "")
        label, _ = parse_status(text)
        lines.append(f"\n## {pos['ticker']} · {pos['name']} ({pos['weight']}) — {label}\n\n{text}\n")
        res = st.session_state.stress_results.get(pos["ticker"])
        if res:
            lines.append(f"\n*Stress test — momentum {res.get('momentum')}, action {res.get('action')}: "
                         f"{res.get('summary','')}*\n")
    pdf_button("⬇  Download Portfolio Pulse (PDF)", "PortfolioPulse", "PORTFOLIO PULSE",
               today_str(), "\n".join(lines), key="dl_pulse")

# ── Macro Thesis Tracker ─────────────────────────────────────────────────────
theme.subheader("Macro Thesis Tracker")
mcols = st.columns(3, gap="small")
for col, mt in zip(mcols, MACRO_THESES):
    with col:
        res = st.session_state.macro_results.get(mt["name"])
        if res:
            conf = res.get("confirmation", "?")
            status = (res.get("status") or "ACTIVE").upper()
            scol = {"ACTIVE": "#4ade80", "WATCH": "#d6c645", "PAUSED": "#8a8470"}.get(status, "#c9a84c")
            ev = "".join(f"<div class='row' style='font-size:12px;color:#e8e3d6;'>• {theme.esc(e)}</div>"
                         for e in (res.get("evidence") or [])[:3])
            inner = (f'<span class="pill" style="background:{scol}22;color:{scol};">{status}</span> '
                     f'<span class="pill" style="background:#c9a84c22;color:#c9a84c;">CONF {conf}/10</span>'
                     f'<div class="row" style="margin-top:8px;color:#e8e3d6;font-size:13px;">{theme.esc(res.get("summary",""))}</div>'
                     f'{ev}')
        else:
            inner = '<div class="sig-caption">Not yet updated.</div>'
        st.markdown(
            f'<div class="pulse-card" style="min-height:auto;">'
            f'<div class="ticker" style="font-size:1rem;">{theme.esc(mt["name"])}</div>'
            f'<div class="weight">est. {mt["established"]}</div>'
            f'<div class="body">{inner}</div></div>',
            unsafe_allow_html=True,
        )
        if st.button(f"⟲ Update", key=f"macro_{mt['name'][:12]}"):
            st.session_state.run_macro = mt["name"]

if st.session_state.run_macro:
    name = st.session_state.run_macro
    st.session_state.run_macro = None
    mt = next((m for m in MACRO_THESES if m["name"] == name), None)
    if mt:
        with st.spinner(f"◆ updating thesis: {name}…"):
            st.session_state.macro_results[name] = ai.load_macro_thesis(api_key, name, mt["desc"])
        st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# VII — EARNINGS CALENDAR
# ═════════════════════════════════════════════════════════════════════════════
theme.section_header("VII", "EARNINGS CALENDAR", "earnings")
theme.caption("Next earnings dates for holdings + sector-watch names. Generate a pre-earnings brief per position.")

PORTFOLIO_TICKERS = {"QCOM", "KMI", "CRM", "1810.HK"}
TICKER_TO_NAME = {
    "QCOM": "Qualcomm", "KMI": "Kinder Morgan", "CRM": "Salesforce", "1810.HK": "Xiaomi",
    "NVDA": "Nvidia", "AMD": "AMD", "TSM": "TSMC", "MSFT": "Microsoft", "GOOGL": "Alphabet",
    "META": "Meta", "OXY": "Occidental", "ET": "Energy Transfer", "WMB": "Williams",
    "ENB": "Enbridge", "ORCL": "Oracle", "SAP": "SAP", "SNOW": "Snowflake",
}


def _parse_calendar(raw):
    out = []
    for line in (raw or "").splitlines():
        line = line.strip().strip("`").strip()
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0] or len(parts[0]) > 12:
            continue
        out.append({"ticker": parts[0],
                    "date": parts[1] if len(parts) > 1 else "TBD",
                    "eps": parts[2] if len(parts) > 2 else "TBD",
                    "confidence": parts[3].lower() if len(parts) > 3 else "unknown"})
    return out


def _days_until(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        delta = (d - datetime.now(ZoneInfo("America/New_York")).date()).days
        return "passed" if delta < 0 else ("today" if delta == 0 else f"{delta}d")
    except Exception:
        return "—"


if st.button("⟲  Load / refresh calendar", key="load_cal"):
    st.session_state.earnings_calendar = None
    st.session_state.pre_earnings_briefs = {}

if st.session_state.earnings_calendar is None:
    with st.spinner("◆ fetching earnings calendar…"):
        try:
            raw = call_research(prompt_earnings_calendar(today_str()), api_key, max_tokens=1500)
            st.session_state.earnings_calendar = _parse_calendar(raw)
        except Exception as e:  # noqa: BLE001
            st.error(f"Calendar fetch failed: {e}")
            st.session_state.earnings_calendar = []

cal_rows = st.session_state.earnings_calendar or []
pf_rows = [r for r in cal_rows if r["ticker"].upper() in PORTFOLIO_TICKERS]
sw_rows = [r for r in cal_rows if r["ticker"].upper() not in PORTFOLIO_TICKERS]

if pf_rows:
    st.markdown('<div class="cal-row head"><span>Ticker</span><span class="nm">Name</span>'
                '<span>Date</span><span>EPS</span><span class="du">In</span></div>',
                unsafe_allow_html=True)
    for r in pf_rows:
        nm = TICKER_TO_NAME.get(r["ticker"].upper(), r["ticker"])
        date_disp = r["date"] if r["date"].upper() != "TBD" else "TBD — verify on IR page"
        st.markdown(
            f'<div class="cal-row"><span class="tk">{r["ticker"]}</span>'
            f'<span class="nm">{nm}</span><span class="dt">{date_disp}</span>'
            f'<span class="ep">{r["eps"]}</span><span class="du">{_days_until(r["date"])}</span></div>',
            unsafe_allow_html=True)
        bc, _ = st.columns([2, 3])
        with bc:
            if st.button(f"◆ Pre-Earnings Brief · {r['ticker']}", key=f"brief_{r['ticker']}"):
                st.session_state.active_brief_ticker = r["ticker"]
                st.session_state.pre_earnings_briefs.pop(r["ticker"], None)

if sw_rows:
    theme.subheader("Sector Watch")
    st.markdown('<div class="cal-row head"><span>Ticker</span><span class="nm">Name</span>'
                '<span>Date</span><span>EPS</span><span class="du">Conf</span></div>',
                unsafe_allow_html=True)
    for r in sw_rows:
        nm = TICKER_TO_NAME.get(r["ticker"].upper(), r["ticker"])
        date_disp = r["date"] if r["date"].upper() != "TBD" else "TBD"
        st.markdown(
            f'<div class="cal-row"><span class="tk">{r["ticker"]}</span>'
            f'<span class="nm">{nm}</span><span class="dt">{date_disp}</span>'
            f'<span class="ep">{r["eps"]}</span><span class="du">{r["confidence"]}</span></div>',
            unsafe_allow_html=True)

if not cal_rows:
    st.markdown('<div class="sig-caption" style="text-align:center;">NO CALENDAR DATA YET</div>',
                unsafe_allow_html=True)

if st.session_state.active_brief_ticker:
    tkr = st.session_state.active_brief_ticker
    edate = next((r["date"] for r in cal_rows if r["ticker"].upper() == tkr.upper()), "TBD")
    theme.subheader(f"Pre-Earnings Brief · {tkr} · {edate}")
    if tkr not in st.session_state.pre_earnings_briefs:
        text = run_stream(prompt_pre_earnings(today_str(), tkr, edate), err_prefix="Error")
        st.session_state.pre_earnings_briefs[tkr] = text
    else:
        with st.container(border=True):
            st.markdown(f'<div class="memo-body">{st.session_state.pre_earnings_briefs[tkr]}</div>',
                        unsafe_allow_html=True)
    bt = st.session_state.pre_earnings_briefs.get(tkr, "")
    if bt:
        pdf_button("⬇  Download Pre-Earnings Brief (PDF)", "PreEarnings",
                   f"PRE-EARNINGS BRIEF — {tkr}", f"{edate} · {today_str()}",
                   f"## {tkr}\n\n{bt}", tkr, key=f"dl_brief_{tkr}")


# ── Footer ───────────────────────────────────────────────────────────────────
st.markdown("<div style='height:3rem'></div>", unsafe_allow_html=True)
st.markdown(
    f'<div style="text-align:center;font-size:9px;color:#4a4538;letter-spacing:0.3em;'
    f'text-transform:uppercase;">SIGNAL · {MODEL} · web search enabled · '
    f'data: yfinance + live AI</div>',
    unsafe_allow_html=True,
)
