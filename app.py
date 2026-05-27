"""
SIGNAL — Ani Singh Private Research Agent
Five modes:
  I    Full 6-section daily research cycle
  II   Topic deep dive
  III  Interactive 3D Global Markets globe (P/E color-coded)
  IV   Portfolio Pulse — auto-fires on every fresh session
  V    Earnings Calendar with per-position pre-earnings briefs
Plus PDF download buttons on every research output.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Generator
from zoneinfo import ZoneInfo

import anthropic
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

import valuation as val
import pdf_export

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
# PORTFOLIO POSITIONS — used by Section IV (Pulse) and Section V (Calendar)
# ─────────────────────────────────────────────────────────────────────────────

POSITIONS = [
    {
        "ticker": "QCOM",
        "yf_ticker": "QCOM",
        "name": "QUALCOMM",
        "weight": "40%",
        "thesis": (
            "Edge AI inference dominance in power-constrained environments, "
            "automotive revenue ramp targeting $4B by 2026, QTL licensing moat, "
            "structural multi-year advantage over Nvidia and AMD at the edge "
            "due to mobile power-constraint engineering heritage. TSMC N2 "
            "capacity ramp is a direct tailwind for QCOM product roadmap."
        ),
    },
    {
        "ticker": "KMI",
        "yf_ticker": "KMI",
        "name": "KINDER MORGAN",
        "weight": "17%",
        "thesis": (
            "Cash-flow-generative midstream energy infrastructure, natural gas "
            "demand growth driven by AI data center power buildout, 4–6% dividend "
            "yield, inflation-resilient real asset, long-duration pipeline "
            "contracts insulated from commodity price swings."
        ),
    },
    {
        "ticker": "CRM",
        "yf_ticker": "CRM",
        "name": "SALESFORCE",
        "weight": "core",
        "thesis": (
            "Agentic AI platform consolidation, enterprise software stickiness, "
            "Agentforce as the dominant AI workflow layer for enterprise, "
            "remaining performance obligation as forward revenue visibility signal."
        ),
    },
    {
        "ticker": "XIAOMI",
        "yf_ticker": "1810.HK",
        "name": "XIAOMI",
        "weight": "core",
        "thesis": (
            "China consumer recovery, EV optionality with growing delivery numbers, "
            "global hardware ecosystem expansion, India smartphone market share. "
            "Watch India revenue concentration — if above 30% of total, India "
            "credit cycle becomes position-sizing concern."
        ),
    },
]


def prompt_pulse(today: str, pos: dict) -> str:
    return f"""Today is {today}. Use web search.

Position check for {pos['yf_ticker']} ({pos['name']}), {pos['weight']} of portfolio.

Core thesis: {pos['thesis']}

In 4–5 sentences cover:
1. Any material news, earnings, analyst actions, or price target changes in the last 48 hours
2. Any development that directly strengthens or challenges the core thesis
3. Status verdict: THESIS INTACT, WATCH, or ALERT and one sentence explaining why

Be direct. No filler. If nothing material happened say so plainly."""


def prompt_earnings_calendar(today: str) -> str:
    return f"""Today is {today}. Use web search to find the next confirmed earnings date for each ticker below. Search investor-relations pages and reliable earnings sites (Zacks, Earnings Whispers, Nasdaq).

PORTFOLIO POSITIONS:
- QCOM (Qualcomm)
- KMI (Kinder Morgan)
- CRM (Salesforce)
- 1810.HK (Xiaomi)

SECTOR WATCH:
- NVDA, AMD, TSM, MSFT, GOOGL, META  (AI / semiconductor — move QCOM)
- OXY, ET, WMB, ENB                   (energy infrastructure — move KMI)
- ORCL, SAP, SNOW                     (enterprise software — move CRM)

Output ONE line per ticker in EXACTLY this pipe-delimited format:

TICKER | YYYY-MM-DD | EPS_ESTIMATE | CONFIDENCE

Where:
- TICKER: the symbol as listed above
- YYYY-MM-DD: expected earnings date; use TBD if not confirmed
- EPS_ESTIMATE: consensus EPS estimate as a number with $ (e.g. $2.35) or TBD
- CONFIDENCE: one of `confirmed`, `estimated`, `unknown`

