"""Agent nodes for the LangGraph Multi-Agent Sector Research System.

Each node is a plain function that takes the shared ResearchState and
returns a partial state update (a dict containing only the keys it
produced). LangGraph merges these updates into the state as the graph
runs. The graph wiring itself lives in main.py — these are just the nodes.

Per the master spec (CLAUDE.md):
- §4 Dynamic sector prompt injection: every agent call appends a
  sector-specific valuation lens chosen from state["sector"].
- §5 Multi-model tiering: heavy workers (data_gatherer, screener, bull,
  bear) run on the cheap/fast tier; the red-team critic and the senior
  synthesis writer run on the high-capability tier.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from .state import ResearchState

_REPO_ROOT = Path(__file__).resolve().parent.parent

# market_data.py lives at the repo root, one level above this package.
sys.path.insert(0, str(_REPO_ROOT))
from market_data import fetch_ticker_fundamentals  # noqa: E402

try:
    from tavily import TavilyClient
except ImportError:  # keep the pipeline importable without the extra dep
    TavilyClient = None

# Credentials: the repo's .env stores the key as MAS_ANTHROPIC_KEY; the
# Anthropic SDK looks for ANTHROPIC_API_KEY, so map it across. An already-set
# ANTHROPIC_API_KEY in the environment always wins.
load_dotenv(_REPO_ROOT / ".env")
if os.environ.get("MAS_ANTHROPIC_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["MAS_ANTHROPIC_KEY"]

# ─────────────────────────────────────────────────────────────────────────────
# §5 Multi-model tiering (Anthropic mapping)
# ─────────────────────────────────────────────────────────────────────────────

# Heavy workers: cheap, fast extraction and drafting.
WORKER_MODEL = "claude-3-5-haiku-20241022"
# Red-team critic + senior writer: high-capability tier.
SENIOR_MODEL = "claude-3-5-sonnet-20241022"
MAX_TOKENS = 8000


def _llm(model: str) -> ChatAnthropic:
    """Build a chat model for the requested tier.

    ChatAnthropic reads ANTHROPIC_API_KEY from the environment.
    """
    return ChatAnthropic(model=model, max_tokens=MAX_TOKENS)


def _run(system_prompt: str, user_prompt: str, model: str = SENIOR_MODEL) -> str:
    """One system + user round trip on the given model tier."""
    response = _llm(model).invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    return response.content if isinstance(response.content, str) else str(response.content)


# ─────────────────────────────────────────────────────────────────────────────
# §4 Dynamic sector prompt injection
# ─────────────────────────────────────────────────────────────────────────────

SECTOR_VALUATION_RULES = {
    "Technology": (
        "Focus on SaaS-style margin structure (gross margin trajectory, "
        "recurring revenue mix — e.g. QTL-style licensing streams), R&D "
        "intensity as a % of revenue, and value the business with a DCF "
        "cross-checked by a Sum-of-the-Parts (SOTP) where segments differ "
        "materially in quality."
    ),
    "Financials": (
        "Focus on Net Interest Margin (NIM) trends, Loan-to-Deposit ratios, "
        "credit quality and reserve coverage, and value the business with "
        "Residual Income / Price-to-Book models rather than raw P/E."
    ),
    "Energy": (
        "Focus on Net Asset Value (NAV) of the reserve base, the reserve "
        "replacement ratio, break-even costs, and sensitivity/correlation "
        "to Brent crude. Value on NAV and strip-price cash flows, not "
        "spot-cycle earnings multiples."
    ),
}

_DEFAULT_SECTOR_RULES = (
    "Apply standard fundamental analysis: revenue durability, margin "
    "structure, capital intensity, balance-sheet strength, and a DCF "
    "sanity-checked against comparable-company multiples."
)


def _sector_lens(state: ResearchState) -> str:
    """The valuation-rules block injected into every agent's system prompt."""
    rules = SECTOR_VALUATION_RULES.get(state["sector"], _DEFAULT_SECTOR_RULES)
    return f"\n\nSECTOR VALUATION LENS ({state['sector']}):\n{rules}"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Data Gatherer (worker) — fills the scratchpads and the normalized ledger
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
want to miss. From the latest earnings report/call, assess sentiment: beats
or misses, guidance direction, and management's confidence level.

The user message may include two live data blocks — treat them as ground
truth, in this order of authority:
1. LIVE WEB RESEARCH (Tavily): real-time search results covering recent SEC
   filings, earnings figures, one-time items, and current price/valuation.
   Prefer these for anything time-sensitive, and cite the source URL next to
   figures you take from them.
