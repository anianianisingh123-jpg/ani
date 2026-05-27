"""
SIGNAL — Ani Singh Private Research Agent
Full daily cycle, deep dive, 3D global markets globe with live valuation
color-coding & divergence alerts, auto-loading Portfolio Pulse, and an
Earnings Calendar with pre-earnings intelligence briefs.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
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

VALUATION_HISTORY_PATH = Path(__file__).parent / "valuation_history.json"


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


def today_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def today_slug_compact() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")


def now_str() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M ET · %a %b %d")


def now_full_str() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%B %d, %Y · %H:%M ET")


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
# VALUATION  (yfinance · ETF proxies)
# ─────────────────────────────────────────────────────────────────────────────

COUNTRY_ETF = {
    "United States":  "SPY",
    "United Kingdom": "EWU",
    "Japan":          "EWJ",
    "Germany":        "EWG",
    "France":         "EWQ",
    "China":          "MCHI",
    "Hong Kong":      "EWH",
    "India":          "INDA",
    "Brazil":         "EWZ",
    "Canada":         "EWC",
    "Australia":      "EWA",
    "South Korea":    "EWY",
    "Singapore":      "EWS",
    "Switzerland":    "EWL",
    "Saudi Arabia":   "KSA",
    "Taiwan":         "EWT",
    "Mexico":         "EWW",
    "South Africa":   "EZA",
}

BAND_CHEAP     = "CHEAP"
BAND_FAIR      = "FAIR"
BAND_ELEVATED  = "ELEVATED"
BAND_EXPENSIVE = "EXPENSIVE"
BAND_VERY_EXP  = "VERY EXPENSIVE"
BAND_NONE      = "NO DATA"

BAND_COLOR = {
    BAND_CHEAP:     "#4ade80",
    BAND_FAIR:      "#a3e635",
    BAND_ELEVATED:  "#f59e0b",
    BAND_EXPENSIVE: "#f97316",
    BAND_VERY_EXP:  "#ef4444",
    BAND_NONE:      GOLD,
}

BAND_RANK = {
    BAND_CHEAP: 0, BAND_FAIR: 1, BAND_ELEVATED: 2,
    BAND_EXPENSIVE: 3, BAND_VERY_EXP: 4, BAND_NONE: -1,
}


def band_for_pe(pe: float | None) -> str:
    if pe is None or pe <= 0:
        return BAND_NONE
    if pe < 12:   return BAND_CHEAP
    if pe < 16:   return BAND_FAIR
    if pe < 20:   return BAND_ELEVATED
    if pe < 24:   return BAND_EXPENSIVE
    return BAND_VERY_EXP


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_valuations() -> dict:
    """Pull trailing P/E (fallback forward P/E) for each market ETF. 24h cache."""
    try:
        import yfinance as yf  # local import keeps app starting if pkg unavailable
    except Exception:
        return {name: {"pe": None, "band": BAND_NONE, "color": GOLD, "etf": etf}
                for name, etf in COUNTRY_ETF.items()}

    out: dict[str, dict] = {}
    for name, etf in COUNTRY_ETF.items():
        pe = None
        try:
            info = yf.Ticker(etf).info or {}
            pe = info.get("trailingPE") or info.get("forwardPE")
            if pe is not None:
                try:
                    pe = float(pe)
                    if pe <= 0 or pe > 200:
                        pe = None
                except Exception:
                    pe = None
        except Exception:
            pe = None
        band = band_for_pe(pe)
        out[name] = {
            "pe": pe,
            "band": band,
            "color": BAND_COLOR[band],
            "etf": etf,
        }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# VALUATION HISTORY  &  DIVERGENCE ALERTS
# ─────────────────────────────────────────────────────────────────────────────

def _load_history() -> dict:
    if not VALUATION_HISTORY_PATH.exists():
        return {}
    try:
        with VALUATION_HISTORY_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_history(data: dict) -> None:
    try:
        with VALUATION_HISTORY_PATH.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        pass


def update_history_and_detect_shifts(valuations: dict) -> list[dict]:
    """Append today's readings (max 12 per market, no same-day duplicates) and
    return a list of band shifts vs the most recent prior entry per market."""
    history = _load_history()
    today_key = today_iso()
    shifts: list[dict] = []

    for country, info in valuations.items():
        pe = info.get("pe")
        band = info.get("band", BAND_NONE)
        if pe is None or band == BAND_NONE:
            continue

        bucket = history.get(country, [])
        prior = bucket[-1] if bucket else None

        if prior and prior.get("band") not in (None, BAND_NONE) and prior.get("band") != band:
            shifts.append({
                "country": country,
                "from_band": prior["band"],
                "to_band": band,
                "from_pe": prior.get("pe"),
                "to_pe": pe,
                "direction": (
                    "more_expensive"
                    if BAND_RANK.get(band, -1) > BAND_RANK.get(prior["band"], -1)
                    else "cheaper"
                ),
            })

        entry = {"date": today_key, "pe": round(float(pe), 2), "band": band}
        if prior and prior.get("date") == today_key:
            bucket[-1] = entry
        else:
            bucket.append(entry)
        history[country] = bucket[-12:]

    _save_history(history)
    return shifts


# Country → list of position tickers it should alert into
COUNTRY_TO_POSITIONS = {
    "United States": ["QCOM", "CRM"],
    "China":         ["XIAOMI"],
    "Hong Kong":     ["XIAOMI"],
    "India":         ["XIAOMI"],
    "Taiwan":        ["QCOM"],
    "South Korea":   ["QCOM"],
    "Saudi Arabia":  ["KMI"],
    "Canada":        ["KMI"],
    "Mexico":        ["KMI"],
}


def shifts_for_position(shifts: list[dict], ticker: str) -> list[dict]:
    out = []
    for s in shifts:
        if ticker in COUNTRY_TO_POSITIONS.get(s["country"], []):
            out.append(s)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# PORTFOLIO PULSE  (Section IV)
# ─────────────────────────────────────────────────────────────────────────────

POSITIONS = [
    {
        "ticker": "QCOM",
        "name": "Qualcomm",
        "yf": "QCOM",
        "weight": "40% WEIGHT",
        "thesis": (
            "Edge AI inference dominance in power-constrained environments, "
            "automotive revenue ramp targeting $4B by 2026, QTL licensing moat, "
            "structural multi-year advantage over Nvidia and AMD at the edge due "
            "to mobile power-constraint engineering heritage. TSMC N2 capacity "
            "ramp is a direct tailwind for QCOM product roadmap."
        ),
    },
    {
        "ticker": "KMI",
        "name": "Kinder Morgan",
        "yf": "KMI",
        "weight": "17% WEIGHT",
        "thesis": (
            "Cash-flow-generative midstream energy infrastructure, natural gas "
            "demand growth driven by AI data center power buildout, 4–6% "
            "dividend yield, inflation-resilient real asset, long-duration "
            "pipeline contracts insulated from commodity price swings."
        ),
    },
    {
        "ticker": "CRM",
        "name": "Salesforce",
        "yf": "CRM",
        "weight": "CORE HOLDING",
        "thesis": (
            "Agentic AI platform consolidation, enterprise software stickiness, "
            "Agentforce as the dominant AI workflow layer for enterprise, "
            "remaining performance obligation as forward revenue visibility signal."
        ),
    },
    {
        "ticker": "XIAOMI",
        "name": "Xiaomi",
        "yf": "1810.HK",
        "weight": "CORE HOLDING",
        "thesis": (
            "China consumer recovery, EV optionality with growing delivery "
            "numbers, global hardware ecosystem expansion, India smartphone "
            "market share. Watch India revenue concentration — if above 30% of "
            "total, India credit cycle becomes position-sizing concern."
        ),
    },
]


def prompt_portfolio_pulse(today: str, pos: dict) -> str:
    return f"""Today is {today}. Use web search.