Output ONLY these lines — no commentary, no headers, no markdown fences."""


def prompt_pre_earnings(today: str, ticker: str, earnings_date: str) -> str:
    ticker_blocks = {
        "QCOM": """For QCOM specifically watch:
- Automotive segment revenue (thesis: $4B by 2026)
- IoT segment revenue trend
- Handset unit guidance and ASP
- Any edge AI or on-device AI design win commentary
- QTL licensing revenue and royalty rate""",
        "KMI": """For KMI specifically watch:
- Natural gas throughput volumes
- Natural gas demand commentary — any AI data center customer mentions
- LNG export capacity utilization
- Dividend guidance or coverage ratio""",
        "CRM": """For CRM specifically watch:
- Agentforce seat adoption and revenue attach rate
- Remaining Performance Obligation growth (forward revenue signal)
- AI-driven deal sizes vs traditional deals
- Net revenue retention rate""",
        "XIAOMI": """For Xiaomi specifically watch:
- EV delivery numbers and margin per unit
- India revenue as % of total (alert if above 30%)
- Gross margin trajectory across segments
- Any commentary on China consumer demand trends""",
        "1810.HK": """For Xiaomi specifically watch:
- EV delivery numbers and margin per unit
- India revenue as % of total (alert if above 30%)
- Gross margin trajectory across segments
- Any commentary on China consumer demand trends""",
    }
    watch = ticker_blocks.get(ticker.upper(), "")
    return f"""Today is {today}. Use web search.

Pre-earnings intelligence brief for {ticker} reporting approximately {earnings_date}.

1. CONSENSUS EXPECTATIONS
What is the street expecting for EPS, revenue, and key segment metrics? What is the whisper number vs official consensus?

2. WHAT TO WATCH
The 2–3 specific data points or guidance language that will move the stock.

{watch}

3. THESIS CHECK SCENARIOS
What results would strengthen the thesis? What would challenge it? Specific numbers.

4. HISTORICAL EARNINGS PATTERN
How has this stock reacted to beats vs misses over the last 4 quarters? Any consistent pattern?

5. POSITIONING INTO THE PRINT
Given current valuation and thesis conviction, what is the rational response to a beat, a miss, and an in-line result?

