"""Agent nodes for the LangGraph Multi-Agent Sector Research System.

Each node is a plain function that takes the shared ResearchState and
returns a partial state update (a dict containing only the keys it
produced). LangGraph merges these updates into the state as the graph
runs. The graph wiring itself lives elsewhere — these are just the nodes.

Node flow (wired in the next step):

    data_gatherer_node ──> bull_agent_node ──┐
                      └──> bear_agent_node ──┴──> synthesis_node
"""

import json
import sys
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from .state import ResearchState

# market_data.py lives at the repo root, one level above this package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from market_data import fetch_ticker_fundamentals  # noqa: E402

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


# ─────────────────────────────────────────────────────────────────────────────
# 1. Data Gatherer — populates raw_financials and sec_filing_summary
# ─────────────────────────────────────────────────────────────────────────────

DATA_GATHERER_SYSTEM_PROMPT = """\
You are a forensic financial data analyst preparing the quantitative foundation
for an investment research team.

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

From SEC filings (10-K, 10-Q, 8-K), summarize risk factors, management's
discussion, segment trends, and any disclosures a diligent analyst would not
want to miss.

When the user message includes LIVE MARKET DATA (fetched from yfinance),
treat those figures as ground truth: build your ratios from them, reconcile
your adjusted metrics against them, and pay special attention to any fiscal
year flagged `tax_year_looks_distorted` — recompute the normalized P/E from
`normalized_net_income` for those years. Fill gaps (null fields) from your
own knowledge, but clearly mark which figures came from the feed and which
are estimates.

Return your answer as JSON with two keys:
  "raw_financials": an object of the metrics you extracted/derived
    (include both headline and adjusted values where they differ),
  "sec_filing_summary": a prose summary of the filing analysis.
"""


