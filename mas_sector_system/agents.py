"""Agent nodes for the LangGraph Multi-Agent Sector Research System.

Each node is a plain function that takes the shared ResearchState and
returns a partial state update (a dict containing only the keys it
produced). LangGraph merges these updates into the state as the graph runs.

Deep-dive fan-out (wired in main.py):

    entry ──┬─> data_gatherer ──────────┐
            └─> business_overview ──────┼─> bull / bear / fundamental / relative ─> synthesis
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from .state import ResearchState
from .tools import (
    gather_business_overview_context,
    gather_live_research_context,
    multi_search,
)

# ── Model tiering ────────────────────────────────────────────────────────────
# Opus: highest-stakes reasoning (data foundation + final deliverable).
# Sonnet: bounded analytical writing over already-clean data.
OPUS_MODEL = "claude-opus-5"
SONNET_MODEL = "claude-sonnet-5"

MAX_TOKENS_OPUS = 8000
MAX_TOKENS_SONNET = 4000


def _llm(model: str = SONNET_MODEL, max_tokens: Optional[int] = None) -> ChatAnthropic:
    """Build a chat model. ChatAnthropic reads ANTHROPIC_API_KEY from the env."""
    if max_tokens is None:
        max_tokens = MAX_TOKENS_OPUS if model == OPUS_MODEL else MAX_TOKENS_SONNET
    return ChatAnthropic(model=model, max_tokens=max_tokens)


def _run(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str = SONNET_MODEL,
    max_tokens: Optional[int] = None,
) -> str:
    """One system + user round trip, returning the text response."""
    response = _llm(model, max_tokens=max_tokens).invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    return response.content if isinstance(response.content, str) else str(response.content)


def _run_with_shared_cache(
    system_prompt: str,
    shared_data_block: str,
    task_instruction: str,
    *,
    model: str = SONNET_MODEL,
    max_tokens: Optional[int] = None,
) -> str:
    """Round trip with Anthropic prompt caching on the shared data block.

    bull / bear / fundamental / relative all receive the same statement +
    overview payload; only the system lens and task instruction differ.
    Marking the shared block with cache_control makes subsequent calls in
    the same run hit a cheaper cached read.
    """
    response = _llm(model, max_tokens=max_tokens).invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": shared_data_block,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": task_instruction,
                    },
                ]
            ),
        ]
    )
    return response.content if isinstance(response.content, str) else str(response.content)


def _parse_json_blob(raw: str) -> Optional[Dict[str, Any]]:
    """Best-effort extract of a JSON object from model output (may be fenced)."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        brace = re.search(r"\{[\s\S]*\}", text)
        if not brace:
            return None
        try:
            parsed = json.loads(brace.group(0))
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None


def _json_block(label: str, payload: Any) -> str:
    return f"=== {label} ===\n{json.dumps(payload, indent=2, default=str)}"


def _shared_research_payload(state: ResearchState) -> str:
    """Shared data block for the four parallel analysis agents.

    Intentionally excludes debug/audit fields (_live_*, queries, timestamps)
    so they are not re-serialized into every downstream prompt.
    """
    return "\n\n".join(
        [
            f"Target: {state.get('ticker') or state['sector']}",
            f"Sector: {state['sector']}",
            f"User request: {state['user_query']}",
            _json_block("BUSINESS OVERVIEW", state.get("business_overview") or "Not provided."),
            _json_block("INCOME STATEMENT", state.get("income_statement") or {}),
            _json_block("BALANCE SHEET", state.get("balance_sheet") or {}),
            _json_block("CASH FLOW STATEMENT", state.get("cash_flow_statement") or {}),
            _json_block("SEC FILING SUMMARY", state.get("sec_filing_summary") or "Not provided."),
            _json_block("MACRO CONTEXT", state.get("macro_context") or "Not provided."),
        ]
    )


# ─────────────────────────────────────────────────────────────────────────────
# 0. Business Overview — pure description, parallel with data_gatherer
# ─────────────────────────────────────────────────────────────────────────────