Howard Marks memo style. Specific numbers only. No generic statements."""


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


def call_research(prompt: str, api_key: str, max_tokens: int = 2000) -> str:
    """Non-streaming Claude call with web search. Returns concatenated text."""
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        tools=[WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": prompt}],
    )
    parts: list[str] = []
    for block in resp.content:
        if getattr(block, "type", "") == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts).strip()


def parse_status(text: str) -> tuple[str, str]:
    """Return (label, hex_color) verdict for a position pulse response."""
    upper = text.upper()
    # Order matters — most-severe wins
    if "ALERT" in upper and "ALERT TRIGGER" not in upper.replace("ALERT", "ALERT", 1):
        return ("ALERT", "#ef4444")
    if "WATCH" in upper:
        return ("WATCH", "#f59e0b")
    if "THESIS INTACT" in upper or "INTACT" in upper:
        return ("THESIS INTACT", "#4ade80")
    return ("PENDING", "#8a8470")


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

/* ── Valuation legend (below globe) ─────────────────────────────────── */
.legend-row {
    display: flex; flex-wrap: wrap; justify-content: center; gap: 14px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px; letter-spacing: 0.15em;
    color: #8a8470; margin-top: 0.6rem; margin-bottom: 0.4rem;
}
.legend-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    margin-right: 5px; vertical-align: middle; }

/* ── Valuation alert banner above globe ─────────────────────────────── */
.val-alert {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px; letter-spacing: 0.1em;
    padding: 8px 12px; margin: 6px 0;
    border-radius: 2px; border-width: 1px; border-style: solid;
}
.val-alert.up   { background: rgba(239, 68, 68, 0.12); border-color: #ef4444; color: #fca5a5; }
.val-alert.down { background: rgba(74, 222, 128, 0.12); border-color: #4ade80; color: #86efac; }

/* ── Portfolio Pulse cards ──────────────────────────────────────────── */
.pulse-card {
    background: #131210;
    border: 1px solid #2a261b;
    border-left: 3px solid #c9a84c;
    border-radius: 2px;
    padding: 1rem 1.1rem;
    margin-bottom: 0.8rem;
    min-height: 200px;
    font-family: 'Cormorant Garamond', Georgia, serif;
}
.pulse-card .ticker {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.5rem; font-weight: 600; color: #c9a84c;
    letter-spacing: 0.1em;
}
.pulse-card .company {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem; color: #8a8470;
    letter-spacing: 0.25em; text-transform: uppercase;
    margin-bottom: 0.4rem;
}
.pulse-card .weight {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem; color: #6a6555;
    letter-spacing: 0.25em; text-transform: uppercase;
}
.pulse-card .status-badge {
    display: inline-block;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem; font-weight: 600;
    letter-spacing: 0.25em; text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 1px;
    margin-top: 0.4rem;
}
.pulse-card .body {
    font-size: 0.95rem; line-height: 1.5;
    color: #e8e3d6; margin-top: 0.7rem;
}
.pulse-card .val-signal {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px; color: #c9a84c;
    letter-spacing: 0.1em; margin-top: 0.6rem;
    padding-top: 0.4rem; border-top: 1px dotted #2a261b;
}
.pulse-card.skeleton .body::after {
    content: "researching…";
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem; color: #6a6555; letter-spacing: 0.25em;
    animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 0.9; } }

/* ── Earnings Calendar rows ─────────────────────────────────────────── */
.cal-row {
    display: grid;
    grid-template-columns: 80px 1fr 130px 90px 100px;
    gap: 0.8rem; align-items: center;
    padding: 0.7rem 0.9rem;
    border-bottom: 1px solid #1f1c14;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
}
.cal-row .tk { color: #c9a84c; font-weight: 600; letter-spacing: 0.15em; }
.cal-row .nm { color: #e8e3d6; font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 1rem; }
.cal-row .dt { color: #e8e3d6; letter-spacing: 0.1em; }
.cal-row .ep { color: #8a8470; letter-spacing: 0.1em; }
.cal-row .du { color: #6a6555; letter-spacing: 0.15em; text-align: right; }
.cal-row.head {
    color: #6a6555; font-size: 0.65rem;
    letter-spacing: 0.3em; text-transform: uppercase;
    border-bottom: 1px solid #c9a84c; opacity: 0.55;
}
.cal-row.head .nm { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; }
.sector-watch-row {
    display: grid;
    grid-template-columns: 80px 1fr 130px 100px;
    gap: 0.8rem; padding: 0.5rem 0.9rem;
    border-bottom: 1px solid #1f1c14;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
}
.sector-watch-row .tk { color: #c9a84c; letter-spacing: 0.15em; }
.sector-watch-row .dt { color: #e8e3d6; }
.sector-watch-row .ep { color: #8a8470; }
.sector-watch-row .cf { color: #6a6555; text-align: right; letter-spacing: 0.2em; }

@media (max-width: 640px) {
    .signal-title { font-size: 3.4rem !important; letter-spacing: 0.4rem !important; }
    .signal-subtitle { font-size: 0.6rem !important; letter-spacing: 0.25rem !important; }
    .section-name { font-size: 1.4rem !important; }
    body, p, li, .stMarkdown p { font-size: 1rem !important; }
    .block-container { padding-top: 1rem !important; }
    .cal-row, .sector-watch-row { grid-template-columns: 1fr; gap: 0.2rem; }
    .cal-row .du { text-align: left; }
    .legend-row { gap: 8px; font-size: 9px; }
}
</style>
""",
    unsafe_allow_html=True,
)

# Import JetBrains Mono once
st.markdown(
    "<link href='https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap' rel='stylesheet'>",
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
    "letter-spacing:0.15rem; margin-top:0.4rem; margin-bottom:0.6rem;'>"
    "Nodes color-coded by trailing P/E. Tap a node for a country memo."
    "</div>",
    unsafe_allow_html=True,
)

