"""
signal_ai.py — prompt builders and parsers for the live AI sections.

All calls go through signal_core (claude-sonnet-4-5 + web search). Loaders
return plain Python structures; caching/refresh is handled at the call site in
app.py via session_state so the page opens fast and AI fires only on demand.
"""

from __future__ import annotations

from signal_core import call_json, call_research
from debt_cycle import MP_FRAMEWORK

# ── Geopolitical risk scale (Globe layer 2 + Hotspots) ───────────────────────
GEO_RISK_COLORS = {
    "STABLE":     "#2d4a2d",
    "SIMMERING":  "#7a6b1a",
    "ESCALATING": "#c47a1a",
    "HOT":        "#c43a1a",
    "CRISIS":     "#8b0000",
    "UNKNOWN":    "#3a3a3a",
}
GEO_RISK_ORDER = ["STABLE", "SIMMERING", "ESCALATING", "HOT", "CRISIS"]


def geo_color(level: str) -> str:
    return GEO_RISK_COLORS.get((level or "UNKNOWN").upper(), GEO_RISK_COLORS["UNKNOWN"])


# ── 1. Geopolitics map ───────────────────────────────────────────────────────
def load_geopolitics(api_key: str, countries: list[str]) -> dict:
    names = ", ".join(countries)
    prompt = f"""Use web search for the very latest developments. Assess the current geopolitical risk level for each of these countries: {names}.

Risk levels (use EXACTLY one of these strings):
- STABLE — no active tensions
- SIMMERING — diplomatic tensions, sanctions, contested elections
- ESCALATING — military movements, proxy conflicts, economic warfare
- HOT — active conflict, strikes, direct military engagement
- CRISIS — full warfare, regime collapse, humanitarian emergency

Return ONLY a JSON object keyed by the exact country name, each value an object:
{{"level": "<LEVEL>", "brief": "<2-sentence current situation>", "assets": ["<asset class 1>", "<asset class 2>"]}}

"assets" = the two asset classes most affected (e.g. "oil", "local equities", "FX/currency", "sovereign bonds", "gold"). Be current and specific — cite what is happening right now."""
    data = call_json(prompt, api_key, max_tokens=4000)
    return data if isinstance(data, dict) else {}


# ── 2. Valuation signals + world commentary ──────────────────────────────────
def load_valuation_signals(api_key: str, table: list[dict]) -> dict:
    lines = []
    for r in table:
        pe = f"{r['pe']:.1f}" if r.get("pe") is not None else "n/a"
        va = f"{r['vs_avg_pe']:+.0f}%" if r.get("vs_avg_pe") is not None else "n/a"
        lines.append(f"- {r['country']} {r['index']}: P/E {pe}, vs 10yr-avg {va}, label {r['valuation']}")
    snapshot = "\n".join(lines)
    prompt = f"""Use web search to confirm current conditions. Below is today's live valuation snapshot of major equity markets (P/E vs each market's own 10yr-average):

{snapshot}

Apply Ani's framework (Dalio long-term debt cycle + Howard Marks risk/reward).

Return ONLY a JSON object:
{{
  "signals": {{ "<country>": "<ONE WORD: AVOID|WATCH|ACCUMULATE|BUY>", ... }},
  "commentary": "<one tight paragraph: where in the world is capital cheap right now, and where is it dangerously stretched? Specific markets, Dalio framing.>"
}}

Provide a signal for EVERY country listed. AVOID = expensive + deteriorating; WATCH = neutral; ACCUMULATE = attractive; BUY = cheap with catalyst."""
    data = call_json(prompt, api_key, max_tokens=3000)
    if not isinstance(data, dict):
        return {"signals": {}, "commentary": ""}
    data.setdefault("signals", {})
    data.setdefault("commentary", "")
    return data


# ── 3. Sovereign CDS / credit stress ─────────────────────────────────────────
def load_cds(api_key: str) -> dict:
    prompt = """Use web search to find the most recent available 5-year sovereign CDS spreads (credit default swap, in basis points) for the world's most-watched sovereigns — include the most stressed: Argentina, Turkey, Egypt, Pakistan, Ukraine, Nigeria, South Africa, Brazil, Colombia, Mexico, Romania, Italy, Greece, China, plus benchmarks US, Germany, Japan, UK, France, and any others currently elevated.

CDS data is not free real-time; use the most recent figures you can find from public sources and news and mark confidence accordingly.

Return ONLY a JSON object:
{
  "asof": "<date or 'recent news data, approximate'>",
  "rows": [
    {"country": "<name>", "cds": <number bps>, "w_chg": <1-week change bps or null>, "m_chg": <1-month change bps or null>, "trend": "<widening|tightening|stable>", "note": "<short driver, only for the most stressed; else empty>"}
  ]
}

Sort rows by cds descending (most stressed first). Give the top 3 a one-line "note" connecting the spread to Dalio's debt-cycle framework. Numbers should be your best current estimate — do not invent precision you don't have."""
    data = call_json(prompt, api_key, max_tokens=4000)
    if not isinstance(data, dict):
        return {"asof": "", "rows": []}
    data.setdefault("rows", [])
    data.setdefault("asof", "recent estimate")
    return data