BUSINESS_OVERVIEW_SYSTEM_PROMPT = """\
You are a company research analyst writing the descriptive foundation for an
investment memo. Your only job is to explain what the business *is* — not
whether it is cheap, expensive, a buy, or a sell.

You will be given LIVE web research focused on the 10-K Item 1 "Business"
section and related company materials. Ground every claim in those sources.
If a detail is not in the sources, say so rather than inventing it from
training memory.

Cover, in clear plain language (no jargon without a one-clause definition):
1. What the company does
2. Products and segments, and how they relate to each other
3. Revenue streams (subscription vs. one-time, product vs. services,
   recurring vs. project)
4. Geographic footprint
5. Competitive position and any durable advantage (or lack of one)
6. Corporate history — founding, pivots, major M&A
7. Strategic direction per management's own stated priorities

EXPLICITLY OUT OF SCOPE — do not include:
- Valuation opinions or multiples
- Buy / hold / sell language
- Financial ratios or margin analysis
- Price targets

Write tight prose suitable to open a professional investment memo
(roughly 400–800 words). Use short markdown headers sparingly if helpful.
"""


def business_overview_node(state: ResearchState) -> dict:
    """Produce a pure-descriptive company overview.

    Populates: business_overview.
    Independent of data_gatherer — runs in parallel from the entry point.
    """
    ctx = gather_business_overview_context(
        ticker=state.get("ticker"),
        sector=state["sector"],
        user_query=state["user_query"],
    )
    user_prompt = (
        f"Ticker: {state.get('ticker') or 'N/A'}\n"
        f"Sector: {state['sector']}\n"
        f"User request: {state['user_query']}\n"
        f"Research gathered at (UTC): {ctx['gathered_at_utc']}\n\n"
        f"=== LIVE WEB RESEARCH (Tavily — Business narrative) ===\n"
        f"{ctx['web_research']}\n\n"
        "Using ONLY the research above, write the business overview."
    )
    return {
        "business_overview": _run(
            BUSINESS_OVERVIEW_SYSTEM_PROMPT,
            user_prompt,
            model=SONNET_MODEL,
        )
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Data Gatherer — SEC statements + narrative; Opus tier
# ─────────────────────────────────────────────────────────────────────────────

DATA_GATHERER_SYSTEM_PROMPT = """\
You are a forensic financial data analyst preparing the quantitative foundation
for an investment research team.

You will be given:
  (1) Parsed SEC EDGAR XBRL company facts — income statement, balance sheet,
      and cash flow statement for the most recent and prior fiscal year and
      quarter (each line has value/end/fy/fp/form or value=null with a note).
  (2) A live market snapshot (price + market cap only — NO pre-baked ratios).
  (3) Tavily web research for narrative context XBRL cannot provide: earnings
      call takeaways, analyst commentary, guidance changes, litigation/
      regulatory items, MD&A themes.

Treat the SEC statement numbers as the source of truth for financials. Do NOT
invent numbers unsupported by the provided data. If a line is null, say so.

Your job:
- Review and lightly annotate the three statements. You may nest an
  "adjusted" / "normalized" object under a period when one-time items are
  clearly identifiable from the narrative (tax hits, impairments, legal
  settlements, divestiture gains). Show headline vs. adjusted with the
  reconciling items listed. Never silently overwrite a GAAP line.
- Compute derived metrics that agents will need (e.g. gross/operating/net
  margins, YoY revenue growth, FCF if not already present) ONLY when the
  inputs exist; put them under a "derived" key per period.
- Summarize SEC filings / narrative into sec_filing_summary (risk factors,
  MD&A, segment trends, guidance, litigation).
- Write a short macro_context grounded in the search hits.

Return JSON with exactly these keys:
  "income_statement": the statement dict (pass through structure; enrich with
    adjusted/derived as needed; include "live_market" key with the price snapshot),
  "balance_sheet": same pattern,
  "cash_flow_statement": same pattern,
  "sec_filing_summary": prose string,
  "macro_context": prose string.

If statements_incomplete is true, still produce the best JSON you can from
Tavily + live price, set each statement's "incomplete": true, and explain the
gap in sec_filing_summary. Do not crash into empty silence.
"""


def data_gatherer_node(state: ResearchState) -> dict:
    """Fetch SEC statements + narrative, then normalize via Opus.

    Populates: income_statement, balance_sheet, cash_flow_statement,
    sec_filing_summary, macro_context.
    """
    live = gather_live_research_context(
        ticker=state.get("ticker"),
        sector=state["sector"],
        user_query=state["user_query"],
    )

    user_prompt = (
        f"Mode: {state['mode']}\n"
        f"Sector: {state['sector']}\n"
        f"Ticker: {state.get('ticker') or 'N/A'}\n"
        f"Entity: {live.get('entity_name') or 'n/a'}\n"
        f"CIK: {live.get('cik') or 'n/a'}\n"
        f"User request: {state['user_query']}\n"
        f"Live data gathered at (UTC): {live['gathered_at_utc']}\n"
        f"statements_incomplete: {live['statements_incomplete']}\n"
        f"statements_error: {live.get('statements_error')}\n"
        f"Search queries run: {json.dumps(live['queries_run'])}\n\n"
        f"{_json_block('INCOME STATEMENT (SEC XBRL)', live['income_statement'])}\n\n"
        f"{_json_block('BALANCE SHEET (SEC XBRL)', live['balance_sheet'])}\n\n"
        f"{_json_block('CASH FLOW STATEMENT (SEC XBRL)', live['cash_flow_statement'])}\n\n"
        f"{_json_block('LIVE MARKET (price only)', live['live_market'])}\n\n"
        f"=== NARRATIVE WEB RESEARCH (Tavily) ===\n{live['web_research']}\n\n"
        "Using ONLY the data above, produce the requested JSON."
    )
    raw = _run(
        DATA_GATHERER_SYSTEM_PROMPT,
        user_prompt,
        model=OPUS_MODEL,
        max_tokens=MAX_TOKENS_OPUS,
    )

    parsed = _parse_json_blob(raw)

    def _stmt(key: str) -> dict:
        base = live.get(key) or {}
        if parsed and isinstance(parsed.get(key), dict):
            out = parsed[key]
        else:
            out = dict(base) if isinstance(base, dict) else {}
        # Always attach live market under a clean key (not a _debug field).
        if isinstance(out, dict) and "live_market" not in out:
            out = {**out, "live_market": live.get("live_market") or {}}
        if live.get("statements_incomplete") and isinstance(out, dict):
            out.setdefault("incomplete", True)
            if live.get("statements_error"):
                out.setdefault("error", live["statements_error"])
        return out

    if parsed:
        sec_filing_summary = parsed.get("sec_filing_summary") or raw
        macro_context = parsed.get("macro_context") or ""
    else:
        sec_filing_summary = raw
        macro_context = ""

    if not macro_context:
        macro_context = (
            f"Live web research digest (gathered {live['gathered_at_utc']} UTC):\n"
            f"{(live.get('web_research') or '')[:4000]}"
        )

    # Audit fields stay in process memory only — not written to state prompts.
    # (Caller can inspect live dict during debugging if needed.)
    return {
        "income_statement": _stmt("income_statement"),
        "balance_sheet": _stmt("balance_sheet"),
        "cash_flow_statement": _stmt("cash_flow_statement"),
        "sec_filing_summary": sec_filing_summary,
        "macro_context": macro_context,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Bull Agent
# ─────────────────────────────────────────────────────────────────────────────

BULL_SYSTEM_PROMPT = """\
You are the bull analyst on an investment research team. Using only the LIVE
data provided (business overview + SEC financial statements + filing summary
+ macro context), write the strongest good-faith case FOR the investment.

Focus on:
- Upside the market may be underpricing: optionality, product cycles, pricing
  power, sector tailwinds — grounded in the business overview's segment/
  geography/competitive-position picture.
- Margin expansion or operating leverage visible in the income statement
  (cite specific line items and periods, e.g. "operating margin expanded from
  X% to Y% on OperatingIncomeLoss / Revenues").
- Balance-sheet or cash-flow support (liquidity, FCF, buybacks) where relevant.
- Where adjusted/normalized figures tell a better story than headline GAAP,
  and why the adjustment is legitimate.

Ground every claim in the data you were given. Cite specific statement line
items by name. Do not invent figures or pull stale training-data numbers.
If a metric is missing, say so. Be persuasive but intellectually honest —
your work will be attacked by a bear analyst reading the same data.
"""


def bull_agent_node(state: ResearchState) -> dict:
    """Write the bull thesis from gathered data. Populates: bull_thesis."""
    text = _run_with_shared_cache(
        BULL_SYSTEM_PROMPT,
        _shared_research_payload(state),
        "Write the bull thesis. Cite specific statement line items.",
        model=SONNET_MODEL,
    )
    return {"bull_thesis": text}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Bear Agent
# ─────────────────────────────────────────────────────────────────────────────

BEAR_SYSTEM_PROMPT = """\
You are the red team: the bear analyst whose job is to find every reason this
investment could fail. Using only the LIVE data provided (business overview +
SEC financial statements + filing summary + macro context), write the
strongest good-faith case AGAINST the investment.

Hunt specifically for:
- Accounting red flags visible in the statements: revenue recognition stress,
  receivables growing faster than revenue, serial "one-time" charges, GAAP vs.
  adjusted gaps.
- Debt walls and balance-sheet pressure: maturities, leverage, covenant risk,
  off-balance-sheet obligations if disclosed in the filing summary.
- Business-model risks from the overview: customer concentration, secular
  decline, competitive erosion, geography concentration.
- Cash-flow deterioration (operating CF, FCF, buybacks funded by debt).

Ground every claim in the data you were given. Cite specific statement line
items by name and period. Do not invent figures. If a metric is missing, say
so. Be ruthless but fair — a weak bear case helps no one.
"""


def bear_agent_node(state: ResearchState) -> dict:
    """Write the bear thesis from gathered data. Populates: bear_thesis."""
    text = _run_with_shared_cache(
        BEAR_SYSTEM_PROMPT,
        _shared_research_payload(state),
        "Write the bear thesis. Cite specific statement line items.",
        model=SONNET_MODEL,
    )
    return {"bear_thesis": text}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Fundamental Valuation Agent
# ─────────────────────────────────────────────────────────────────────────────

FUNDAMENTAL_VALUATION_SYSTEM_PROMPT = """\
You are a fundamental valuation analyst. Using only the LIVE data provided
(business overview + SEC statements + filing summary + macro context + live
price if present under statements), estimate intrinsic value.

STEP 1 — classify the business-model archetype BEFORE choosing a method.
State the archetype and why in ONE sentence, then run the matching method(s):

| Archetype | Signal | Right fundamental method |
|---|---|---|
| Bank / lender | Financials sector; BS dominated by loans/deposits; leverage is the model | DDM or excess-return-on-equity (book + PV of (ROE − r_e)×equity). Standard FCF DCF is INVALID — interest is operating. |
| REIT / real estate | Real estate sector; heavy PP&E; rent revenue | FFO/AFFO-based valuation (not NI); NAV with property-level cap rates. |
| Asset-heavy industrial / utility / energy | High PP&E/revenue; capital-intensive | DCF with normalized mid-cycle margins; split maintenance vs growth capex; NAV/replacement-cost sanity check. |
| Insurance | Insurance sector; float/reserves on BS | Embedded value or P/B-vs-ROE excess return (bank-like). |
| Software / SaaS | High gross margin; low PP&E; subscription | DCF OK but allow negative near-term FCF if growth-stage; rule-of-40; longer high-growth explicit period before fade. |
| Mature dividend-payer / consumer staple | Low growth; stable payout; low capex | DDM or steady-state FCF DCF; note if they diverge and why. |
| Cyclical / commodity producer | Margins swing with commodity/macro cycle | Normalize earnings across a full cycle; DCF or EPV off normalized base — do not extrapolate peak/trough. |
| Pre-profit / early-stage growth | Negative/near-zero NI; high revenue growth | Scenario path-to-profitability DCF with unit economics; avoid false-precision point estimates. |

Then:
- Build the chosen model from the company's own statement history (FCF, ROE,
  growth rates, etc.). Show explicit assumptions (discount rate / cost of
  equity, growth/fade path, projection period).
- Cross-check with a second simpler method where reasonable (e.g. EPV beside DCF).
- State a fair-value estimate (or range), confidence level, and the key swing
  assumption that would most change the estimate.
- This is INTRINSIC value — independent of what peers currently trade at.
  Do not invent numbers missing from the packet; mark gaps explicitly.
"""


def fundamental_valuation_node(state: ResearchState) -> dict:
    """Intrinsic valuation by archetype. Populates: fundamental_valuation."""
    text = _run_with_shared_cache(
        FUNDAMENTAL_VALUATION_SYSTEM_PROMPT,
        _shared_research_payload(state),
        "Classify the archetype, then produce the fundamental valuation write-up.",
        model=SONNET_MODEL,
    )
    return {"fundamental_valuation": text}


# ─────────────────────────────────────────────────────────────────────────────
# 5. Relative Valuation Agent
# ─────────────────────────────────────────────────────────────────────────────

RELATIVE_VALUATION_SYSTEM_PROMPT = """\
You are a relative valuation analyst. Using the LIVE company data provided
plus any peer multiples supplied in the user message, assess whether the
stock is cheap/fair/rich *relative to peers and its own history*.

STEP 1 — classify the business-model archetype BEFORE choosing multiples.
State the archetype and multiple(s) selected and why in ONE sentence:

| Archetype | Right relative multiple(s) | Why |
|---|---|---|
| Bank / lender | P/B vs ROE (or P/TBV), P/E | EV/EBITDA is meaningless — debt is inventory. |
| REIT / real estate | P/FFO or P/AFFO, not P/E | NI distorted by heavy D&A. |
| Asset-heavy industrial / utility | EV/EBITDA, EV/Invested Capital | Normalizes capital structure & D&A policy. |
| Insurance | P/B vs ROE | Book value and ROE matter more than earnings multiples. |
| Software / SaaS | EV/Revenue or EV/ARR (if unprofitable); EV/EBITDA if mature | P/E useless if reinvestment drives near-zero NI. |
| Mature dividend-payer / consumer staple | P/E, EV/EBITDA, dividend yield vs peers | Standard multiples work. |
| Cyclical / commodity producer | EV/EBITDA on mid-cycle / normalized earnings | Trailing P/E distorted at peaks/troughs. |
| Pre-profit / early-stage growth | EV/Revenue, EV/Gross Profit | No earnings to multiple; growth-adjust where possible. |

Then:
- Use the subject company's live price / market cap / shares and statement
  data to compute or infer its current trading multiple(s).
- Compare to 2–4 named direct competitors that share the SAME archetype.
  Comping across archetypes (e.g. bank vs software EV/EBITDA) is a hard
  error — if peer data is mixed, flag it explicitly rather than averaging.
- Compare to the stock's own historical multiple range if available.
- Conclude cheap / fair / rich relative to peers and history.
- Explicitly state this says NOTHING about intrinsic value (that is the
  fundamental agent's job).
- Ground claims in provided data; do not invent peer multiples from memory
  when they are absent — say the data is missing.
"""


def relative_valuation_node(state: ResearchState) -> dict:
    """Comps / multiples valuation. Populates: relative_valuation.

    May run a focused Tavily peer search — the only analysis node allowed
    independent search, because peer multiples are not in the gatherer packet.
    """
    ticker = state.get("ticker") or ""
    sector = state["sector"]
    peer_research = ""
    if ticker:
        peer_research = multi_search(
            [
                f"{ticker} valuation multiples peers competitors {sector}",
                f"{ticker} vs peers EV/EBITDA P/E P/B P/S FFO trading multiples",
            ],
            max_results=5,
            topic="finance",
        )

    shared = _shared_research_payload(state)
    if peer_research:
        shared = (
            shared
            + "\n\n=== PEER / MULTIPLES WEB RESEARCH (Tavily) ===\n"
            + peer_research
        )

    text = _run_with_shared_cache(
        RELATIVE_VALUATION_SYSTEM_PROMPT,
        shared,
        "Classify the archetype, then produce the relative valuation write-up.",
        model=SONNET_MODEL,
    )
    return {"relative_valuation": text}


# ─────────────────────────────────────────────────────────────────────────────
# 6. Synthesis — Opus tier; final deliverable
# ─────────────────────────────────────────────────────────────────────────────

SYNTHESIS_SYSTEM_PROMPT = """\
You are the senior portfolio strategist and lead writer. You have received:
  (1) a descriptive business overview,
  (2) a bull thesis,
  (3) a bear thesis,
  (4) a fundamental (intrinsic) valuation, and
  (5) a relative (comps) valuation.

Your job is a single decision-ready investment memo.

Structure (in this order):
1. BUSINESS OVERVIEW — open with 2–4 concise paragraphs drawn directly from
   the business overview agent's output so a reader unfamiliar with the
   company understands what it does before any argument about the stock.
2. RECOMMENDATION — take an explicit stance (buy / hold / avoid or equivalent).
   No hedging that avoids a position. State what evidence would change it.
3. KEY DEBATE POINTS — weigh bull vs bear against the valuation picture, not
   just against each other. Where does the bear case land a blow? Where does
   the bull case survive contact?
4. VALUATION RECONCILIATION — explicitly reconcile disagreement between
   fundamental and relative calls (e.g. "DCF says overvalued, but cheap vs
   peers — which matters more here and why").
5. RISKS AND MONITORING TRIGGERS — what to watch next.

Rules:
- Build the stance strictly from the data assembled upstream. No outside
  numbers from training memory.
- Do not split the difference reflexively — take a view.
- Strip any claim none of the upstream agents supported with evidence.
"""


def synthesis_node(state: ResearchState) -> dict:
    """Synthesize overview + debate + valuations into the final memo.

    Writes only final_memo (raw judgment). Style is a separate downstream node.
    """
    user_prompt = (
        f"Target: {state.get('ticker') or state['sector']}\n"
        f"Sector: {state['sector']}\n"
        f"User request: {state['user_query']}\n\n"
        f"=== BUSINESS OVERVIEW ===\n{state.get('business_overview') or 'None provided.'}\n\n"
        f"=== BULL THESIS ===\n{state.get('bull_thesis') or 'None provided.'}\n\n"
        f"=== BEAR THESIS ===\n{state.get('bear_thesis') or 'None provided.'}\n\n"
        f"=== FUNDAMENTAL VALUATION ===\n{state.get('fundamental_valuation') or 'None provided.'}\n\n"
        f"=== RELATIVE VALUATION ===\n{state.get('relative_valuation') or 'None provided.'}\n\n"
        "Write the final investment memo in the required structure."
    )
    return {
        "final_memo": _run(
            SYNTHESIS_SYSTEM_PROMPT,
            user_prompt,
            model=OPUS_MODEL,
            max_tokens=MAX_TOKENS_OPUS,
        )
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. Style pass — Sonnet tier; voice only, no new judgment
# ─────────────────────────────────────────────────────────────────────────────

STYLE_PASS_SYSTEM_PROMPT = """\
You are a writing-style pass. You will be given a completed, fully-reasoned investment memo.
Your ONLY job is to rewrite it so the prose matches a specific voice — you are not permitted
to change any conclusion, number, stance, or substantive claim. Think of this as seasoning,
not cooking: the analysis underneath must come out exactly as it went in.

HARD CONSTRAINTS:
- Do not alter the recommendation, price target, any figure, any valuation conclusion, or the
  overall stance. If the input says "Buy" it must still say "Buy" when you're done.
- Do not add new claims, evidence, or reasoning that wasn't in the original. Do not remove
  substantive content — every conclusion and every piece of supporting evidence in the input
  must still be present in the output.
- You may reorganize section names, sentence structure, paragraph breaks, and phrasing freely
  to match the voice below. You may not reorganize which conclusions go with which evidence.

VOICE TO MATCH:

WRITING STYLE — match this voice throughout the memo. This is extracted from the writer's own
published investment memos (SpaceX, NVIDIA, two Salesforce pieces) plus broader essays — follow
it closely, it maps directly onto this exact task.

STRUCTURE — use this shape, adapting section names to fit the specific analysis:

1. Cover block up front, before any prose: Ticker / Rating (Buy-Hold-Avoid) / Price Target /
   Implied Upside / Time Horizon. State the call before justifying it.
2. "Understanding the Business" section — this is where the business overview agent's content
   goes, under this literal header or a close variant.
3. Open the analytical body with a specific comparative anomaly stated as a concrete number gap
   — a real, checkable discrepancy, not a vague framing sentence. Pattern: "X is up 7% YTD
   while [benchmark] is up 76% YTD."
4. Include a "Variant Perception" or "Where the Market Is Right" section — name it explicitly.
   State the consensus/bear view plainly and concede what it gets right before pivoting to the
   contrarian read. This is a labeled section, not just a paragraph buried in the middle.
5. A scenario table for the valuation reconciliation: Bear Case / Base Case / Bull Case, each
   with an explicit multiple and resulting price, not a vague range.
6. A risk section that addresses each risk by name in its own short paragraph, closing each one
   with a direct verdict on whether it's a near-term threat or a longer-horizon concern.
7. Close with a binary framing sentence — "Either X or Y. Very little middle ground." — then
   land the conditional recommendation immediately after it (see CLOSING below).

BODY:
- Short, declarative sentences. Starting a sentence with "And" or "But" is fine and used
  deliberately as a rhythm device.
- Land data immediately after the claim it supports, with no hedging qualifiers in between —
  "revenue grew 40% year over year," not "it's worth noting that revenue appears to have grown
  by approximately 40%."
- Open a section by knocking down the naive read before giving the real one when relevant:
  "Most people think X. They're not." / "Everyone talks about X like it's about Y. It isn't."
  Use this especially when correcting a common misconception the market/bear case holds.
- When a metric or ratio is introduced as evidence (PEG, EV/EBITDA, whatever the fundamental/
  relative valuation agents used), briefly teach what it means in one plain sentence before
  using it — don't assume the reader already knows.
- Close each major section with a short, standalone verdict sentence that compresses that
  section's takeaway. Example: "This is strictly a price gap, not a growth one." One line, no
  hedging.
- Use a recurring metaphor or analogy to make unfamiliar mechanics concrete, and return to it
  more than once rather than using it only where it's first introduced — e.g. "railroad
  economics" reappearing later in the same piece to reinforce the point.
- Use first-person conviction markers sparingly but directly — "I think," "I would recommend"
  — rather than passive hedged phrasing.
- If there's a real limitation or gap in the analysis, admit it once, briefly, in a single
  clause — then keep going with the argument anyway. Don't dwell on caveats.

CLOSING:
- Land a binary framing sentence just before the final recommendation — "This is either the
  most important company of the next 50 years or the most expensive lesson in execution risk
  ever written. There is very little middle ground." Sets up stakes before the ask.
- Then end with a conditional decision framework handed to the reader, not just a flat verdict.
  Pattern: "If you believe X, I would not buy. If you think Y, I would buy, because on a
  growth-adjusted basis it screens cheaply." This ties the recommendation explicitly to the
  variant view that would flip it.
- No corporate hedge-language, no exclamation points, no forced enthusiasm, no "in conclusion"
  or "it is worth noting that" transitions. Say the thing directly.
- Plain, phrase-based section headers (e.g. "The Lag Versus Peers: A Valuation Opportunity,"
  "The Asymmetry," "Understanding the Business," "Variant Perception"), no nested subheadings.
  Short paragraphs, 2-4 sentences typical.

Rewrite the memo now, section by section, preserving every substantive claim while adjusting
only how it's said.
"""


def style_pass_node(state: ResearchState) -> dict:
    """Voice rewrite of final_memo → styled_memo. No new judgment.

    Model: Sonnet. Reads only final_memo; leaves final_memo untouched.
    """
    raw = state.get("final_memo") or ""
    if not raw.strip():
        return {"styled_memo": ""}

    user_prompt = (
        f"Target: {state.get('ticker') or state['sector']}\n"
        f"Sector: {state['sector']}\n\n"
        f"=== FINAL MEMO (do not change conclusions or numbers) ===\n{raw}\n\n"
        "Rewrite for voice only. Preserve every substantive claim."
    )
    return {
        "styled_memo": _run(
            STYLE_PASS_SYSTEM_PROMPT,
            user_prompt,
            model=SONNET_MODEL,
            max_tokens=MAX_TOKENS_OPUS,  # full memo rewrite can be long
        )
    }