# Fetch P/E once per session (24h cache), enrich markets, compute alerts
pe_map = val.fetch_pe_ratios()
if "valuation_alerts" not in st.session_state:
    st.session_state.valuation_alerts = val.update_history_and_alerts(pe_map)
valuation_alerts = st.session_state.valuation_alerts
position_alerts = val.alerts_for_position(valuation_alerts)

# Alert banners above the globe
for a in valuation_alerts:
    cls = "up" if a["direction"] == "expensive" else "down"
    prev_pe = f"{a['prev_pe']:.1f}x" if a.get("prev_pe") is not None else "—"
    new_pe = f"{a['new_pe']:.1f}x" if a.get("new_pe") is not None else "—"
    st.markdown(
        f"<div class='val-alert {cls}'>⚠  VALUATION SHIFT — "
        f"{a['country']} moved from {a['prev_band']} → {a['new_band']} "
        f"({prev_pe} → {new_pe})</div>",
        unsafe_allow_html=True,
    )

# Enrich markets with color, pe, band for the globe payload
markets_enriched = []
for m in MARKETS:
    pe = pe_map.get(m["name"])
    band, color = val.band_for(pe)
    markets_enriched.append({**m, "pe": pe, "band": band, "color": color})

globe_event = globe_markets_component(
    markets=markets_enriched,
    height=560,
    key="signal_globe",
    default=None,
)

