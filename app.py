"""
SIGNAL — Ani Singh Private Research Agent
Three modes: full 6-section daily cycle, topic deep dive, and an interactive
3D Global Markets globe. Powered by Claude with web search.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Generator
from zoneinfo import ZoneInfo

import anthropic
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

load_dotenv()

_GLOBE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "globe_component")
globe_markets_component = components.declare_component("signal_globe", path=_GLOBE_DIR)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 8000
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 6,
}

GOLD = "#c9a84c"
BG = "#0c0c0c"


def get_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        return None


def today_str() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %d, %Y")


def now_str() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M ET · %a %b %d")


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT — the lens
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a dedicated research agent for Anirudh Singh — a concentrated macro investor building toward running a concentrated macro fund.

His analytical framework:
- PRIMARY LENS: Ray Dalio — long-term debt cycle, changing world order, historical pattern recognition. Always ask: where are we in the machine?
- SECONDARY LENS: George Soros reflexivity — identify self-reinforcing loops between perception and fundamentals
- WRITING/THINKING DISCIPLINE: Howard Marks memo style — what is priced, where is the asymmetry, what is consensus wrong about, no filler, no hedging for cover
- INVESTING PRINCIPLES: Concentration with conviction, long time horizons, no external validation needed, obligation as risk management

His core positions:
- QUALCOMM (QCOM) — 40% portfolio weight, largest holding. Thesis: edge AI inference dominance in power-constrained environments, automotive revenue ramp, QTL licensing moat. Structural multi-year advantage over Nvidia/AMD in mobile/edge due to mobile power-constraint engineering heritage.
- KINDER MORGAN (KMI) — 17% portfolio weight, second largest holding. Energy midstream / pipeline infrastructure. Thesis: cash-flow-generative energy infrastructure, natural gas demand growth (including AI data center power demand), dividend yield, inflation-resilient real assets.
- SALESFORCE (CRM) — Thesis: agentic AI platform consolidation, enterprise software stickiness, AI workflow monetization
- XIAOMI (1810.HK) — Thesis: China consumer recovery, EV optionality, global hardware ecosystem expansion

Standing watch-items (check every run):
- Market sentiment — positioning, risk appetite, fear/greed, breadth, flows
- Edge AI inference adoption curve
- Semiconductor fab production capacity growth — TSMC ONLY
- Inference AI news — developments specific to AI inference (not just training)

ALWAYS: Use web search aggressively for current data and specific numbers. Apply the lens to everything — not just what happened, but what it means through the debt cycle, reflexivity, and risk asymmetry. Identify what consensus is missing. Write for a sophisticated investor who knows the basics — skip definitions, get to the edge.

Format your output as a Howard Marks memo: tight paragraphs, specific numbers, no throat-clearing. Use markdown headers (## or ###) sparingly to organize. Bold key claims with **double asterisks**. Never apologize for uncertainty — state your view."""


# ─────────────────────────────────────────────────────────────────────────────
# THE 6 RESEARCH PROMPTS
# ─────────────────────────────────────────────────────────────────────────────

def prompt_macro(today: str) -> str:
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


def prompt_earnings(today: str) -> str:
    return f"""Today is {today}. Use web search for all current data.

Produce the EARNINGS & CORPORATE section. Cover:
- Major earnings in trailing 48-72 hours: actual vs estimate, guidance revision, margin trajectory, what management didn't say
- Key reports due this week that move the macro or sector picture
- Semiconductor sector specifically: supply, pricing, capex, design wins (critical for QCOM thesis)
- Capital markets: debt issuance, refinancing stress, downgrades, defaults
- Major M&A, restructurings, corporate strategy shifts

Signal vs noise filter applied. Reflexivity lens: is any earnings narrative becoming self-reinforcing?"""


def prompt_ai_tech(today: str) -> str:
    return f"""Today is {today}. Use web search for all current data.

Produce the AI & TECHNOLOGY section. Cover:
- Edge AI inference adoption curve: on-device compute developments — this is the core QCOM structural thesis. New design wins, partnerships, adoption evidence?
- Inference AI news specifically: developments in AI inference (NOT training) — cost curves, inference-optimized chips, deployment at scale
- Semiconductor fab capacity — TSMC ONLY: production capacity growth, node ramp (N2, N3), capex, utilization, AI chip allocation. Focus exclusively on TSMC.
- Qualcomm, Apple, Nvidia, AMD silicon roadmap news as it relates to inference
- AI model releases and capability announcements relevant to inference demand
- One emerging inference-related signal most investors are not watching yet

Frame edge AI through Dalio: early-to-middle cycle technology shift. What is the reflexivity loop forming?"""