# ── 4. Central bank policy tracker ───────────────────────────────────────────
def load_central_banks(api_key: str) -> dict:
    prompt = f"""Use web search for the CURRENT figures. Build a global central-bank policy tracker for: Federal Reserve (US), ECB (Euro Area), Bank of Japan (Japan), Bank of England (UK), People's Bank of China (China), Bank of Canada (Canada), Reserve Bank of Australia (Australia), Swiss National Bank (Switzerland), Reserve Bank of India (India), Banco Central do Brasil (Brazil), Banco de Mexico (Mexico), Central Bank of Turkey (Turkey).

{MP_FRAMEWORK}

Return ONLY a JSON object:
{{
  "rows": [
    {{"bank": "<name>", "country": "<country>", "rate": <current policy rate %>, "direction": "<HIKING|CUTTING|PAUSED>", "cpi": <latest YoY CPI %>, "mp_phase": "<MP1|MP2|MP3|TRANSITIONING>", "next_meeting": "<approx date or 'TBD'>", "consensus": "<expected action in one phrase>"}}
  ],
  "commentary": "<one paragraph: where is the global rate cycle right now, and what does Dalio's framework say about Fed vs ECB vs BOJ divergence?>"
}}

Use the most recent confirmed rate and CPI prints. real rate = rate − cpi (the UI computes this)."""
    data = call_json(prompt, api_key, max_tokens=4000)
    if not isinstance(data, dict):
        return {"rows": [], "commentary": ""}
    data.setdefault("rows", [])
    data.setdefault("commentary", "")
    return data


# ── 5. Country debt-cycle memo (streamed, on demand) ─────────────────────────
def prompt_debt_memo(today: str, country: str, baseline: dict) -> str:
    ind = (
        f"Debt/GDP ~{baseline.get('debt_gdp')}% · real rate ~{baseline.get('real_rate')}% · "
        f"CB balance sheet ~{baseline.get('cb_bs')}% GDP · deficit ~{baseline.get('deficit')}% GDP "
        f"(framework baseline — verify and update with web search)"
    )
    return f"""Today is {today}. Use web search to verify current figures.

Produce a DEBT CYCLE memo on {country} through Ray Dalio's framework.

{MP_FRAMEWORK}

Framework baseline for {country}: {ind}
Current phase (baseline): {baseline.get('phase')} ({baseline.get('sub','')})

Write the memo with these sections:

CYCLE NARRATIVE
2–3 paragraphs: where {country}'s long-term debt cycle began in Dalio's framework, what MP phase it is in now and why, what the key transition signals have been, and what the framework predicts comes next. Verify the debt/GDP, real rate, CB balance sheet and deficit numbers with web search and state the current values.

WHAT TO WATCH
3 specific data points or events that would signal a phase transition.

HISTORICAL PARALLEL
One historical parallel Dalio's framework would draw, and the lesson.

Howard Marks memo style. Specific numbers only. No filler."""


# ── 6. Thesis stress test (Thesis War Room) ──────────────────────────────────
def load_stress_test(api_key: str, ticker: str, name: str, thesis: str) -> dict:
    prompt = f"""Today, use web search for what happened in markets in the last 24–48 hours relevant to {ticker} ({name}).

Core thesis: {thesis}

Return ONLY a JSON object:
{{
  "helps": ["<specific development that HELPS the thesis>", ...],
  "help_score": <integer 1-5>,
  "hurts": ["<specific development that HURTS the thesis>", ...],
  "hurt_score": <integer 1-5>,
  "momentum": "<STRENGTHENING|NEUTRAL|WEAKENING>",
  "action": "<HOLD|ADD|TRIM|WATCH>",
  "summary": "<one blunt sentence>"
}}

Be specific and current — cite actual events, numbers, analyst actions. If nothing material happened, say so and set momentum NEUTRAL."""
    data = call_json(prompt, api_key, max_tokens=2500)
    if not isinstance(data, dict):
        return {}
    return data


# ── 7. Macro thesis update ───────────────────────────────────────────────────
def load_macro_thesis(api_key: str, name: str, description: str) -> dict:
    prompt = f"""Today, use web search for the latest relevant developments.

Macro thesis: "{name}"
Description: {description}

Return ONLY a JSON object:
{{
  "confirmation": <integer 1-10, how strongly recent evidence confirms the thesis>,
  "status": "<ACTIVE|WATCH|PAUSED>",
  "evidence": ["<recent datapoint or event supporting/contradicting, with specifics>", ...],
  "summary": "<two sentences, Howard Marks tone>"
}}

Be specific and current. 10 = strongly confirmed by fresh evidence, 1 = strongly contradicted."""
    data = call_json(prompt, api_key, max_tokens=2500)
    if not isinstance(data, dict):
        return {}
    return data


# ── 8. Currency debasement commentary ────────────────────────────────────────
def load_debasement_commentary(api_key: str, rows: list[dict]) -> str:
    lines = [
        f"- {r['ccy']}: {r['chg5y']:+.0f}% vs gold (5y)"
        for r in rows if r.get("chg5y") is not None
    ]
    snapshot = "\n".join(lines) if lines else "(data pending)"
    prompt = f"""Use web search to confirm the gold/currency picture. Here is the 5-year change of major currencies measured against gold (negative = debased):

{snapshot}

In ONE paragraph, connect this debasement picture to Dalio's MP3 (fiscal-monetary / debt-monetization) thesis and what it implies for gold and commodity positioning. Specific, Howard Marks tone. Return plain text only."""
    return call_research(prompt, api_key, max_tokens=1200)