def data_gatherer_node(state: ResearchState) -> dict:
    """Extract normalized financial data and a filing summary for the target.

    Populates: raw_financials, sec_filing_summary.
    """
    # Pull real quote/valuation/statement data via yfinance (market_data.py).
    # The fetch degrades to None fields on any network failure, so the node
    # still runs — the model is told which figures are live vs. estimated.
    live_data = fetch_ticker_fundamentals(state["ticker"]) if state.get("ticker") else None

    live_block = (
        f"LIVE MARKET DATA (yfinance):\n{json.dumps(live_data, indent=2, default=str)}\n\n"
        if live_data else
        "LIVE MARKET DATA: none available for this request.\n\n"
    )
    user_prompt = (
        f"Mode: {state['mode']}\n"
        f"Sector: {state['sector']}\n"
        f"Ticker: {state.get('ticker') or 'N/A (sector screener)'}\n"
        f"User request: {state['user_query']}\n\n"
        + live_block +
        "Gather and normalize the financial data as instructed."
    )
    raw = _run(DATA_GATHERER_SYSTEM_PROMPT, user_prompt)

    # Best-effort parse of the requested JSON shape; fall back to storing the
    # raw text so downstream agents always have something to work with.
    try:
        parsed = json.loads(raw)
        raw_financials = parsed.get("raw_financials", {})
        sec_filing_summary = parsed.get("sec_filing_summary", raw)
    except (json.JSONDecodeError, AttributeError):
        raw_financials = {"unparsed_output": raw}
        sec_filing_summary = raw

    # Keep the untouched feed alongside the model's derived metrics so the
    # bull/bear agents can check the analysis against the source numbers.
    if live_data is not None and isinstance(raw_financials, dict):
        raw_financials["live_market_data"] = live_data

    return {
        "raw_financials": raw_financials,
        "sec_filing_summary": sec_filing_summary,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Bull Agent — writes the strongest good-faith long case
# ─────────────────────────────────────────────────────────────────────────────

BULL_SYSTEM_PROMPT = """\
You are the bull analyst on an investment research team. Using only the data
provided, write the strongest good-faith case FOR the investment.

Focus on:
- Upside risks the market may be underpricing: optionality, new product
  cycles, pricing power, sector tailwinds.
- Margin expansion: operating leverage, mix shift toward higher-margin
  revenue, cost programs that are already showing up in the numbers.
- Where the adjusted (normalized) figures tell a better story than the
  headline GAAP numbers, and why the adjustment is legitimate.

Ground every claim in the data you were given. Do not invent figures. Be
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
investment could fail. Using only the data provided, write the strongest
good-faith case AGAINST the investment.

Hunt specifically for:
- Accounting red flags: revenue recognition games, widening gaps between
  GAAP and "adjusted" earnings, receivables growing faster than revenue,
  serial "one-time" charges that recur every year.
- Debt walls: maturities clustered in the next few years, covenant pressure,
  refinancing risk at today's rates, off-balance-sheet obligations.
- Downside risks: customer concentration, secular decline masked by cyclical
  strength, margin peaks being extrapolated, management's incentives.

Ground every claim in the data you were given. Do not invent figures. Be
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
# 4. Red Team Critique — attacks the debate itself before synthesis
# ─────────────────────────────────────────────────────────────────────────────

RED_TEAM_SYSTEM_PROMPT = """\
You are an independent red-team reviewer. You did not write either thesis and
you hold no position. Your job is to attack the QUALITY OF THE ARGUMENTS on
both sides before they reach the senior writer — not to pick a winner.

For each thesis, bull and bear alike, hunt for:
- Claims not supported by the underlying data (cite the specific claim).
- Cherry-picking: evidence in the data that the thesis ignored because it
  cuts the other way.
- Logical leaps: correlations read as causation, single quarters extrapolated
  into trends, adjusted metrics used where GAAP is the honest choice (or
  vice versa).
- Stale or double-counted arguments: the same point dressed up as two, or
  risks/catalysts the market has plainly already priced.

Structure your critique in three parts:
1. Weaknesses in the bull thesis (each with the evidence that undermines it).
2. Weaknesses in the bear thesis (same standard).
3. Open questions neither side addressed that the final memo must not ignore.

Be specific and cite the data. A vague critique is worthless.
"""


def red_team_node(state: ResearchState) -> dict:
    """Critique both theses against the underlying data before synthesis.

    Reads: bull_thesis, bear_thesis, raw_financials, sec_filing_summary.
    Populates: red_team_critique.
    """
    user_prompt = (
        f"Target: {state.get('ticker') or state['sector']}\n"
        f"User request: {state['user_query']}\n\n"
        f"UNDERLYING DATA (check every claim against this):\n"
        f"{json.dumps(state['raw_financials'], indent=2, default=str)}\n\n"
        f"SEC filing summary:\n{state['sec_filing_summary']}\n\n"
        f"BULL THESIS UNDER REVIEW:\n{state['bull_thesis']}\n\n"
        f"BEAR THESIS UNDER REVIEW:\n{state['bear_thesis']}\n\n"
        "Write the red-team critique."
    )
    return {"red_team_critique": _run(RED_TEAM_SYSTEM_PROMPT, user_prompt)}


# ─────────────────────────────────────────────────────────────────────────────
# 5. Synthesis — the senior writer producing the final memo
# ─────────────────────────────────────────────────────────────────────────────

SYNTHESIS_SYSTEM_PROMPT = """\
You are the senior portfolio strategist and lead writer. You have received a
bull thesis and a bear thesis built from the same underlying data. Your job is
to synthesize them into a single decision-ready investment memo.

Requirements:
- Weigh the two theses against each other explicitly: where does the bear
  case actually land a blow, and where does the bull case survive contact?
- Apply the red-team critique: discard or caveat any argument it discredited,
  and answer the open questions it says the memo must not ignore.
- Do not split the difference reflexively — take a view, and say what
  evidence would change it.
- Structure the memo: summary and recommendation up front, then the key
  debate points, then risks and monitoring triggers.
- Keep it grounded in the underlying data; strip any claim neither side
  supported with evidence.
"""


def synthesis_node(state: ResearchState) -> dict:
    """Synthesize the debate and the red-team critique into the final memo.

    Reads: bull_thesis, bear_thesis, red_team_critique.
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