def prompt_geo(today: str) -> str:
    return f"""Today is {today}. Use web search for all current data.

Produce the GEOPOLITICAL section. Cover:
- Middle East energy: current status, escalation or de-escalation, oil supply implications (relevant to KMI energy thesis)
- US-China: trade actions, tech and semiconductor export restrictions, Taiwan developments (critical for TSMC capacity), capital flow implications
- Energy infrastructure and natural gas: policy, demand drivers including AI data center power buildout (relevant to KMI)
- Europe: energy security, political developments with market implications
- One flashpoint being underpriced by markets right now

Changing world order lens: which developments signal the structural transition Dalio describes?"""


def prompt_cross_asset(today: str) -> str:
    return f"""Today is {today}. Use web search for all current data.

Produce the CROSS-ASSET section. Cover:
- Equities: index levels, sector rotation, market breadth — is the rally narrow or broad?
- Rates: yield curve shape (2s10s spread), credit spreads IG and HY, MOVE index
- Commodities: WTI oil, gold (central bank demand signal), copper (growth signal)
- FX: DXY, key crosses, stress signals
- Volatility: VIX — fear or complacency?
- One cross-asset relationship breaking down or forming that most haven't noticed

Marks lens: where is risk being mispriced across these asset classes right now?"""


def prompt_synthesis(today: str) -> str:
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


def prompt_deep_dive(today: str, query: str) -> str:
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


def prompt_market_analysis(today: str, country: str) -> str:
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


MARKETS = [
    {"name": "United States",  "lat": 40.7,  "lng":  -74.0},
    {"name": "United Kingdom", "lat": 51.5,  "lng":   -0.1},
    {"name": "Japan",          "lat": 35.7,  "lng":  139.7},
    {"name": "Germany",        "lat": 50.1,  "lng":    8.7},
    {"name": "France",         "lat": 48.9,  "lng":    2.3},
    {"name": "China",          "lat": 31.2,  "lng":  121.5},
    {"name": "Hong Kong",      "lat": 22.3,  "lng":  114.2},
    {"name": "India",          "lat": 19.1,  "lng":   72.9},
    {"name": "Brazil",         "lat": -23.5, "lng":  -46.6},
    {"name": "Canada",         "lat": 43.7,  "lng":  -79.4},
    {"name": "Australia",      "lat": -33.9, "lng":  151.2},
    {"name": "South Korea",    "lat": 37.6,  "lng":  127.0},
    {"name": "Singapore",      "lat":  1.3,  "lng":  103.8},
    {"name": "Switzerland",    "lat": 47.4,  "lng":    8.5},
    {"name": "Saudi Arabia",   "lat": 24.7,  "lng":   46.7},
    {"name": "Taiwan",         "lat": 25.0,  "lng":  121.5},
    {"name": "Mexico",         "lat": 19.4,  "lng":  -99.1},
    {"name": "South Africa",   "lat": -26.2, "lng":   28.0},
]


SECTIONS = [
    ("MACRO & RATES", prompt_macro),
    ("EARNINGS & CORPORATE", prompt_earnings),
    ("AI & TECHNOLOGY", prompt_ai_tech),
    ("GEOPOLITICAL", prompt_geo),
    ("CROSS-ASSET", prompt_cross_asset),
    ("SYNTHESIS · POSITIONS · RISKS · SUBSTACK", prompt_synthesis),
]


# ─────────────────────────────────────────────────────────────────────────────
# STREAMING
# ─────────────────────────────────────────────────────────────────────────────

def stream_research(prompt: str, api_key: str) -> Generator[str, None, None]:
    """Stream text deltas from Claude with web search enabled."""
    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for event in stream:
            etype = getattr(event, "type", "")
            if etype == "content_block_start":
                block = getattr(event, "content_block", None)
                if block is not None and getattr(block, "type", "") == "server_tool_use":
                    yield "\n\n_◆ searching the web…_\n\n"
            elif etype == "content_block_delta":
                delta = getattr(event, "delta", None)
                if delta is not None and getattr(delta, "type", "") == "text_delta":
                    yield delta.text


# ─────────────────────────────────────────────────────────────────────────────
# PAGE / CSS
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SIGNAL · Ani Singh",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Inter:wght@300;400;500;600&display=swap');