Position check for {pos['ticker']} ({pos['name']}), {pos['weight'].lower()} of portfolio.

Core thesis: {pos['thesis']}

In 4–5 sentences cover:
1. Any material news, earnings, analyst actions, or price target changes in the last 48 hours
2. Any development that directly strengthens or challenges the core thesis
3. Status verdict: THESIS INTACT, WATCH, or ALERT and one sentence explaining why

Be direct. No filler. If nothing material happened say so plainly."""


def classify_status(text: str) -> tuple[str, str]:
    """Return (label, color) by scanning the model output for the verdict."""
    upper = text.upper()
    # Look at the last 600 chars for the verdict line
    tail = upper[-800:]
    if "ALERT" in tail and "INTACT" not in tail.split("ALERT")[-1][:120]:
        return "ALERT", "#ef4444"
    if "WATCH" in tail:
        return "WATCH", "#f59e0b"
    if "INTACT" in tail or "STRENGTHEN" in tail:
        return "THESIS INTACT", "#4ade80"
    if "ALERT" in tail:
        return "ALERT", "#ef4444"
    return "THESIS INTACT", "#4ade80"


# ─────────────────────────────────────────────────────────────────────────────
# EARNINGS CALENDAR  (Section V)
# ─────────────────────────────────────────────────────────────────────────────

SECTOR_WATCH = [
    ("NVDA",  "NVIDIA",            "AI / SEMI"),
    ("AMD",   "AMD",               "AI / SEMI"),
    ("TSM",   "TSMC",              "AI / SEMI"),
    ("MSFT",  "Microsoft",         "AI / SEMI"),
    ("GOOGL", "Alphabet",          "AI / SEMI"),
    ("META",  "Meta Platforms",    "AI / SEMI"),
    ("OXY",   "Occidental",        "ENERGY"),
    ("ET",    "Energy Transfer",   "ENERGY"),
    ("WMB",   "Williams Cos.",     "ENERGY"),
    ("ENB",   "Enbridge",          "ENERGY"),
    ("ORCL",  "Oracle",            "ENTERPRISE SW"),
    ("SAP",   "SAP",               "ENTERPRISE SW"),
    ("SNOW",  "Snowflake",         "ENTERPRISE SW"),
]


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_earnings_one(symbol: str) -> dict:
    """Return {date_iso, date_human, days_until, eps_avg} or fallbacks."""
    out = {"date_iso": None, "date_human": "TBD — verify on IR page",
           "days_until": None, "eps_avg": None}
    try:
        import yfinance as yf
        from datetime import date
        t = yf.Ticker(symbol)
        cal = t.calendar
        ed = None
        eps_avg = None
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date") or []
            if dates:
                ed = dates[0]
            eps_avg = cal.get("Earnings Average")
        if ed is None:
            try:
                info = t.info or {}
                ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
                if ts:
                    ed = datetime.fromtimestamp(int(ts)).date()
            except Exception:
                pass
        if ed is not None:
            if hasattr(ed, "date"):
                ed = ed.date() if callable(getattr(ed, "date", None)) else ed
            try:
                d_iso = ed.isoformat() if hasattr(ed, "isoformat") else str(ed)
            except Exception:
                d_iso = str(ed)
            out["date_iso"] = d_iso
            try:
                d_obj = ed if isinstance(ed, date) else datetime.fromisoformat(d_iso).date()
                out["date_human"] = d_obj.strftime("%b %d, %Y")
                out["days_until"] = (d_obj - datetime.now(ZoneInfo("America/New_York")).date()).days
            except Exception:
                pass
        if eps_avg is not None:
            try:
                out["eps_avg"] = float(eps_avg)
            except Exception:
                pass
    except Exception:
        pass
    return out


def prompt_pre_earnings(today: str, pos: dict, earnings_date: str) -> str:
    ticker_watchlist = {
        "QCOM": (
            "For QCOM specifically watch:\n"
            "- Automotive segment revenue (thesis: $4B by 2026)\n"
            "- IoT segment revenue trend\n"
            "- Handset unit guidance and ASP\n"
            "- Any edge AI or on-device AI design win commentary\n"
            "- QTL licensing revenue and royalty rate"
        ),
        "KMI": (
            "For KMI specifically watch:\n"
            "- Natural gas throughput volumes\n"
            "- Natural gas demand commentary — any AI data center customer mentions\n"
            "- LNG export capacity utilization\n"
            "- Dividend guidance or coverage ratio"
        ),
        "CRM": (
            "For CRM specifically watch:\n"
            "- Agentforce seat adoption and revenue attach rate\n"
            "- Remaining Performance Obligation growth (forward revenue signal)\n"
            "- AI-driven deal sizes vs traditional deals\n"
            "- Net revenue retention rate"
        ),
        "XIAOMI": (
            "For Xiaomi specifically watch:\n"
            "- EV delivery numbers and margin per unit\n"
            "- India revenue as % of total (alert if above 30%)\n"
            "- Gross margin trajectory across segments\n"
            "- Any commentary on China consumer demand trends"
        ),
    }
    watch_block = ticker_watchlist.get(pos["ticker"], "")
    return f"""Today is {today}. Use web search.

