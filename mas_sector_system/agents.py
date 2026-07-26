"""Agent nodes for the LangGraph Multi-Agent Sector Research System.

Each node is a plain function that takes the shared ResearchState and
returns a partial state update (a dict containing only the keys it
produced). LangGraph merges these updates into the state as the graph
runs. The graph wiring itself lives elsewhere — these are just the nodes.

Node flow (wired in the next step):

    data_gatherer_node ──> bull_agent_node ──┐
                      └──> bear_agent_node ──┴──> synthesis_node

Live data: data_gatherer_node calls Tavily (web) + yfinance (quotes/
fundamentals) BEFORE prompting the LLM. Downstream agents only reason over
that grounded context — they do not invent market numbers.
"""

import json
import re
from typing import Any, Dict, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from .state import ResearchState
from .tools import gather_live_research_context

# The repo's Streamlit app currently runs Sonnet; for the research agents we
# default to Opus, Anthropic's most capable generally-available tier.
MODEL = "claude-opus-4-8"
MAX_TOKENS = 8000


def _llm() -> ChatAnthropic:
    """Build the chat model shared by all agents.

    ChatAnthropic reads ANTHROPIC_API_KEY from the environment.
    """
    return ChatAnthropic(model=MODEL, max_tokens=MAX_TOKENS)


def _run(system_prompt: str, user_prompt: str) -> str:
    """One system + user round trip, returning the text response."""
    response = _llm().invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    return response.content if isinstance(response.content, str) else str(response.content)


def _parse_json_blob(raw: str) -> Optional[Dict[str, Any]]:
    """Best-effort extract of a JSON object from model output (may be fenced)."""
    text = raw.strip()
    # Strip ```json ... ``` fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        # Last resort: first {...} block
        brace = re.search(r"\{[\s\S]*\}", text)
        if not brace:
            return None
        try:
            parsed = json.loads(brace.group(0))
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Data Gatherer — populates raw_financials, sec_filing_summary, macro_context
# ─────────────────────────────────────────────────────────────────────────────

DATA_GATHERER_SYSTEM_PROMPT = """\
You are a forensic financial data analyst preparing the quantitative foundation
for an investment research team.

You will be given LIVE data pulled moments ago from:
  (1) yfinance — price, multiples, margins, balance-sheet items
  (2) Tavily web search — recent news, earnings coverage, SEC filing summaries

Treat that live data as the source of truth. Do NOT invent numbers that are
not supported by the provided live data or search snippets. If a metric is
missing, say so explicitly rather than filling it from memory.

Your job is to extract and normalize the company's financials — not just report
headline numbers. Explicitly look for and calculate ADJUSTED metrics:

- Strip out one-time items before computing valuation ratios. A massive
  non-recurring tax hit, impairment, legal settlement, or divestiture gain can
  make headline EPS meaningless — recompute a normalized P/E on earnings with
  those items removed, and show your work (headline vs. adjusted, with the
  reconciling items listed).
- Normalize margins for one-off charges so the trend is comparable
  quarter-over-quarter and year-over-year.
- Flag any metric where GAAP and adjusted figures diverge materially, and say
  why they diverge.

From the search results covering SEC filings (10-K, 10-Q, 8-K) and news,
summarize risk factors, management's discussion, segment trends, and any
disclosures a diligent analyst would not want to miss.

Also extract a short macro backdrop relevant to this name/sector from the
search hits (rates, inflation, policy, sector cycle).

Return your answer as JSON with three keys:
  "raw_financials": an object of the metrics you extracted/derived
    (include both headline and adjusted values where they differ; copy through
    key live fields such as price, trailing_pe, forward_pe, market_cap,
    margins, debt, growth rates with an as_of stamp),
  "sec_filing_summary": a prose summary of the filing / disclosure analysis,
  "macro_context": a short prose macro/sector backdrop grounded in the search.
"""