# Color legend below the globe
st.markdown(
    """
<div class="legend-row">
    <span><span class="legend-dot" style="background:#4ade80"></span>CHEAP &lt;12x</span>
    <span><span class="legend-dot" style="background:#a3e635"></span>FAIR 12–16x</span>
    <span><span class="legend-dot" style="background:#f59e0b"></span>ELEVATED 16–20x</span>
    <span><span class="legend-dot" style="background:#f97316"></span>EXPENSIVE 20–24x</span>
    <span><span class="legend-dot" style="background:#ef4444"></span>VERY EXPENSIVE &gt;24x</span>
    <span><span class="legend-dot" style="background:#c9a84c"></span>NO DATA</span>
</div>
""",
    unsafe_allow_html=True,
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
# DOWNLOAD — PDF for whichever memo just rendered (I / II / III)
# ─────────────────────────────────────────────────────────────────────────────

if st.session_state.memo_sections:
    st.markdown("<div class='status-line'>Export</div>", unsafe_allow_html=True)

    full_memo = assemble_full_memo()
    kind = st.session_state.memo_kind

    if kind == "deep":
        pdf_section, btn_label = "DeepDive", "⬇  Download Deep Dive (PDF)"
        section_title = "DEEP DIVE"
    elif kind == "market":
        pdf_section, btn_label = "Globe", "⬇  Download Country Memo (PDF)"
        section_title = "GLOBAL MARKETS — " + st.session_state.memo_topic
    else:
        pdf_section, btn_label = "FullCycle", "⬇  Download Full Memo (PDF)"
        section_title = "FULL RESEARCH CYCLE"

    try:
        pdf_bytes = pdf_export.memo_to_pdf(
            section_title,
            today_str(),
            full_memo,
        )
        st.download_button(
            btn_label,
            data=pdf_bytes,
            file_name=pdf_export.filename(pdf_section, st.session_state.memo_topic),
            mime="application/pdf",
            use_container_width=True,
            key=f"dl_{kind}_pdf",
        )
    except Exception as e:  # noqa: BLE001
        st.error(f"PDF generation failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION IV — PORTFOLIO PULSE  (auto-fires once per session)
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("<hr class='gold-rule'>", unsafe_allow_html=True)
st.markdown("<div class='status-line'>IV · Portfolio Pulse</div>", unsafe_allow_html=True)
st.markdown(
    "<div style='font-family:\"Inter\",sans-serif; font-size:0.7rem; color:#6a6555; "
    "letter-spacing:0.15rem; margin-top:0.4rem; margin-bottom:0.8rem;'>"
    "Live agent check on every position. Auto-refreshes on each new session."
    "</div>",
    unsafe_allow_html=True,
)

if "pulse_results" not in st.session_state:
    st.session_state.pulse_results = {}  # ticker -> raw memo text

refresh_col, _ = st.columns([1, 4])
with refresh_col:
    if st.button("↻  Refresh Pulse", key="pulse_refresh", use_container_width=True):
        st.session_state.pulse_results = {}
        st.rerun()


def _alert_html_for_card(ticker: str) -> str:
    rows = position_alerts.get(ticker, [])
    if not rows:
        return ""
    pieces = []
    for a in rows:
        prev_pe = f"{a['prev_pe']:.1f}x" if a.get("prev_pe") is not None else "—"
        new_pe = f"{a['new_pe']:.1f}x" if a.get("new_pe") is not None else "—"
        pieces.append(
            f"◈ VALUATION SIGNAL  {a['country']}: "
            f"{a['prev_band']} → {a['new_band']} ({prev_pe} → {new_pe})"
        )
    return "<div class='val-signal'>" + "<br>".join(pieces) + "</div>"


def card_html(pos: dict, body_text: str | None) -> str:
    if body_text is None:
        return f"""
<div class="pulse-card skeleton">
    <div class="ticker">{pos['ticker']}</div>
    <div class="company">{pos['name']}</div>
    <div class="weight">{pos['weight']} weight</div>
    <div class="body"></div>
</div>
"""
    label, color = parse_status(body_text)
    import html as _html
    body_clean = _html.escape(body_text).replace("\n", "<br>")
    return f"""
<div class="pulse-card">
    <div class="ticker">{pos['ticker']}</div>
    <div class="company">{pos['name']}</div>
    <div class="weight">{pos['weight']} weight</div>
    <span class="status-badge"
          style="background:{color}20; color:{color}; border:1px solid {color};">
        {label}
    </span>
    <div class="body">{body_clean}</div>
    {_alert_html_for_card(pos['ticker'])}
</div>
"""


# 2x2 grid of placeholders
row1 = st.columns(2, gap="small")
row2 = st.columns(2, gap="small")
slots = [row1[0].empty(), row1[1].empty(), row2[0].empty(), row2[1].empty()]

# Initial render: from cache or skeleton
for i, pos in enumerate(POSITIONS):
    body = st.session_state.pulse_results.get(pos["ticker"])
    slots[i].markdown(card_html(pos, body), unsafe_allow_html=True)

# Fire missing ones sequentially with 15s delays
missing = [p for p in POSITIONS if p["ticker"] not in st.session_state.pulse_results]
if missing:
    today = today_str()
    for j, pos in enumerate(missing):
        if j > 0:
            time.sleep(15)
        try:
            text = call_research(prompt_pulse(today, pos), api_key, max_tokens=1500)
            if not text:
                text = "_No response received._"
        except anthropic.APIStatusError as e:
            text = f"_API error: {getattr(e, 'message', str(e))}_"
        except Exception as e:  # noqa: BLE001
            text = f"_Error: {e}_"
        st.session_state.pulse_results[pos["ticker"]] = text
        i = POSITIONS.index(pos)
        slots[i].markdown(card_html(pos, text), unsafe_allow_html=True)

# Once all four are present, offer a PDF
if len(st.session_state.pulse_results) >= len(POSITIONS):
    pulse_memo_lines = [f"# PORTFOLIO PULSE\n*{today_str()}*\n"]
    for pos in POSITIONS:
        text = st.session_state.pulse_results.get(pos["ticker"], "")
        label, _ = parse_status(text)
        pulse_memo_lines.append(
            f"\n## {pos['ticker']} · {pos['name']}  ({pos['weight']} weight) — {label}\n\n{text}\n"
        )
        for a in position_alerts.get(pos["ticker"], []):
            prev_pe = f"{a['prev_pe']:.1f}x" if a.get("prev_pe") is not None else "—"
            new_pe = f"{a['new_pe']:.1f}x" if a.get("new_pe") is not None else "—"
            pulse_memo_lines.append(
                f"\n*Valuation signal — {a['country']}: "
                f"{a['prev_band']} → {a['new_band']} ({prev_pe} → {new_pe})*\n"
            )
    pulse_memo = "\n".join(pulse_memo_lines)
    try:
        pulse_pdf = pdf_export.memo_to_pdf("PORTFOLIO PULSE", today_str(), pulse_memo)
        st.download_button(
            "⬇  Download Portfolio Pulse (PDF)",
            data=pulse_pdf,
            file_name=pdf_export.filename("PortfolioPulse"),
            mime="application/pdf",
            use_container_width=True,
            key="dl_pulse_pdf",
        )
    except Exception as e:  # noqa: BLE001
        st.error(f"Pulse PDF generation failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION V — EARNINGS CALENDAR
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("<hr class='gold-rule'>", unsafe_allow_html=True)
st.markdown("<div class='status-line'>V · Earnings Calendar</div>", unsafe_allow_html=True)
st.markdown(
    "<div style='font-family:\"Inter\",sans-serif; font-size:0.7rem; color:#6a6555; "
    "letter-spacing:0.15rem; margin-top:0.4rem; margin-bottom:0.8rem;'>"
    "Next earnings dates for portfolio holdings, plus sector-watch names that "
    "move them. Tap a position to generate a pre-earnings brief."
    "</div>",
    unsafe_allow_html=True,
)

if "earnings_calendar" not in st.session_state:
    st.session_state.earnings_calendar = None  # list of dicts once loaded
if "pre_earnings_briefs" not in st.session_state:
    st.session_state.pre_earnings_briefs = {}  # ticker -> text
if "active_brief_ticker" not in st.session_state:
    st.session_state.active_brief_ticker = None


def _parse_calendar(raw: str) -> list[dict]:
    rows = []
    for line in raw.splitlines():
        line = line.strip().strip("`").strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        ticker = parts[0]
        date = parts[1] if len(parts) > 1 else "TBD"
        eps = parts[2] if len(parts) > 2 else "TBD"
        conf = parts[3].lower() if len(parts) > 3 else "unknown"
        if not ticker or len(ticker) > 12:
            continue
        rows.append({"ticker": ticker, "date": date, "eps": eps, "confidence": conf})
    return rows


def _days_until(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = datetime.now(ZoneInfo("America/New_York")).date()
        delta = (d - today).days
        if delta < 0:
            return "passed"
        if delta == 0:
            return "today"
        if delta == 1:
            return "1 day"
        return f"{delta} days"
    except Exception:
        return "—"


PORTFOLIO_TICKERS = {"QCOM", "KMI", "CRM", "1810.HK"}
TICKER_TO_NAME = {
    "QCOM": "Qualcomm", "KMI": "Kinder Morgan",
    "CRM": "Salesforce", "1810.HK": "Xiaomi",
    "NVDA": "Nvidia", "AMD": "AMD", "TSM": "TSMC",
    "MSFT": "Microsoft", "GOOGL": "Alphabet", "META": "Meta",
    "OXY": "Occidental", "ET": "Energy Transfer", "WMB": "Williams", "ENB": "Enbridge",
    "ORCL": "Oracle", "SAP": "SAP", "SNOW": "Snowflake",
}


cal_col1, cal_col2 = st.columns([1, 3])
with cal_col1:
    load_cal = st.button("Load Calendar", key="load_cal", use_container_width=True)

if load_cal:
    st.session_state.earnings_calendar = None  # force refresh
    st.session_state.pre_earnings_briefs = {}

if st.session_state.earnings_calendar is None:
    with st.spinner("◆ fetching earnings calendar…"):
        try:
            raw = call_research(prompt_earnings_calendar(today_str()), api_key, max_tokens=2000)
            st.session_state.earnings_calendar = _parse_calendar(raw)
        except Exception as e:  # noqa: BLE001
            st.error(f"Calendar fetch failed: {e}")
            st.session_state.earnings_calendar = []

cal_rows = st.session_state.earnings_calendar or []
portfolio_rows = [r for r in cal_rows if r["ticker"].upper() in PORTFOLIO_TICKERS]
sector_rows = [r for r in cal_rows if r["ticker"].upper() not in PORTFOLIO_TICKERS]

# Portfolio table
if portfolio_rows:
    st.markdown(
        "<div class='cal-row head'>"
        "<span>TICKER</span><span class='nm'>NAME</span>"
        "<span>EARNINGS DATE</span><span>EPS EST</span><span class='du'>IN</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    for r in portfolio_rows:
        nm = TICKER_TO_NAME.get(r["ticker"].upper(), r["ticker"])
        date_disp = r["date"] if r["date"] and r["date"].upper() != "TBD" else "TBD — verify on IR page"
        days = _days_until(r["date"])
        st.markdown(
            f"<div class='cal-row'>"
            f"<span class='tk'>{r['ticker']}</span>"
            f"<span class='nm'>{nm}</span>"
            f"<span class='dt'>{date_disp}</span>"
            f"<span class='ep'>{r['eps']}</span>"
            f"<span class='du'>{days}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        bcol1, bcol2, _ = st.columns([2, 2, 3])
        with bcol1:
            if st.button(
                f"◆  Pre-Earnings Brief · {r['ticker']}",
                key=f"brief_{r['ticker']}",
                use_container_width=True,
            ):
                st.session_state.active_brief_ticker = r["ticker"]
                st.session_state.pre_earnings_briefs.pop(r["ticker"], None)

# Sector watch
if sector_rows:
    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='status-line'>Sector Watch</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class='sector-watch-row' style='border-bottom:1px solid #c9a84c; opacity:0.55;'>"
        "<span class='tk'>TICKER</span><span class='dt'>NAME</span>"
        "<span class='dt'>DATE</span><span class='cf'>EPS / CONF</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    for r in sector_rows:
        nm = TICKER_TO_NAME.get(r["ticker"].upper(), r["ticker"])
        date_disp = r["date"] if r["date"] and r["date"].upper() != "TBD" else "TBD"
        st.markdown(
            f"<div class='sector-watch-row'>"
            f"<span class='tk'>{r['ticker']}</span>"
            f"<span class='dt'>{nm}</span>"
            f"<span class='dt'>{date_disp}</span>"
            f"<span class='cf'>{r['eps']} · {r['confidence']}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

if not cal_rows:
    st.markdown(
        "<div style='font-family:\"JetBrains Mono\",monospace; font-size:0.75rem; "
        "color:#6a6555; letter-spacing:0.2rem; text-align:center; margin:1rem 0;'>"
        "NO CALENDAR DATA YET"
        "</div>",
        unsafe_allow_html=True,
    )

# Pre-earnings brief render
if st.session_state.active_brief_ticker:
    ticker = st.session_state.active_brief_ticker
    earnings_date = next(
        (r["date"] for r in cal_rows if r["ticker"].upper() == ticker.upper()),
        "TBD",
    )
    st.markdown("<hr class='gold-rule'>", unsafe_allow_html=True)
    render_section_header("PRE-EARNINGS BRIEF", f"{ticker} · {earnings_date}")

    if ticker not in st.session_state.pre_earnings_briefs:
        try:
            full_text = st.write_stream(
                stream_research(
                    prompt_pre_earnings(today_str(), ticker, earnings_date),
                    api_key,
                )
            )
            if not isinstance(full_text, str):
                full_text = "".join(full_text) if full_text else ""
            st.session_state.pre_earnings_briefs[ticker] = full_text
        except anthropic.APIStatusError as e:
            msg = getattr(e, "message", str(e))
            st.error(f"API error: {msg}")
            st.session_state.pre_earnings_briefs[ticker] = f"_API error: {msg}_"
        except Exception as e:  # noqa: BLE001
            st.error(f"Error: {e}")
            st.session_state.pre_earnings_briefs[ticker] = f"_Error: {e}_"
    else:
        st.markdown(st.session_state.pre_earnings_briefs[ticker])

    brief_text = st.session_state.pre_earnings_briefs.get(ticker, "")
    if brief_text:
        try:
            brief_pdf = pdf_export.memo_to_pdf(
                f"PRE-EARNINGS BRIEF — {ticker}",
                f"{earnings_date} · {today_str()}",
                brief_text,
            )
            st.download_button(
                "⬇  Download Pre-Earnings Brief (PDF)",
                data=brief_pdf,
                file_name=pdf_export.filename("PreEarnings", ticker),
                mime="application/pdf",
                use_container_width=True,
                key=f"dl_brief_{ticker}",
            )
        except Exception as e:  # noqa: BLE001
            st.error(f"Brief PDF failed: {e}")

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