2. LIVE MARKET DATA (yfinance): structured quote/statement feed — use it to
   cross-check the web figures, and pay special attention to any fiscal year
   flagged `tax_year_looks_distorted` — recompute the normalized P/E from
   `normalized_net_income` for those years.
Fill gaps from your own knowledge only when both sources are silent, and
clearly mark which figures are sourced vs. estimated. If both blocks report
errors, say so prominently in sec_filings_summary so downstream agents know
the data is unanchored.

Populate ALL FOUR output fields — an answer missing any of them is
incomplete:
  raw_financials: compact object of raw extracted metrics (headline figures
    only — a few dozen key numbers, not an exhaustive dump),
  normalized_metrics: the adjustment ledger — each one-time item isolated
    with its impact, plus adjusted EPS / normalized P/E / clean margins,
  sec_filings_summary: prose summary of the filing analysis,
  earnings_sentiment: prose read on the latest earnings tone and guidance.
"""


def _tavily_research(ticker: str, sector: str, user_query: str) -> dict:
    """Live web research via Tavily: recent SEC filings, earnings figures,
    one-time items, and current valuation for the target ticker.

    Same degradation contract as the yfinance fetcher — a missing API key,
    missing package, or network failure records an error and returns, so the
    pipeline never stalls on the search layer.
    """
    out: dict = {"source": "tavily", "results": {}, "errors": []}
    if TavilyClient is None:
        out["errors"].append("tavily-python not installed")
        return out
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        out["errors"].append("TAVILY_API_KEY not set")
        return out

    client = TavilyClient(api_key=api_key)
    queries = [
        f"{ticker} latest 10-K 10-Q SEC filing risk factors segment results",
        f"{ticker} most recent quarterly earnings revenue EPS guidance",
        f"{ticker} one-time charges tax impairment non-recurring items",
        f"{ticker} stock price market cap P/E valuation today",
    ]
    for q in queries:
        try:
            resp = client.search(
                query=q, search_depth="advanced", max_results=5, include_answer=True
            )
            out["results"][q] = {
                "answer": resp.get("answer"),
                "sources": [
                    {
                        "title": r.get("title"),
                        "url": r.get("url"),
                        "content": (r.get("content") or "")[:800],
                    }
                    for r in resp.get("results", [])
                ],
            }
        except Exception as e:
            out["errors"].append(f"{q}: {e}")
    return out


class GathererOutput(BaseModel):
    """Structured contract for the data gatherer's response — enforced via
    tool calling so the model cannot drift into prose or fenced markdown.
    Fields default to empty so a partial tool call degrades instead of
    failing validation outright."""

    raw_financials: dict = {}
    normalized_metrics: dict = {}
    sec_filings_summary: str = ""
    earnings_sentiment: str = ""


def _run_structured(system_prompt: str, user_prompt: str, model: str) -> GathererOutput:
    """Schema-enforced round trip; one retry if the ledger comes back empty."""
    structured_llm = _llm(model).with_structured_output(GathererOutput)
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    result = structured_llm.invoke(messages)
    if result is None or not result.normalized_metrics:
        retry_messages = messages + [HumanMessage(content=(
            "Your previous tool call was incomplete. Call the tool again and "
            "populate ALL FOUR fields — raw_financials, normalized_metrics, "
            "sec_filings_summary, earnings_sentiment. Keep raw_financials "
            "compact so you have room for the other three."
        ))]
        retried = structured_llm.invoke(retry_messages)
        if retried is not None and retried.normalized_metrics:
            return retried
    return result if result is not None else GathererOutput()


def data_gatherer_node(state: ResearchState) -> dict:
    """Extract raw + normalized financial data and filing/earnings reads.

    Populates: raw_financials, normalized_metrics, sec_filings_summary,
    earnings_sentiment.
    """
    # Primary live source: Tavily web research (real-time SEC filings,
    # earnings figures, one-time items, current valuation). Secondary:
    # structured yfinance feed as a cross-check. Both degrade to recorded
    # errors on any failure, so the node still runs — the model is told
    # which figures are live vs. estimated.
    ticker = state.get("ticker")
    web_research = (
        _tavily_research(ticker, state["sector"], state["user_query"])
        if ticker else None
    )
    live_data = fetch_ticker_fundamentals(ticker) if ticker else None

    web_block = (
        f"LIVE WEB RESEARCH (Tavily):\n{json.dumps(web_research, indent=2, default=str)}\n\n"
        if web_research else
        "LIVE WEB RESEARCH: none available for this request.\n\n"
    )
    live_block = (
        f"LIVE MARKET DATA (yfinance):\n{json.dumps(live_data, indent=2, default=str)}\n\n"
        if live_data else
        "LIVE MARKET DATA: none available for this request.\n\n"
    )
    user_prompt = (
        f"Mode: {state['mode']}\n"
        f"Sector: {state['sector']}\n"
        f"Ticker: {ticker or 'N/A (sector screener)'}\n"
        f"User request: {state['user_query']}\n\n"
        + web_block + live_block +
        "Gather and normalize the financial data as instructed."
    )
    system = DATA_GATHERER_SYSTEM_PROMPT + _sector_lens(state)

    # Primary path: schema-enforced output (tool calling), so the model
    # cannot drift into prose. Fallback: plain text with best-effort JSON
    # parsing (stripping any ```json fence), so the pipeline never stalls.
    try:
        parsed = _run_structured(system, user_prompt, model=WORKER_MODEL)
        raw_financials = parsed.raw_financials
        normalized_metrics = parsed.normalized_metrics
        sec_filings_summary = parsed.sec_filings_summary
        earnings_sentiment = parsed.earnings_sentiment
    except Exception:
        raw = _run(system, user_prompt, model=WORKER_MODEL)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
            cleaned = cleaned.rstrip().removesuffix("```").rstrip()
        try:
            parsed_json = json.loads(cleaned)
            raw_financials = parsed_json.get("raw_financials", {})
            normalized_metrics = parsed_json.get("normalized_metrics", {})
            sec_filings_summary = parsed_json.get("sec_filings_summary", raw)
            earnings_sentiment = parsed_json.get("earnings_sentiment", "")
        except (json.JSONDecodeError, AttributeError):
            raw_financials = {"unparsed_output": raw}
            normalized_metrics = {}
            sec_filings_summary = raw
            earnings_sentiment = ""

    # Keep the untouched feeds alongside the model's derived metrics so the
    # bull/bear agents can check the analysis against the source material.
    if isinstance(raw_financials, dict):
        if web_research is not None:
            raw_financials["web_research"] = web_research
        if live_data is not None:
            raw_financials["live_market_data"] = live_data

    return {
        "raw_financials": raw_financials,
        "normalized_metrics": normalized_metrics,
        "sec_filings_summary": sec_filings_summary,
        "earnings_sentiment": earnings_sentiment,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Screener (worker) — "The Radar": drafts the sector shortlist
# ─────────────────────────────────────────────────────────────────────────────

SCREENER_SYSTEM_PROMPT = """\
You are a sector screener for an investment research team. Survey the given
sector and produce a ranked shortlist of the most interesting candidates for
further research.