Pre-earnings intelligence brief for {pos['ticker']} reporting approximately {earnings_date}.

1. CONSENSUS EXPECTATIONS
What is the street expecting for EPS, revenue, and key segment metrics? What is the whisper number vs official consensus?

2. WHAT TO WATCH
The 2–3 specific data points or guidance language that will move the stock.

{watch_block}

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


def collect_research(prompt: str, api_key: str) -> str:
    """Non-streaming helper — returns the full assembled text."""
    return "".join(stream_research(prompt, api_key))


# ─────────────────────────────────────────────────────────────────────────────
# PDF GENERATION  (fpdf2)
# ─────────────────────────────────────────────────────────────────────────────

_LATIN1_FIXES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-",
    "…": "...",
    " ": " ", "​": "", "‌": "", "‍": "", "﻿": "",
    "•": "*", "◆": "*", "◈": "*", "●": "*",
    "⚠": "!", "→": "->", "⇒": "=>", "·": "-",
    " ": " ", " ": " ",
}


def _safe_latin1(text: str) -> str:
    for k, v in _LATIN1_FIXES.items():
        text = text.replace(k, v)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _strip_inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text


def build_pdf(title: str, subtitle: str, body_markdown: str) -> bytes:
    from fpdf import FPDF

    class SignalPDF(FPDF):
        def header(self):
            self.set_font("Helvetica", "B", 11)
            self.set_text_color(201, 168, 76)
            self.cell(0, 7, _safe_latin1("SIGNAL · ANI SINGH · PRIVATE RESEARCH AGENT"),
                      align="C", new_x="LMARGIN", new_y="NEXT")
            self.set_font("Helvetica", "", 9)
            self.set_text_color(120, 110, 80)
            self.cell(0, 5, _safe_latin1(f"{title}  ·  {subtitle}"),
                      align="C", new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(201, 168, 76)
            y = self.get_y() + 1
            self.line(self.l_margin, y, self.w - self.r_margin, y)
            self.ln(4)

        def footer(self):
            self.set_y(-13)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120, 110, 80)
            self.cell(0, 8,
                      _safe_latin1("Generated by SIGNAL Research Agent · aniagent.streamlit.app"),
                      align="C")

    pdf = SignalPDF()
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(16, 22, 16)
    pdf.add_page()

    def _mc(h: float, txt: str):
        pdf.multi_cell(0, h, _safe_latin1(txt),
                       new_x="LMARGIN", new_y="NEXT")

    for raw in body_markdown.split("\n"):
        line = _strip_inline(raw).rstrip()
        if not line.strip():
            pdf.ln(2.5)
            continue
        if line.startswith("### "):
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(201, 168, 76)
            _mc(6, line[4:])
            pdf.ln(0.5)
        elif line.startswith("## "):
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(201, 168, 76)
            _mc(7, line[3:])
            pdf.ln(0.8)
        elif line.startswith("# "):
            pdf.set_font("Helvetica", "B", 15)
            pdf.set_text_color(201, 168, 76)
            _mc(8, line[2:])
            pdf.ln(1)
        elif re.match(r"^[\-\*\+] ", line):
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(35, 35, 35)
            _mc(5.3, "  -  " + line[2:].strip())
        else:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(35, 35, 35)
            _mc(5.3, line)

    raw_out = pdf.output(dest="S")
    if isinstance(raw_out, (bytes, bytearray)):
        return bytes(raw_out)
    return raw_out.encode("latin-1", errors="replace")