html, body, .stApp {
    background-color: #0c0c0c !important;
    color: #e8e3d6 !important;
}

.stApp {
    background: radial-gradient(ellipse at top, #131210 0%, #0c0c0c 60%) !important;
}

body, p, li, span, div, .stMarkdown, .stMarkdown p {
    font-family: 'Cormorant Garamond', Georgia, serif !important;
    font-size: 1.08rem;
    line-height: 1.55;
    color: #e8e3d6 !important;
}

h1, h2, h3, h4 {
    font-family: 'Cormorant Garamond', Georgia, serif !important;
    color: #c9a84c !important;
    font-weight: 600 !important;
}

.stMarkdown h2 {
    border-bottom: 1px solid #2a261b;
    padding-bottom: 0.3rem;
    margin-top: 1.5rem;
}

strong, b {
    color: #f0e6c8 !important;
    font-weight: 600 !important;
}

a, a:visited {
    color: #c9a84c !important;
    text-decoration: none !important;
    border-bottom: 1px dotted #6a5828;
}

.signal-title {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 5.5rem;
    font-weight: 700;
    letter-spacing: 0.7rem;
    color: #c9a84c;
    margin: 0;
    line-height: 1;
    text-shadow: 0 0 30px rgba(201, 168, 76, 0.15);
}

.signal-subtitle {
    font-family: 'Inter', sans-serif;
    font-size: 0.7rem;
    font-weight: 500;
    letter-spacing: 0.4rem;
    color: #8a8470;
    margin-top: 0.7rem;
    text-transform: uppercase;
}

.signal-meta {
    font-family: 'Inter', sans-serif;
    font-size: 0.7rem;
    color: #6a6555;
    letter-spacing: 0.2rem;
    margin-top: 0.8rem;
    text-transform: uppercase;
}

.gold-rule {
    border: none;
    border-top: 1px solid #c9a84c;
    opacity: 0.25;
    margin: 1.5rem 0;
}

.stButton > button, .stDownloadButton > button {
    background-color: transparent !important;
    color: #c9a84c !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.25rem !important;
    text-transform: uppercase !important;
    border: 1px solid #c9a84c !important;
    padding: 0.7rem 1.8rem !important;
    border-radius: 1px !important;
    transition: all 0.2s ease;
    width: 100%;
}

.stButton > button:hover, .stDownloadButton > button:hover {
    background-color: #c9a84c !important;
    color: #0c0c0c !important;
}

.stButton > button:focus { box-shadow: none !important; outline: none !important; }

.stTextInput > div > div > input {
    background-color: #14130f !important;
    color: #e8e3d6 !important;
    border: 1px solid #2a261b !important;
    border-radius: 1px !important;
    font-family: 'Cormorant Garamond', Georgia, serif !important;
    font-size: 1.1rem !important;
    padding: 0.8rem 1rem !important;
}
.stTextInput > div > div > input:focus { border-color: #c9a84c !important; box-shadow: none !important; }

.section-card { margin-top: 2rem; margin-bottom: 0.5rem; }
.section-num {
    font-family: 'Inter', sans-serif;
    font-size: 0.65rem;
    color: #6a6555;
    letter-spacing: 0.3rem;
    text-transform: uppercase;
}
.section-name {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 1.9rem;
    color: #c9a84c;
    margin-top: 0.3rem;
    border-bottom: 1px solid #2a261b;
    padding-bottom: 0.4rem;
    font-weight: 600;
}

.stProgress > div > div > div > div { background-color: #c9a84c !important; }
.stProgress > div > div > div { background-color: #2a261b !important; }

.status-line {
    font-family: 'Inter', sans-serif;
    font-size: 0.72rem;
    color: #8a8470;
    letter-spacing: 0.2rem;
    text-transform: uppercase;
    margin-top: 0.4rem;
}

.stCode, code { background-color: #14130f !important; color: #e8e3d6 !important; font-size: 0.85rem !important; }

#MainMenu, footer, header { visibility: hidden; }

.block-container {
    padding-top: 2rem !important;
    max-width: 900px;
}

@media (max-width: 640px) {
    .signal-title { font-size: 3.4rem !important; letter-spacing: 0.4rem !important; }
    .signal-subtitle { font-size: 0.6rem !important; letter-spacing: 0.25rem !important; }
    .section-name { font-size: 1.4rem !important; }
    body, p, li, .stMarkdown p { font-size: 1rem !important; }
    .block-container { padding-top: 1rem !important; }
}
</style>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# HERO
# ─────────────────────────────────────────────────────────────────────────────

st.markdown(
    f"""
<div style="text-align:center; margin-top:1rem; margin-bottom:2rem;">
    <div class="signal-title">SIGNAL</div>
    <div class="signal-subtitle">Ani Singh · Private Research Agent</div>
    <div class="signal-meta">{now_str()}</div>
</div>
<hr class="gold-rule">
""",
    unsafe_allow_html=True,
)

if "memo_sections" not in st.session_state:
    st.session_state.memo_sections = []
if "memo_kind" not in st.session_state:
    st.session_state.memo_kind = None
if "memo_topic" not in st.session_state:
    st.session_state.memo_topic = ""
if "last_globe_click_id" not in st.session_state:
    st.session_state.last_globe_click_id = None

api_key = get_api_key()
if not api_key:
    st.error(
        "ANTHROPIC_API_KEY not set. Add it to .env locally, or to "
        "Streamlit Cloud secrets (Settings → Secrets) as "
        "`ANTHROPIC_API_KEY=\"sk-ant-…\"`."
    )
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# CONTROLS
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("<div class='status-line'>I · Full Research Cycle</div>", unsafe_allow_html=True)
run_full = st.button("◆  Run Full Research Cycle", key="run_full", use_container_width=True)

st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)
st.markdown("<div class='status-line'>II · Deep Dive</div>", unsafe_allow_html=True)

dive_col1, dive_col2 = st.columns([4, 1])
with dive_col1:
    topic = st.text_input(
        "topic",
        placeholder="e.g. Japan yield crisis · private credit stress · Qualcomm edge AI",
        label_visibility="collapsed",
        key="topic_input",
    )
with dive_col2:
    run_deep = st.button("Research", key="run_deep", use_container_width=True)

st.markdown("<hr class='gold-rule'>", unsafe_allow_html=True)

# ─── Section III · Global Markets ────────────────────────────────────────────
st.markdown("<div class='status-line'>III · Global Markets</div>", unsafe_allow_html=True)
st.markdown(
    "<div style='font-family:\"Inter\",sans-serif; font-size:0.7rem; color:#6a6555; "
    "letter-spacing:0.15rem; margin-top:0.4rem; margin-bottom:0.8rem;'>"
    "Tap a node to generate a country-level intelligence memo."
    "</div>",
    unsafe_allow_html=True,
)
globe_event = globe_markets_component(
    markets=MARKETS,
    height=560,
    key="signal_globe",
    default=None,
)

st.markdown("<hr class='gold-rule'>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

def render_section_header(num: str, name: str):
    st.markdown(
        f"""
<div class="section-card">
    <div class="section-num">§ {num}</div>
    <div class="section-name">{name}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def run_full_cycle():
    today = today_str()
    st.session_state.memo_sections = []
    st.session_state.memo_kind = "full"
    st.session_state.memo_topic = ""

    progress = st.progress(0.0, text="initializing…")

    for i, (title, build_prompt) in enumerate(SECTIONS):
        render_section_header(f"{i+1:02d} / {len(SECTIONS):02d}", title)
        progress.progress(i / len(SECTIONS), text=f"{title} …")

        try:
            full_text = st.write_stream(stream_research(build_prompt(today), api_key))
            if not isinstance(full_text, str):
                full_text = "".join(full_text) if full_text else ""
            st.session_state.memo_sections.append((title, full_text))
        except anthropic.APIStatusError as e:
            msg = getattr(e, "message", str(e))
            st.error(f"API error in {title}: {msg}")
            st.session_state.memo_sections.append((title, f"_API error: {msg}_"))
        except Exception as e:  # noqa: BLE001
            st.error(f"Error in {title}: {e}")
            st.session_state.memo_sections.append((title, f"_Error: {e}_"))

        progress.progress((i + 1) / len(SECTIONS), text=f"{title} complete")

    progress.progress(1.0, text="memo complete")


def run_deep_dive(query: str):
    today = today_str()
    st.session_state.memo_sections = []
    st.session_state.memo_kind = "deep"
    st.session_state.memo_topic = query

    render_section_header("DEEP DIVE", query.upper())
    try:
        full_text = st.write_stream(stream_research(prompt_deep_dive(today, query), api_key))
        if not isinstance(full_text, str):
            full_text = "".join(full_text) if full_text else ""
        st.session_state.memo_sections.append((query.upper(), full_text))
    except anthropic.APIStatusError as e:
        msg = getattr(e, "message", str(e))
        st.error(f"API error: {msg}")
        st.session_state.memo_sections.append((query.upper(), f"_API error: {msg}_"))
    except Exception as e:  # noqa: BLE001
        st.error(f"Error: {e}")
        st.session_state.memo_sections.append((query.upper(), f"_Error: {e}_"))


def run_market_analysis(country: str):
    today = today_str()
    st.session_state.memo_sections = []
    st.session_state.memo_kind = "market"
    st.session_state.memo_topic = country

    render_section_header("GLOBAL MARKETS", country.upper())
    try:
        full_text = st.write_stream(
            stream_research(prompt_market_analysis(today, country), api_key)
        )
        if not isinstance(full_text, str):
            full_text = "".join(full_text) if full_text else ""
        st.session_state.memo_sections.append((country.upper(), full_text))
    except anthropic.APIStatusError as e:
        msg = getattr(e, "message", str(e))
        st.error(f"API error: {msg}")
        st.session_state.memo_sections.append((country.upper(), f"_API error: {msg}_"))
    except Exception as e:  # noqa: BLE001
        st.error(f"Error: {e}")
        st.session_state.memo_sections.append((country.upper(), f"_Error: {e}_"))


def assemble_full_memo() -> str:
    today = today_str()
    if st.session_state.memo_kind == "deep":
        header = f"# SIGNAL · DEEP DIVE\n## {st.session_state.memo_topic}\n*{today}*\n\n---\n\n"
    elif st.session_state.memo_kind == "market":
        header = (
            f"# SIGNAL · GLOBAL MARKETS\n"
            f"## {st.session_state.memo_topic}\n*{today}*\n\n---\n\n"
        )
    else:
        header = f"# SIGNAL · DAILY MEMO\n*{today}*\n\n---\n\n"
    body = "\n\n---\n\n".join(
        f"## {title}\n\n{text}" for title, text in st.session_state.memo_sections
    )
    return header + body


# Detect a fresh globe click (deduplicated by click_id)
new_globe_click = None
if isinstance(globe_event, dict):
    cid = globe_event.get("click_id")
    if cid and cid != st.session_state.get("last_globe_click_id"):
        st.session_state.last_globe_click_id = cid
        new_globe_click = globe_event.get("country")

if run_full:
    run_full_cycle()
elif run_deep and topic.strip():
    run_deep_dive(topic.strip())
elif run_deep and not topic.strip():
    st.warning("Enter a topic first.")
elif new_globe_click:
    run_market_analysis(new_globe_click)

# ─────────────────────────────────────────────────────────────────────────────
# COPY / DOWNLOAD
# ─────────────────────────────────────────────────────────────────────────────

if st.session_state.memo_sections:
    st.markdown("<hr class='gold-rule'>", unsafe_allow_html=True)
    st.markdown("<div class='status-line'>Export</div>", unsafe_allow_html=True)

    full_memo = assemble_full_memo()
    today_slug = today_str().replace(",", "").replace(" ", "-")
    kind = {
        "deep": "deep-dive",
        "market": "market",
        "full": "daily",
    }.get(st.session_state.memo_kind, "memo")

    topic_slug = (
        "-" + st.session_state.memo_topic.lower().replace(" ", "-")
        if st.session_state.memo_kind in ("deep", "market") and st.session_state.memo_topic
        else ""
    )
    col_a, col_b = st.columns(2)
    with col_a:
        st.download_button(
            "◆  Download Memo (.md)",
            data=full_memo,
            file_name=f"signal-{kind}{topic_slug}-{today_slug}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with col_b:
        show_copy = st.toggle("Show copy-ready text", value=False)

    if show_copy:
        st.markdown(
            "<div class='status-line'>Tap the copy icon at the top-right of the block</div>",
            unsafe_allow_html=True,
        )
        st.code(full_memo, language="markdown")

st.markdown("<div style='height:4rem'></div>", unsafe_allow_html=True)
st.markdown(
    f"""
<div style="text-align:center; font-family:'Inter',sans-serif; font-size:0.6rem;
            color:#4a4538; letter-spacing:0.3rem; text-transform:uppercase;
            margin-top:2rem;">
    Signal · {MODEL} · web search enabled
</div>
""",
    unsafe_allow_html=True,
)