def data_gatherer_node(state: ResearchState) -> dict:
    """Fetch live market + web data, then normalize via the LLM.

    Populates: raw_financials, sec_filing_summary, macro_context.
    """
    live = gather_live_research_context(
        ticker=state.get("ticker"),
        sector=state["sector"],
        user_query=state["user_query"],
    )

    user_prompt = (
        f"Mode: {state['mode']}\n"
        f"Sector: {state['sector']}\n"
        f"Ticker: {state.get('ticker') or 'N/A (sector screener)'}\n"
        f"User request: {state['user_query']}\n"
        f"Live data gathered at (UTC): {live['gathered_at_utc']}\n"
        f"Search queries run: {json.dumps(live['queries_run'])}\n\n"
        f"=== LIVE FUNDAMENTALS (yfinance) ===\n"
        f"{json.dumps(live['fundamentals'], indent=2, default=str)}\n\n"
        f"=== LIVE WEB RESEARCH (Tavily) ===\n"
        f"{live['web_research']}\n\n"
        "Using ONLY the live data above, normalize the financials and produce "
        "the requested JSON. Cite which search hit or yfinance field supports "
        "material claims."
    )
    raw = _run(DATA_GATHERER_SYSTEM_PROMPT, user_prompt)

    parsed = _parse_json_blob(raw)
    if parsed:
        raw_financials = parsed.get("raw_financials") or {}
        if not isinstance(raw_financials, dict):
            raw_financials = {"value": raw_financials}
        # Always attach the live source payload so downstream agents can audit.
        raw_financials.setdefault("_live_yfinance", live["fundamentals"])
        raw_financials.setdefault("_live_queries", live["queries_run"])
        raw_financials.setdefault("_gathered_at_utc", live["gathered_at_utc"])
        sec_filing_summary = parsed.get("sec_filing_summary") or raw
        macro_context = parsed.get("macro_context") or ""
    else:
        raw_financials = {
            "unparsed_output": raw,
            "_live_yfinance": live["fundamentals"],
            "_live_queries": live["queries_run"],
            "_gathered_at_utc": live["gathered_at_utc"],
        }
        sec_filing_summary = raw
        macro_context = ""

    # If the model skipped macro, fall back to a compact search digest.
    if not macro_context:
        macro_context = (
            f"Live web research digest (gathered {live['gathered_at_utc']} UTC):\n"
            f"{live['web_research'][:4000]}"
        )

    return {
        "raw_financials": raw_financials,
        "sec_filing_summary": sec_filing_summary,
        "macro_context": macro_context,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Bull Agent — writes the strongest good-faith long case
# ─────────────────────────────────────────────────────────────────────────────

BULL_SYSTEM_PROMPT = """\
You are the bull analyst on an investment research team. Using only the LIVE
data provided (yfinance fundamentals + Tavily web research normalized by the
data gatherer), write the strongest good-faith case FOR the investment.

Focus on:
- Upside risks the market may be underpricing: optionality, new product
  cycles, pricing power, sector tailwinds.
- Margin expansion: operating leverage, mix shift toward higher-margin
  revenue, cost programs that are already showing up in the numbers.
- Where the adjusted (normalized) figures tell a better story than the
  headline GAAP numbers, and why the adjustment is legitimate.

Ground every claim in the data you were given. Do not invent figures or pull
stale training-data numbers. If the live packet lacks a metric, say so. Be
persuasive but intellectually honest — your work will be attacked by a bear
analyst reading the same data.
"""


def bull_agent_node(state: ResearchState) -> dict:
    """Write the bull thesis from the gathered data.

    Reads: raw_financials, sec_filing_summary, macro_context.
    Populates: bull_thesis.
    """
    user_prompt = (
        f"Target: {state.get('ticker') or state['sector']}\n"
        f"User request: {state['user_query']}\n\n"
        f"Raw financials:\n{json.dumps(state['raw_financials'], indent=2, default=str)}\n\n"
        f"SEC filing summary:\n{state['sec_filing_summary']}\n\n"
        f"Macro context:\n{state.get('macro_context') or 'None provided.'}\n\n"
        "Write the bull thesis."
    )
    return {"bull_thesis": _run(BULL_SYSTEM_PROMPT, user_prompt)}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Bear Agent (Red Team) — hunts for what could go wrong
# ─────────────────────────────────────────────────────────────────────────────

BEAR_SYSTEM_PROMPT = """\
You are the red team: the bear analyst whose job is to find every reason this
investment could fail. Using only the LIVE data provided (yfinance
fundamentals + Tavily web research normalized by the data gatherer), write
the strongest good-faith case AGAINST the investment.

Hunt specifically for:
- Accounting red flags: revenue recognition games, widening gaps between
  GAAP and \"adjusted\" earnings, receivables growing faster than revenue,
  serial \"one-time\" charges that recur every year.
- Debt walls: maturities clustered in the next few years, covenant pressure,
  refinancing risk at today's rates, off-balance-sheet obligations.
- Downside risks: customer concentration, secular decline masked by cyclical
  strength, margin peaks being extrapolated, management's incentives.

Ground every claim in the data you were given. Do not invent figures or pull
stale training-data numbers. If the live packet lacks a metric, say so. Be
ruthless but fair — a weak bear case helps no one.
"""


def bear_agent_node(state: ResearchState) -> dict:
    """Write the bear thesis (red-team attack) from the gathered data.

    Reads: raw_financials, sec_filing_summary, macro_context.
    Populates: bear_thesis.
    """
    user_prompt = (
        f"Target: {state.get('ticker') or state['sector']}\n"
        f"User request: {state['user_query']}\n\n"
        f"Raw financials:\n{json.dumps(state['raw_financials'], indent=2, default=str)}\n\n"
        f"SEC filing summary:\n{state['sec_filing_summary']}\n\n"
        f"Macro context:\n{state.get('macro_context') or 'None provided.'}\n\n"
        "Write the bear thesis."
    )
    return {"bear_thesis": _run(BEAR_SYSTEM_PROMPT, user_prompt)}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Synthesis — the senior writer producing the final memo
# ─────────────────────────────────────────────────────────────────────────────

SYNTHESIS_SYSTEM_PROMPT = """\
You are the senior portfolio strategist and lead writer. You have received a
bull thesis and a bear thesis built from the same underlying data. Your job is
to synthesize them into a single decision-ready investment memo.

Requirements:
- Weigh the two theses against each other explicitly: where does the bear
  case actually land a blow, and where does the bull case survive contact?
- Do not split the difference reflexively — take a view, and say what
  evidence would change it.
- Structure the memo: summary and recommendation up front, then the key
  debate points, then risks and monitoring triggers.
- Keep it grounded in the underlying data; strip any claim neither side
  supported with evidence.
"""


def synthesis_node(state: ResearchState) -> dict:
    """Synthesize the debate into the final memo.

    Reads: bull_thesis, bear_thesis (plus red_team_critique when a dedicated
    critique node is added to the graph).
    Populates: final_memo.
    """
    user_prompt = (
        f"Target: {state.get('ticker') or state['sector']}\n"
        f"User request: {state['user_query']}\n\n"
        f"BULL THESIS:\n{state['bull_thesis']}\n\n"
        f"BEAR THESIS:\n{state['bear_thesis']}\n\n"
        f"RED TEAM CRITIQUE:\n{state.get('red_team_critique') or 'None provided.'}\n\n"
        "Write the final investment memo."
    )
    return {"final_memo": _run(SYNTHESIS_SYSTEM_PROMPT, user_prompt)}