def safe_filename_chunk(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "", s)
    return s[:40] or "Memo"


def pdf_download_button(label: str, title: str, subtitle: str,
                        body: str, file_stub: str, key: str):
    try:
        data = build_pdf(title, subtitle, body)
    except Exception as e:  # noqa: BLE001
        st.warning(f"PDF generation failed: {e}")
        return
    st.download_button(
        label,
        data=data,
        file_name=f"{file_stub}_{today_slug_compact()}.pdf",
        mime="application/pdf",
        use_container_width=True,
        key=key,
    )


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
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap');

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

.stDownloadButton > button {
    font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace !important;
    font-size: 0.72rem !important;
    letter-spacing: 0.18rem !important;
    padding: 0.55rem 1rem !important;
    background-color: #0c0c0c !important;
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

/* ── valuation legend ── */
.val-legend {
    display: flex; flex-wrap: wrap; justify-content: center; gap: 14px;
    font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
    font-size: 10px;
    letter-spacing: 0.1em;
    color: #a8a395;
    margin: 0.6rem auto 0.2rem;
    text-transform: uppercase;
}
.val-legend .dot {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    margin-right: 6px; vertical-align: middle;
}

/* ── divergence alert banners ── */
.shift-banner {
    font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
    font-size: 11px;
    letter-spacing: 0.08em;
    padding: 9px 14px;
    margin: 4px 0;
    border-radius: 2px;
    border: 1px solid;
    line-height: 1.5;
}
.shift-up   { background: #ef444420; border-color: #ef4444; color: #ef4444; }
.shift-down { background: #4ade8020; border-color: #4ade80; color: #4ade80; }

/* ── portfolio pulse cards ── */
.pulse-card {
    border: 1px solid #2a261b;
    border-radius: 2px;
    padding: 1.1rem 1.2rem;
    background: #11100c;
    margin-bottom: 0.6rem;
    min-height: 100%;
}
.pulse-head {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 0.4rem;
}
.pulse-ticker {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.35rem;
    color: #c9a84c;
    font-weight: 600;
    letter-spacing: 0.08em;
}
.pulse-name {
    font-family: 'Inter', sans-serif;
    font-size: 0.7rem;
    color: #8a8470;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    margin-top: 2px;
}
.pulse-weight {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.66rem;
    color: #c9a84c;
    border: 1px solid #c9a84c;
    padding: 2px 8px;
    letter-spacing: 0.15em;
    border-radius: 1px;
}
.pulse-status {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.66rem;
    padding: 3px 10px;
    border-radius: 1px;
    letter-spacing: 0.18em;
    font-weight: 600;
    display: inline-block;
    margin-top: 0.4rem;
    margin-bottom: 0.5rem;
}
.pulse-body p { font-size: 0.98rem !important; line-height: 1.5; }
.pulse-val-alert {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: #c9a84c;
    margin-top: 0.5rem;
    letter-spacing: 0.06em;
    line-height: 1.55;
    border-top: 1px dashed #2a261b;
    padding-top: 0.5rem;
}
.pulse-skeleton {
    border: 1px dashed #2a261b;
    border-radius: 2px;
    padding: 1.1rem 1.2rem;
    background: #0f0e0a;
    margin-bottom: 0.6rem;
}
.pulse-skeleton .bar {
    background: linear-gradient(90deg, #1a1812, #25221a, #1a1812);
    height: 8px; border-radius: 1px; margin: 8px 0;
    background-size: 200% 100%;
    animation: shimmer 1.6s linear infinite;
}
.pulse-skeleton .bar.short { width: 40%; }
.pulse-skeleton .bar.mid   { width: 70%; }
.pulse-skeleton .bar.long  { width: 92%; }
@keyframes shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}

/* ── earnings calendar ── */
.earn-card {
    border: 1px solid #2a261b;
    border-radius: 2px;
    padding: 0.85rem 1rem;
    background: #11100c;
    margin-bottom: 0.5rem;
    display: flex; flex-direction: column; gap: 0.25rem;
}
.earn-row {
    display: flex; justify-content: space-between; align-items: baseline;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
    color: #d8d2bf;
    letter-spacing: 0.05em;
}
.earn-ticker { color: #c9a84c; font-weight: 600; font-size: 0.95rem; letter-spacing: 0.1em; }
.earn-name   { color: #8a8470; font-family: 'Inter', sans-serif; font-size: 0.7rem;
               letter-spacing: 0.15em; text-transform: uppercase; }
.earn-date   { color: #e8e3d6; }
.earn-meta   { color: #8a8470; font-size: 0.68rem; letter-spacing: 0.1em;
               text-transform: uppercase; }
.earn-days   { color: #c9a84c; font-size: 0.72rem; letter-spacing: 0.1em; }
.sector-tag  { color: #6a6555; font-size: 0.62rem;
               font-family: 'JetBrains Mono', monospace;
               letter-spacing: 0.18em; text-transform: uppercase; }

@media (max-width: 640px) {
    .signal-title { font-size: 3.4rem !important; letter-spacing: 0.4rem !important; }
    .signal-subtitle { font-size: 0.6rem !important; letter-spacing: 0.25rem !important; }
    .section-name { font-size: 1.4rem !important; }
    body, p, li, .stMarkdown p { font-size: 1rem !important; }
    .block-container { padding-top: 1rem !important; }
    .pulse-ticker { font-size: 1.1rem; }
    .val-legend { font-size: 9px; gap: 8px; }
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

# session-state init
for key, default in [
    ("memo_sections", []),
    ("memo_kind", None),
    ("memo_topic", ""),
    ("last_globe_click_id", None),
    ("pulse_cards", {}),       # ticker -> {text, status_label, status_color, ...}
    ("pulse_done_date", None), # iso date string
    ("pulse_running", False),
    ("pre_earnings_briefs", {}),  # ticker -> body text
    ("valuation_shifts", []),
]:
    if key not in st.session_state:
        st.session_state[key] = default

api_key = get_api_key()
if not api_key:
    st.error(
        "ANTHROPIC_API_KEY not set. Add it to .env locally, or to "
        "Streamlit Cloud secrets (Settings → Secrets) as "
        "`ANTHROPIC_API_KEY=\"sk-ant-…\"`."
    )
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# CONTROLS  (Sections I & II)
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

# ─────────────────────────────────────────────────────────────────────────────
# SECTION III · GLOBAL MARKETS  (existing globe + valuation + alerts + legend)
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("<div class='status-line'>III · Global Markets</div>", unsafe_allow_html=True)
st.markdown(
    "<div style='font-family:\"Inter\",sans-serif; font-size:0.7rem; color:#6a6555; "
    "letter-spacing:0.15rem; margin-top:0.4rem; margin-bottom:0.8rem;'>"
    "Tap a node to generate a country-level intelligence memo. Nodes are colour-coded "
    "by current ETF trailing P/E."
    "</div>",
    unsafe_allow_html=True,
)

# Pull live valuations (24h cache)
valuations = fetch_valuations()

# Detect band shifts & persist history. We only run shift detection ONCE per
# session per day to keep the JSON file from being rewritten on every rerun.
if (st.session_state.get("history_processed_date") != today_iso()):
    shifts = update_history_and_detect_shifts(valuations)
    st.session_state.valuation_shifts = shifts
    st.session_state.history_processed_date = today_iso()
else:
    shifts = st.session_state.valuation_shifts

# Divergence alert banners above the globe
if shifts:
    for s in shifts:
        cls = "shift-up" if s["direction"] == "more_expensive" else "shift-down"
        fp = f"{s['from_pe']:.1f}x" if s.get("from_pe") is not None else "—"
        tp = f"{s['to_pe']:.1f}x" if s.get("to_pe") is not None else "—"
        st.markdown(
            f"<div class='shift-banner {cls}'>"
            f"⚠  VALUATION SHIFT — {s['country']} moved from "
            f"{s['from_band']} → {s['to_band']}  ({fp} → {tp})"
            f"</div>",
            unsafe_allow_html=True,
        )

# Build colored marker list for the globe
markets_colored = []
for m in MARKETS:
    v = valuations.get(m["name"], {})
    markets_colored.append({
        "name":  m["name"],
        "lat":   m["lat"],
        "lng":   m["lng"],
        "pe":    v.get("pe"),
        "band":  v.get("band", BAND_NONE),
        "color": v.get("color", GOLD),
        "etf":   v.get("etf", ""),
    })

globe_event = globe_markets_component(
    markets=markets_colored,
    height=560,
    key="signal_globe",
    default=None,
)

# Legend
legend_items = [
    (BAND_CHEAP,     "<12x"),
    (BAND_FAIR,      "12-16x"),
    (BAND_ELEVATED,  "16-20x"),
    (BAND_EXPENSIVE, "20-24x"),
    (BAND_VERY_EXP,  ">24x"),
]
legend_html = "<div class='val-legend'>" + "".join(
    f"<span><span class='dot' style='background:{BAND_COLOR[b]}'></span>"
    f"{b} {rng}</span>" for b, rng in legend_items
) + "</div>"
st.markdown(legend_html, unsafe_allow_html=True)

st.markdown("<hr class='gold-rule'>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION HELPERS
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

# ─── Inline download buttons for I/II/III memos ──────────────────────────────
if st.session_state.memo_sections:
    full_memo = assemble_full_memo()
    kind = st.session_state.memo_kind
    if kind == "deep":
        sub = f"DEEP DIVE — {st.session_state.memo_topic} · {now_full_str()}"
        stub = f"SIGNAL_DeepDive_{safe_filename_chunk(st.session_state.memo_topic)}"
        label = "⬇  DOWNLOAD DEEP DIVE"
    elif kind == "market":
        sub = f"GLOBAL MARKETS — {st.session_state.memo_topic} · {now_full_str()}"
        stub = f"SIGNAL_Globe_{safe_filename_chunk(st.session_state.memo_topic)}"
        label = "⬇  DOWNLOAD COUNTRY MEMO"
    else:
        sub = f"FULL RESEARCH CYCLE · {now_full_str()}"
        stub = "SIGNAL_FullCycle"
        label = "⬇  DOWNLOAD FULL MEMO"
    pdf_download_button(
        label,
        title="SIGNAL",
        subtitle=sub,
        body=full_memo,
        file_stub=stub,
        key=f"pdf_main_{kind}",
    )

st.markdown("<hr class='gold-rule'>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION IV · PORTFOLIO PULSE  (auto-fires; sequential w/ 15s delays)
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("<div class='status-line'>IV · Portfolio Pulse</div>", unsafe_allow_html=True)
st.markdown(
    "<div style='font-family:\"Inter\",sans-serif; font-size:0.7rem; color:#6a6555; "
    "letter-spacing:0.15rem; margin-top:0.4rem; margin-bottom:0.9rem;'>"
    "Live thesis check on each position. Auto-refreshes once daily."
    "</div>",
    unsafe_allow_html=True,
)


def render_pulse_skeleton(pos: dict) -> str:
    return f"""
<div class='pulse-skeleton'>
  <div class='pulse-head'>
    <div>
      <div class='pulse-ticker'>{pos['ticker']}</div>
      <div class='pulse-name'>{pos['name']}</div>
    </div>
    <div class='pulse-weight'>{pos['weight']}</div>
  </div>
  <div class='bar long'></div>
  <div class='bar mid'></div>
  <div class='bar long'></div>
  <div class='bar short'></div>
</div>"""


def render_pulse_card(pos: dict, text: str, status_label: str, status_color: str,
                      val_alerts: list[dict]) -> str:
    # Escape HTML in the model output. Render basic markdown (bold, paragraph breaks).
    body = text.strip()
    body_html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", body)
    body_html = body_html.replace("\n\n", "</p><p>").replace("\n", "<br>")
    body_html = f"<p>{body_html}</p>"

    alerts_html = ""
    if val_alerts:
        rows = []
        for s in val_alerts:
            fp = f"{s['from_pe']:.1f}x" if s.get("from_pe") is not None else "—"
            tp = f"{s['to_pe']:.1f}x" if s.get("to_pe") is not None else "—"
            rows.append(
                f"◈ VALUATION SIGNAL  {s['country']}: "
                f"{s['from_band']} → {s['to_band']} ({fp} → {tp})"
            )
        alerts_html = "<div class='pulse-val-alert'>" + "<br>".join(rows) + "</div>"

    return f"""
<div class='pulse-card'>
  <div class='pulse-head'>
    <div>
      <div class='pulse-ticker'>{pos['ticker']}</div>
      <div class='pulse-name'>{pos['name']}</div>
    </div>
    <div class='pulse-weight'>{pos['weight']}</div>
  </div>
  <div class='pulse-status' style='border:1px solid {status_color}; color:{status_color};'>{status_label}</div>
  <div class='pulse-body'>{body_html}</div>
  {alerts_html}
</div>"""


def run_portfolio_pulse():
    """Sequentially fetch all 4 cards with 15s delays."""
    st.session_state.pulse_running = True
    st.session_state.pulse_cards = {}

    today = today_str()
    col_left, col_right = st.columns(2)
    placeholders = {
        POSITIONS[0]["ticker"]: col_left.empty(),
        POSITIONS[1]["ticker"]: col_right.empty(),
        POSITIONS[2]["ticker"]: col_left.empty(),
        POSITIONS[3]["ticker"]: col_right.empty(),
    }
    # Show skeletons up front
    for pos in POSITIONS:
        placeholders[pos["ticker"]].markdown(
            render_pulse_skeleton(pos), unsafe_allow_html=True
        )

    try:
        for i, pos in enumerate(POSITIONS):
            if i > 0:
                time.sleep(15)  # rate-limit padding
            try:
                text = collect_research(prompt_portfolio_pulse(today, pos), api_key)
            except anthropic.APIStatusError as e:
                text = f"_API error: {getattr(e, 'message', str(e))}_"
            except Exception as e:  # noqa: BLE001
                text = f"_Error: {e}_"

            status_label, status_color = classify_status(text)
            val_alerts = shifts_for_position(
                st.session_state.valuation_shifts, pos["ticker"]
            )
            st.session_state.pulse_cards[pos["ticker"]] = {
                "text": text,
                "status_label": status_label,
                "status_color": status_color,
                "val_alerts": val_alerts,
            }
            placeholders[pos["ticker"]].markdown(
                render_pulse_card(pos, text, status_label, status_color, val_alerts),
                unsafe_allow_html=True,
            )

        st.session_state.pulse_done_date = today_iso()
    finally:
        st.session_state.pulse_running = False


def render_cached_pulse():
    col_left, col_right = st.columns(2)
    cols = [col_left, col_right, col_left, col_right]
    for i, pos in enumerate(POSITIONS):
        info = st.session_state.pulse_cards.get(pos["ticker"])
        if not info:
            cols[i].markdown(render_pulse_skeleton(pos), unsafe_allow_html=True)
            continue
        cols[i].markdown(
            render_pulse_card(
                pos, info["text"], info["status_label"],
                info["status_color"], info.get("val_alerts", [])
            ),
            unsafe_allow_html=True,
        )


# Auto-fire if not yet run today
if (st.session_state.pulse_done_date != today_iso()
        and not st.session_state.pulse_running):
    run_portfolio_pulse()
else:
    render_cached_pulse()

# Manual refresh + PDF download once all 4 cards are present
pulse_complete = all(
    pos["ticker"] in st.session_state.pulse_cards for pos in POSITIONS
)
if pulse_complete:
    refresh_col, dl_col = st.columns(2)
    with refresh_col:
        if st.button("◆  Refresh Portfolio Pulse", key="refresh_pulse",
                     use_container_width=True):
            st.session_state.pulse_done_date = None
            st.rerun()
    with dl_col:
        body_parts = [f"# SIGNAL · PORTFOLIO PULSE\n*{today_str()}*\n\n---\n"]
        for pos in POSITIONS:
            info = st.session_state.pulse_cards.get(pos["ticker"], {})
            body_parts.append(
                f"## {pos['ticker']} — {pos['name']} ({pos['weight']})\n"
                f"**Status:** {info.get('status_label','—')}\n\n"
                f"{info.get('text','').strip()}\n"
            )
            for s in info.get("val_alerts", []):
                fp = f"{s['from_pe']:.1f}x" if s.get('from_pe') is not None else "—"
                tp = f"{s['to_pe']:.1f}x" if s.get('to_pe') is not None else "—"
                body_parts.append(
                    f"\n*Valuation signal — {s['country']}: "
                    f"{s['from_band']} → {s['to_band']} ({fp} → {tp})*\n"
                )
            body_parts.append("\n---\n")
        pdf_download_button(
            "⬇  DOWNLOAD PORTFOLIO PULSE",
            title="SIGNAL",
            subtitle=f"PORTFOLIO PULSE · {now_full_str()}",
            body="\n".join(body_parts),
            file_stub="SIGNAL_PortfolioPulse",
            key="pdf_pulse",
        )

st.markdown("<hr class='gold-rule'>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION V · EARNINGS CALENDAR
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("<div class='status-line'>V · Earnings Calendar</div>", unsafe_allow_html=True)
st.markdown(
    "<div style='font-family:\"Inter\",sans-serif; font-size:0.7rem; color:#6a6555; "
    "letter-spacing:0.15rem; margin-top:0.4rem; margin-bottom:0.9rem;'>"
    "Next earnings dates for each core position. Generate a pre-earnings brief "
    "before each print."
    "</div>",
    unsafe_allow_html=True,
)


def fmt_eps(eps) -> str:
    if eps is None:
        return "—"
    try:
        return f"${float(eps):.2f}"
    except Exception:
        return "—"


def fmt_days(days) -> str:
    if days is None:
        return "—"
    if days < 0:
        return f"{abs(days)}d ago"
    if days == 0:
        return "today"
    return f"in {days}d"


def render_earnings_card(ticker: str, name: str, e: dict, sector: str | None = None):
    sector_html = (
        f"<div class='sector-tag'>{sector}</div>" if sector else ""
    )
    return f"""
<div class='earn-card'>
  <div class='earn-row'>
    <div>
      <span class='earn-ticker'>{ticker}</span>
      &nbsp;<span class='earn-name'>{name}</span>
    </div>
    {sector_html}
  </div>
  <div class='earn-row'>
    <span class='earn-meta'>Next report</span>
    <span class='earn-date'>{e['date_human']}</span>
  </div>
  <div class='earn-row'>
    <span class='earn-meta'>Consensus EPS</span>
    <span class='earn-meta'>{fmt_eps(e.get('eps_avg'))}</span>
  </div>
  <div class='earn-row'>
    <span class='earn-meta'>Window</span>
    <span class='earn-days'>{fmt_days(e.get('days_until'))}</span>
  </div>
</div>
"""


# Core positions
for pos in POSITIONS:
    e = fetch_earnings_one(pos["yf"])
    st.markdown(render_earnings_card(pos["ticker"], pos["name"], e),
                unsafe_allow_html=True)
    if st.button(f"⬢  Generate Pre-Earnings Brief — {pos['ticker']}",
                 key=f"preE_{pos['ticker']}", use_container_width=True):
        render_section_header("PRE-EARNINGS BRIEF", pos["ticker"])
        try:
            brief_text = st.write_stream(
                stream_research(
                    prompt_pre_earnings(today_str(), pos, e["date_human"]),
                    api_key,
                )
            )
            if not isinstance(brief_text, str):
                brief_text = "".join(brief_text) if brief_text else ""
        except anthropic.APIStatusError as ex:
            brief_text = f"_API error: {getattr(ex, 'message', str(ex))}_"
            st.error(brief_text)
        except Exception as ex:  # noqa: BLE001
            brief_text = f"_Error: {ex}_"
            st.error(brief_text)
        st.session_state.pre_earnings_briefs[pos["ticker"]] = {
            "text": brief_text,
            "date": e["date_human"],
        }

    # If a brief exists for this ticker, surface its download button
    cached = st.session_state.pre_earnings_briefs.get(pos["ticker"])
    if cached:
        body = (
            f"# SIGNAL · PRE-EARNINGS BRIEF\n"
            f"## {pos['ticker']} — {pos['name']}\n"
            f"*Reporting {cached['date']} · brief generated {today_str()}*\n\n"
            "---\n\n"
            f"{cached['text']}"
        )
        pdf_download_button(
            f"⬇  DOWNLOAD PRE-EARNINGS BRIEF — {pos['ticker']}",
            title="SIGNAL",
            subtitle=f"PRE-EARNINGS BRIEF — {pos['ticker']} · {now_full_str()}",
            body=body,
            file_stub=f"SIGNAL_PreEarnings_{pos['ticker']}",
            key=f"pdf_preE_{pos['ticker']}",
        )

st.markdown(
    "<div style='height:1.4rem'></div>"
    "<div class='status-line'>Sector Watch — moves your positions</div>",
    unsafe_allow_html=True,
)
st.markdown(
    "<div style='font-family:\"Inter\",sans-serif; font-size:0.65rem; color:#6a6555; "
    "letter-spacing:0.12rem; margin-top:0.3rem; margin-bottom:0.6rem;'>"
    "Upcoming earnings from macro-relevant names that could move QCOM, KMI, or CRM."
    "</div>",
    unsafe_allow_html=True,
)

# Sector watch — filter & sort by days_until (closest first), within 60 days
sector_rows = []
for sym, name, sector in SECTOR_WATCH:
    e = fetch_earnings_one(sym)
    days = e.get("days_until")
    if days is None or days < -3 or days > 60:
        continue
    sector_rows.append((sym, name, sector, e))
sector_rows.sort(key=lambda r: (r[3].get("days_until") or 999))

if sector_rows:
    for sym, name, sector, e in sector_rows:
        st.markdown(render_earnings_card(sym, name, e, sector=sector),
                    unsafe_allow_html=True)
else:
    st.markdown(
        "<div style='font-family:\"JetBrains Mono\",monospace; font-size:0.72rem; "
        "color:#6a6555; padding:0.6rem 0;'>"
        "No sector earnings in window."
        "</div>",
        unsafe_allow_html=True,
    )

st.markdown("<hr class='gold-rule'>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# COPY / DOWNLOAD  (legacy markdown export — preserved)
# ─────────────────────────────────────────────────────────────────────────────

if st.session_state.memo_sections:
    st.markdown("<div class='status-line'>Export · Markdown</div>",
                unsafe_allow_html=True)

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
            key="md_legacy",
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