For each candidate: ticker, one-line thesis, key metric that earns it the
spot, and the main risk. Rank by attractiveness and say why the top pick is
ranked first. Flag any candidate that deserves a full deep dive.

Your output is a DRAFT for the senior writer — favor completeness and
evidence over polish.
"""


def screener_node(state: ResearchState) -> dict:
    """Broad sector sweep producing a ranked shortlist draft.

    Populates: quantitative_raw_data['screener_shortlist'] — the synthesis
    node polishes this draft into the final memo.
    """
    user_prompt = (
        f"Sector: {state['sector']}\n"
        f"User request: {state['user_query']}\n\n"
        "Run the screen and produce the ranked shortlist draft."
    )
    draft = _run(
        SCREENER_SYSTEM_PROMPT + _sector_lens(state),
        user_prompt,
        model=WORKER_MODEL,
    )
    return {"quantitative_raw_data": {"screener_shortlist": draft}}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Bull Agent (worker) — writes the strongest good-faith long case
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


def _debate_prompt(state: ResearchState, closing_line: str) -> str:
    """Shared evidence pack for the bull and bear agents."""
    return (
        f"Target: {state.get('ticker') or state['sector']}\n"
        f"User request: {state['user_query']}\n\n"
        f"Raw financials:\n{json.dumps(state['raw_financials'], indent=2, default=str)}\n\n"
        f"Normalized metrics (adjustment ledger):\n"
        f"{json.dumps(state['normalized_metrics'], indent=2, default=str)}\n\n"
        f"SEC filings summary:\n{state['sec_filings_summary']}\n\n"
        f"Earnings sentiment:\n{state.get('earnings_sentiment') or 'None provided.'}\n\n"
        f"Macro context:\n{state.get('macro_context') or 'None provided.'}\n\n"
        f"{closing_line}"
    )


def bull_agent_node(state: ResearchState) -> dict:
    """Write the bull thesis from the gathered data.

    Reads: raw_financials, normalized_metrics, sec_filings_summary,
    earnings_sentiment, macro_context.
    Populates: bull_thesis.
    """
    return {
        "bull_thesis": _run(
            BULL_SYSTEM_PROMPT + _sector_lens(state),
            _debate_prompt(state, "Write the bull thesis."),
            model=WORKER_MODEL,
        )
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Bear Agent (worker) — hunts for what could go wrong
# ─────────────────────────────────────────────────────────────────────────────

BEAR_SYSTEM_PROMPT = """\
You are the bear analyst whose job is to find every reason this investment
could fail. Using only the data provided, write the strongest good-faith
case AGAINST the investment.

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
    """Write the bear thesis from the gathered data.

    Reads: raw_financials, normalized_metrics, sec_filings_summary,
    earnings_sentiment, macro_context.
    Populates: bear_thesis.
    """
    return {
        "bear_thesis": _run(
            BEAR_SYSTEM_PROMPT + _sector_lens(state),
            _debate_prompt(state, "Write the bear thesis."),
            model=WORKER_MODEL,
        )
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Red Team Critique (senior tier) — attacks the debate itself
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

    Reads: bull_thesis, bear_thesis, raw_financials, normalized_metrics,
    sec_filings_summary.
    Populates: red_team_critique.
    """
    user_prompt = (
        f"Target: {state.get('ticker') or state['sector']}\n"
        f"User request: {state['user_query']}\n\n"
        f"UNDERLYING DATA (check every claim against this):\n"
        f"{json.dumps(state['raw_financials'], indent=2, default=str)}\n\n"
        f"Normalized metrics (adjustment ledger):\n"
        f"{json.dumps(state['normalized_metrics'], indent=2, default=str)}\n\n"
        f"SEC filings summary:\n{state['sec_filings_summary']}\n\n"
        f"BULL THESIS UNDER REVIEW:\n{state['bull_thesis']}\n\n"
        f"BEAR THESIS UNDER REVIEW:\n{state['bear_thesis']}\n\n"
        "Write the red-team critique."
    )
    return {
        "red_team_critique": _run(
            RED_TEAM_SYSTEM_PROMPT + _sector_lens(state),
            user_prompt,
            model=SENIOR_MODEL,
        )
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. Synthesis (senior tier) — the senior writer producing the final memo
# ─────────────────────────────────────────────────────────────────────────────

SYNTHESIS_SYSTEM_PROMPT = """\
You are the senior portfolio strategist and lead writer. You produce the
team's final, decision-ready deliverable.

For a DEEP DIVE you receive a bull thesis, a bear thesis, and a red-team
critique built from the same underlying data:
- Weigh the two theses against each other explicitly: where does the bear
  case actually land a blow, and where does the bull case survive contact?
- Apply the red-team critique: discard or caveat any argument it discredited,
  and answer the open questions it says the memo must not ignore.
- Do not split the difference reflexively — take a view, and say what
  evidence would change it.
- Structure the memo: summary and recommendation up front, then the key
  debate points, then risks and monitoring triggers.

For a SCREENER you receive a draft shortlist from the screener worker:
- Polish it into an institutional-grade screener memo: ranked shortlist,
  one-line thesis + key metric + main risk per name, and a clear call on
  which candidates deserve a full deep dive.
- Cut weak candidates rather than padding the list.

Either way: keep it grounded in the underlying data; strip any claim that
is not supported by evidence.
"""


def synthesis_node(state: ResearchState) -> dict:
    """Write the final memo for whichever pipeline ran.

    Deep dive — reads: bull_thesis, bear_thesis, red_team_critique.
    Screener — reads: quantitative_raw_data['screener_shortlist'].
    Populates: final_memo.
    """
    if state["mode"] == "screener":
        user_prompt = (
            f"Sector: {state['sector']}\n"
            f"User request: {state['user_query']}\n\n"
            f"SCREENER SHORTLIST DRAFT:\n"
            f"{state['quantitative_raw_data'].get('screener_shortlist', 'None provided.')}\n\n"
            "Polish this into the final screener memo."
        )
    else:
        user_prompt = (
            f"Target: {state.get('ticker') or state['sector']}\n"
            f"User request: {state['user_query']}\n\n"
            f"BULL THESIS:\n{state['bull_thesis']}\n\n"
            f"BEAR THESIS:\n{state['bear_thesis']}\n\n"
            f"RED TEAM CRITIQUE:\n{state['red_team_critique']}\n\n"
            "Write the final investment memo."
        )
    return {
        "final_memo": _run(
            SYNTHESIS_SYSTEM_PROMPT + _sector_lens(state),
            user_prompt,
            model=SENIOR_MODEL,
        )
    }
