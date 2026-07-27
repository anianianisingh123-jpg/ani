"""Agent nodes for the LangGraph Multi-Agent Sector Research System.

Each node is a plain function that takes the shared ResearchState and
returns a partial state update (a dict containing only the keys it
produced). LangGraph merges these updates into the state as the graph runs.

Deep-dive fan-out (wired in main.py):

    entry ──┬─> data_gatherer ──────────────┐
            ├─> business_overview ──────────┤
            ├─> macro_regime ───────────────┼─> bull / bear / fundamental / relative
            └─> management_track_record ─┐  │
                                         └─> capital_allocation ─┘
              → synthesis → qc → style_pass → qc_style_check → docx_export
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from .cost import finalize_run_cost, record_llm_call
from .metrics import (
    CANONICAL_METRICS_SYSTEM_RULE,
    compute_canonical_metrics,
    format_metrics_for_prompt,
)
from .routing import agents_for_query_type, synthesis_mode_for_query_type
from .state import ResearchState
from .tools import (
    clip_search_digest,
    gather_business_overview_context,
    gather_live_research_context,
    gather_macro_regime_context,
    gather_management_track_record_context,
    multi_search,
)
from .validate import format_validation_for_prompt, validate_inputs
from .valuation_engine import (
    compute_dcf_from_state,
    fetch_peer_multiples,
    format_comps_for_prompt,
    format_dcf_for_prompt,
)


def _agent_enabled(state: ResearchState, key: str) -> bool:
    """Phase 4: skip nodes not needed for this query_type."""
    qt = state.get("query_type") or "full_underwrite"
    return bool(agents_for_query_type(str(qt)).get(key, True))

# ── Model tiering ────────────────────────────────────────────────────────────
# Opus: highest-stakes reasoning (data foundation + final deliverable).
# Sonnet: bounded analytical writing over already-clean data.
# NOTE: CLAUDE.md historically listed Haiku for workers; that was leftover
# from an earlier compliance pass. Current architecture intentionally keeps
# Sonnet/Opus here — do not silently downgrade without an explicit decision.
OPUS_MODEL = "claude-opus-5"
SONNET_MODEL = "claude-sonnet-5"

MAX_TOKENS_OPUS = 8000
MAX_TOKENS_SONNET = 6000
# Full investment memos need headroom; analysis retries use this too.
MAX_TOKENS_MEMO = 16000
# data_gatherer returns a large JSON object (3 statements + prose). 8k Opus
# max_tokens truncates mid-JSON; that silently corrupts sec_filing_summary.
# 16k was still insufficient on NVDA (full annotated statement dump); 32k
# plus a compact-output prompt + prose-only retry is the safety stack.
MAX_TOKENS_GATHERER = 32000
# Retry budget when first pass returns empty / max_tokens-truncated text.
MAX_TOKENS_RETRY = 12000
# Minimum usable prose length — below this we treat the call as failed.
MIN_USEFUL_CHARS = 200

# Shared system prefix for bull / bear / fundamental / relative.
# Must be byte-identical across those four calls so Anthropic's prefix cache
# can hit on the shared research packet that follows.
SHARED_ANALYSIS_SYSTEM_PROMPT = f"""\
You are an analytical writer on an investment research team. You will receive a
shared company research packet and a role-specific lens instruction for this
call only. Follow the lens instruction. Use only the packet (and any engine
blocks attached after it). Do not invent figures or pull stale training-data
numbers. If a metric is missing, say so.

{CANONICAL_METRICS_SYSTEM_RULE}
"""


def _llm(
    model: str = SONNET_MODEL,
    max_tokens: Optional[int] = None,
    *,
    disable_thinking: bool = True,
) -> ChatAnthropic:
    """Build a chat model. ChatAnthropic reads ANTHROPIC_API_KEY from the env.

    Thinking is disabled by default. Claude Sonnet/Opus adaptive thinking can
    consume the entire max_tokens budget as thinking tokens and return zero
    visible text (the NVDA DCF/comps failure mode).
    """
    if max_tokens is None:
        max_tokens = MAX_TOKENS_OPUS if model == OPUS_MODEL else MAX_TOKENS_SONNET
    kwargs: Dict[str, Any] = {"model": model, "max_tokens": max_tokens}
    if disable_thinking:
        kwargs["thinking"] = {"type": "disabled"}
    return ChatAnthropic(**kwargs)


def _message_text(response: Any) -> str:
    """Extract plain text from a LangChain / Anthropic AIMessage.

    Claude models with extended thinking (or tool use) return `content` as a
    *list* of blocks, e.g.::

        [
          {"type": "thinking", "thinking": "...", "signature": "..."},
          {"type": "text", "text": "# NVIDIA ..."},
        ]

    Calling ``str(response.content)`` dumps the raw list (including huge
    thinking signatures) into final_memo / styled_memo — which is exactly what
    broke the NVDA docx export. Always pull only the text blocks.
    """
    content = getattr(response, "content", response)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict):
                # Some SDKs return typed objects (e.g. TextBlock)
                text = getattr(block, "text", None)
                btype = getattr(block, "type", None)
                if text and (btype in (None, "text") or not btype):
                    parts.append(str(text))
                continue
            btype = block.get("type")
            # Prefer explicit text blocks; skip thinking / tool_use / redacted.
            if btype == "text" and block.get("text"):
                parts.append(str(block["text"]))
            elif btype is None and block.get("text"):
                parts.append(str(block["text"]))
        return "\n".join(parts).strip()
    return str(content)


def _usage_bits(response: Any) -> dict[str, Any]:
    """Pull stop_reason / token counts from an AIMessage for logging."""
    md = getattr(response, "response_metadata", None) or {}
    usage = md.get("usage") or {}
    details = usage.get("output_tokens_details") or {}
    um = getattr(response, "usage_metadata", None) or {}
    return {
        "model": md.get("model") or md.get("model_name"),
        "stop_reason": md.get("stop_reason"),
        "input_tokens": usage.get("input_tokens") or um.get("input_tokens"),
        "output_tokens": usage.get("output_tokens") or um.get("output_tokens"),
        "thinking_tokens": details.get("thinking_tokens") or 0,
        "cache_read": usage.get("cache_read_input_tokens") or 0,
        "cache_create": usage.get("cache_creation_input_tokens") or 0,
    }


def _log_llm(label: str, bits: dict[str, Any], text_len: int, *, attempt: int = 1) -> None:
    print(
        f"[llm:{label}] attempt={attempt} model={bits.get('model')} "
        f"stop={bits.get('stop_reason')} "
        f"in={bits.get('input_tokens')} out={bits.get('output_tokens')} "
        f"think={bits.get('thinking_tokens')} "
        f"cache_r={bits.get('cache_read')} cache_w={bits.get('cache_create')} "
        f"text_chars={text_len}",
        flush=True,
    )


def _is_weak_output(text: str, stop_reason: Optional[str]) -> bool:
    """True if we should retry: empty, tiny, or hard-truncated mid-memo."""
    if not text or not text.strip():
        return True
    if len(text.strip()) < MIN_USEFUL_CHARS:
        return True
    # max_tokens with very short text almost always means thinking ate the budget
    # (or output was cut before any useful prose).
    if stop_reason == "max_tokens" and len(text.strip()) < 1500:
        return True
    return False


def _invoke(
    messages: list,
    *,
    model: str,
    max_tokens: Optional[int],
    disable_thinking: bool,
    label: str,
    attempt: int,
) -> tuple[str, dict[str, Any]]:
    t0 = time.monotonic()
    response = _llm(
        model, max_tokens=max_tokens, disable_thinking=disable_thinking
    ).invoke(messages)
    duration_s = time.monotonic() - t0
    text = _message_text(response)
    bits = _usage_bits(response)
    # Prefer the requested model slug when response metadata is empty/odd.
    used_model = bits.get("model") or model
    bits["model"] = used_model
    _log_llm(label, bits, len(text), attempt=attempt)
    record_llm_call(
        node=label,
        model=used_model,
        input_tokens=int(bits.get("input_tokens") or 0),
        output_tokens=int(bits.get("output_tokens") or 0),
        cache_create=int(bits.get("cache_create") or 0),
        cache_read=int(bits.get("cache_read") or 0),
        thinking_tokens=int(bits.get("thinking_tokens") or 0),
        stop_reason=bits.get("stop_reason"),
        duration_s=duration_s,
        attempt=attempt,
        text_chars=len(text),
    )
    return text, bits


def _run(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str = SONNET_MODEL,
    max_tokens: Optional[int] = None,
    label: str = "run",
    disable_thinking: bool = True,
    retry_on_empty: bool = True,
) -> str:
    """One system + user round trip, returning the text response.

    Retries once with a higher token budget if the first pass is empty or
    clearly truncated (P0 empty-output gate).
    """
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    text, bits = _invoke(
        messages,
        model=model,
        max_tokens=max_tokens,
        disable_thinking=disable_thinking,
        label=label,
        attempt=1,
    )
    if retry_on_empty and _is_weak_output(text, bits.get("stop_reason")):
        print(
            f"[llm:{label}] weak output — retrying with max_tokens={MAX_TOKENS_RETRY}, "
            f"thinking disabled",
            flush=True,
        )
        text2, bits2 = _invoke(
            messages,
            model=model,
            max_tokens=MAX_TOKENS_RETRY,
            disable_thinking=True,
            label=label,
            attempt=2,
        )
        if not _is_weak_output(text2, bits2.get("stop_reason")) or len(text2) > len(text):
            return text2
    return text


def _run_with_shared_cache(
    shared_data_block: str,
    role_instruction: str,
    *,
    model: str = SONNET_MODEL,
    max_tokens: Optional[int] = None,
    label: str = "cached",
    disable_thinking: bool = True,
    retry_on_empty: bool = True,
    extra_uncached: Optional[list[str]] = None,
) -> str:
    """Round trip with Anthropic prompt caching on the shared research packet.

    Anthropic's cache is a *prefix* cache: tools → system → messages, and the
    entire prefix through the cache breakpoint must match byte-for-byte.
    Therefore:
      - system prompt is SHARED_ANALYSIS_SYSTEM_PROMPT (identical for all four)
      - shared_data_block is the cache breakpoint (identical research packet)
      - role_instruction + optional extra_uncached (DCF / comps / peer color)
        sit *after* the breakpoint so per-agent content never busts the cache
    """
    human_blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": shared_data_block,
            "cache_control": {"type": "ephemeral"},
        },
    ]
    for block in extra_uncached or []:
        if block and str(block).strip():
            human_blocks.append({"type": "text", "text": str(block)})
    human_blocks.append({"type": "text", "text": role_instruction})

    messages = [
        SystemMessage(content=SHARED_ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=human_blocks),
    ]
    text, bits = _invoke(
        messages,
        model=model,
        max_tokens=max_tokens,
        disable_thinking=disable_thinking,
        label=label,
        attempt=1,
    )
    if retry_on_empty and _is_weak_output(text, bits.get("stop_reason")):
        print(
            f"[llm:{label}] weak output — retrying with max_tokens={MAX_TOKENS_RETRY}, "
            f"thinking disabled",
            flush=True,
        )
        text2, bits2 = _invoke(
            messages,
            model=model,
            max_tokens=MAX_TOKENS_RETRY,
            disable_thinking=True,
            label=label,
            attempt=2,
        )
        if not _is_weak_output(text2, bits2.get("stop_reason")) or len(text2) > len(text):
            return text2
    return text


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
    """Format a labeled block for prompts.

    Plain strings pass through unescaped (json.dumps would quote them and turn
    newlines into literal \\n, degrading multi-paragraph prose for every
    downstream agent). Dicts / lists / other types still go through json.dumps.
    """
    if isinstance(payload, str):
        return f"=== {label} ===\n{payload}"
    return f"=== {label} ===\n{json.dumps(payload, indent=2, default=str)}"


def _shared_research_payload(state: ResearchState) -> str:
    """Shared data block for the four parallel analysis agents.

    Intentionally excludes debug/audit fields (_live_*, queries, timestamps)
    so they are not re-serialized into every downstream prompt.
    Canonical metrics headlines come first so the contract is hard to miss.
    """
    return "\n\n".join(
        [
            f"Target: {state.get('ticker') or state['sector']}",
            f"Sector: {state['sector']}",
            f"User request: {state['user_query']}",
            f"Query type: {state.get('query_type') or 'full_underwrite'}",
            format_metrics_for_prompt(state.get("canonical_metrics")),
            format_validation_for_prompt(state.get("validation_report")),
            _json_block("BUSINESS OVERVIEW", state.get("business_overview") or "Not provided."),
            _json_block("INCOME STATEMENT", state.get("income_statement") or {}),
            _json_block("BALANCE SHEET", state.get("balance_sheet") or {}),
            _json_block("CASH FLOW STATEMENT", state.get("cash_flow_statement") or {}),
            _json_block("SEC FILING SUMMARY", state.get("sec_filing_summary") or "Not provided."),
            _json_block("MACRO CONTEXT", state.get("macro_context") or "Not provided."),
            _json_block(
                "MACRO REGIME ASSESSMENT",
                state.get("macro_regime_assessment") or "Not provided.",
            ),
            _json_block(
                "MANAGEMENT ASSESSMENT",
                state.get("management_assessment") or "Not provided.",
            ),
            _json_block(
                "CAPITAL ALLOCATION ASSESSMENT",
                state.get("capital_allocation_assessment") or "Not provided.",
            ),
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
    if not _agent_enabled(state, "business_overview"):
        print("[business_overview] skipped (query_type routing)", flush=True)
        return {"business_overview": ""}
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
            label="business_overview",
        )
    }


# ─────────────────────────────────────────────────────────────────────────────
# 0b. Macro / Regime — cycle positioning; parallel with overview + gatherer
# ─────────────────────────────────────────────────────────────────────────────

MACRO_REGIME_SYSTEM_PROMPT = """\
You are the macro and cycle-positioning analyst. Your job is to assess whether the current
macro and cycle backdrop is a tailwind, headwind, or neutral for this specific company —
using a defined analytical framework, not generic commentary.

FRAMEWORK — apply these three lenses in order:

1. DEBT CYCLE POSITIONING (primary lens). Using retrieved current data on rates, inflation,
   government debt levels, and central bank posture, assess where the relevant economy sits in
   the short-term debt cycle (expansion / late-expansion / contraction / early-recovery) and,
   where evidence supports it, the long-term debt cycle (early / mid / late-stage deleveraging
   dynamics). Ground this in actual current data — current rate levels, current inflation
   prints, current fiscal deficit figures — not in a general theory asserted without evidence.

2. REFLEXIVITY CHECK (secondary lens). Ask whether there is a self-reinforcing loop currently
   operating for or against this name or sector — e.g. rising asset prices enabling more
   borrowing/investment that further supports prices, or the reverse. State explicitly if no
   clear reflexive loop is identifiable rather than manufacturing one.

3. SECTOR-SPECIFIC CYCLE POSITION (tertiary lens). Separate from the broad macro cycle, assess
   where THIS sector specifically sits in its own cycle (e.g. a capex buildout cycle, an
   inventory cycle, a regulatory cycle) — a sector can be a bright spot in a weak macro
   environment or vice versa, and the two should not be conflated.

CRITICAL DISCIPLINE — calibrate confidence to actual evidentiary strength:
- If you draw a historical analogy (e.g. comparing current conditions to a prior cycle,
  a prior policy era, a prior geopolitical event), you MUST state explicitly: (a) what the
  parallel is, (b) what the actual causal mechanism connecting then to now is claimed to be,
  and (c) at least one way the current situation differs from the historical analog that could
  break the parallel. Never assert a historical analogy as settled fact. A compelling analogy
  is a hypothesis, not a proof — treat it as such in your own language ("this rhymes with X,
  though Y is a real disanalogy" rather than "this is exactly what happened in X").
- Distinguish clearly between what is directly evidenced in the retrieved data (cite it) and
  what is your own interpretive judgment (label it as such, e.g. "my read is..." rather than
  presenting inference as fact).
- If the retrieved data doesn't clearly support a directional call, say so. A genuine "neutral,
  mixed signals" verdict is more useful and more honest than a forced tailwind/headwind call.

OUTPUT:
- State the debt-cycle positioning verdict, the reflexivity read, and the sector-cycle read as
  three short, separate sections.
- Close with an explicit verdict: TAILWIND / HEADWIND / NEUTRAL for this specific company,
  one sentence stating the single factor that would most change this read, and a confidence
  level (high / moderate / low) tied to how much of the above was directly evidenced versus
  inferred.

Ground every claim in the data you retrieved. Do not invent rate levels, inflation figures, or
fiscal data — if you cannot find current figures, say so explicitly rather than estimating.
"""


def macro_regime_node(state: ResearchState) -> dict:
    """Assess macro/cycle positioning for this company.

    Populates: macro_regime_assessment.
    Independent Tavily research — runs in parallel with data_gatherer and
    business_overview from the deep-dive entry point.
    """
    if not _agent_enabled(state, "macro_regime"):
        print("[macro_regime] skipped (query_type routing)", flush=True)
        return {"macro_regime_assessment": ""}
    ctx = gather_macro_regime_context(
        ticker=state.get("ticker"),
        sector=state["sector"],
        user_query=state["user_query"],
    )
    user_prompt = (
        f"Ticker: {state.get('ticker') or 'N/A'}\n"
        f"Sector: {state['sector']}\n"
        f"User request: {state['user_query']}\n"
        f"Research gathered at (UTC): {ctx['gathered_at_utc']}\n"
        f"Search queries run: {json.dumps(ctx['queries_run'])}\n\n"
        f"=== LIVE WEB RESEARCH (Tavily — Macro / cycle) ===\n"
        f"{ctx['web_research']}\n\n"
        "Using ONLY the research above, apply the three-lens framework and "
        "produce the macro/regime assessment. If a rate, inflation, debt, or "
        "fiscal figure is not in the research, say so — do not invent it."
    )
    return {
        "macro_regime_assessment": _run(
            MACRO_REGIME_SYSTEM_PROMPT,
            user_prompt,
            model=SONNET_MODEL,
            label="macro_regime",
        )
    }


# ─────────────────────────────────────────────────────────────────────────────
# 0c. Management Track Record — people/leadership; parallel at entry
# ─────────────────────────────────────────────────────────────────────────────

MANAGEMENT_TRACK_RECORD_SYSTEM_PROMPT = """\
You are the management and leadership analyst. Your job is to research and assess the
company's key executives — who they are, their track record, and how they have actually run
this business — using only what you can find in retrieved sources. This is a factual and
track-record assessment, not a capital allocation analysis (that is a separate agent's job) —
stay focused on people and leadership decisions, not cash deployment.

Cover, grounded only in what you retrieve:

1. WHO THEY ARE: CEO and other key executives (CFO, and any other named leader relevant to the
   thesis). Tenure at this company. Prior roles and companies, and what happened at those
   companies under their leadership if it's findable and relevant.

2. TRACK RECORD AT THIS COMPANY: What has changed under current leadership — strategic pivots,
   major decisions (successful or not), how the company has navigated prior hard periods
   (downturns, competitive threats, crises) if evidence exists. Be specific and dated where
   possible, not just characterological ("has navigated X well").

3. INSIDER ACTIVITY: Insider buying or selling patterns if disclosed/findable — meaningful
   insider buying is a stronger signal than routine, scheduled selling (e.g. 10b5-1 plans);
   note which type you're seeing if you can tell the difference from available data.

4. COMPENSATION AND ALIGNMENT: How executives are compensated — if the structure is disclosed
   or reported (equity-heavy vs. cash-heavy, performance-linked vs. not) — and whether that
   structure appears to align incentives with shareholders or with something else (revenue
   growth regardless of profitability, short-term stock price, etc.).

5. GOVERNANCE AND SUCCESSION: Board composition/independence if findable, any recent leadership
   turnover, and succession risk — is this a single-founder-dependent story or a deep bench.

6. RED FLAGS: Any disclosed governance controversies, activist investor involvement, restated
   earnings, executive departures under unclear circumstances, or other findable concerns.
   If none are found, say so explicitly rather than leaving this section vague.

DISCIPLINE:
- Distinguish clearly between disclosed fact (cite it) and your own read/inference (label it
  as such).
- If you cannot find reliable information on a section above, say so explicitly — do not pad
  with generic characterizations ("strong leadership team") unsupported by anything retrieved.
- Do not let a well-known name or reputation substitute for actual evidence in the retrieved
  data. A famous founder is not automatically a well-governed company.

OUTPUT: organized under the six headers above, prose under each, concluding with a one-line
summary verdict on overall leadership quality/risk and your confidence level (high / moderate/
low) based on how much of the above was actually findable versus inferred.
"""


def management_track_record_node(state: ResearchState) -> dict:
    """Assess key executives' track record and leadership quality.

    Populates: management_assessment.
    Independent Tavily research — runs in parallel with data_gatherer,
    business_overview, and macro_regime from the deep-dive entry point.
    Does not analyze capital allocation (separate node).
    """
    if not _agent_enabled(state, "management_track_record"):
        print("[management_track_record] skipped (query_type routing)", flush=True)
        return {"management_assessment": ""}
    ctx = gather_management_track_record_context(
        ticker=state.get("ticker"),
        sector=state["sector"],
        user_query=state["user_query"],
    )
    user_prompt = (
        f"Ticker: {state.get('ticker') or 'N/A'}\n"
        f"Sector: {state['sector']}\n"
        f"User request: {state['user_query']}\n"
        f"Research gathered at (UTC): {ctx['gathered_at_utc']}\n"
        f"Search queries run: {json.dumps(ctx['queries_run'])}\n\n"
        f"=== LIVE WEB RESEARCH (Tavily — Management / leadership) ===\n"
        f"{ctx['web_research']}\n\n"
        "Using ONLY the research above, write the management track-record "
        "assessment under the six required headers. If a section has no "
        "reliable data, say so — do not invent biographies or insider stats. "
        "Do not analyze capital allocation (buybacks, dividends, M&A spend)."
    )
    return {
        "management_assessment": _run(
            MANAGEMENT_TRACK_RECORD_SYSTEM_PROMPT,
            user_prompt,
            model=SONNET_MODEL,
            label="management_track_record",
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
- Lightly annotate the three statements. Prefer COMPACT pass-through of the
  input structure. Nest "adjusted" / "normalized" under a period ONLY when
  one-time items are clearly identifiable from the narrative. Never silently
  overwrite a GAAP line. Do NOT rewrite or re-pretty-print every line with
  long commentary — token budget is limited and truncated JSON is unusable.
- Compute derived metrics agents need (gross/operating/net margins, YoY
  revenue growth, FCF if not already present) ONLY when inputs exist; put
  them under a "derived" key per period. Keep derived keys short.
- Write sec_filing_summary (prose): risk factors, MD&A, segment trends,
  guidance, litigation — this is the highest-priority field.
- Write a short macro_context grounded in the search hits.

CRITICAL OUTPUT RULES:
- Return ONE valid JSON object and nothing else (no markdown fences if you
  can avoid them; if you fence, close the fence).
- Emit keys in this order so a partial write still has the prose fields:
  sec_filing_summary, macro_context, income_statement, balance_sheet,
  cash_flow_statement.
- Statement values may be the input objects with only small enrichment.
  Do not invent new line items.

Return JSON with exactly these keys:
  "sec_filing_summary": prose string,
  "macro_context": prose string,
  "income_statement": statement dict (include "live_market" with price snapshot),
  "balance_sheet": same pattern,
  "cash_flow_statement": same pattern.

If statements_incomplete is true, still produce valid JSON from Tavily + live
price, set each statement's "incomplete": true, and explain the gap in
sec_filing_summary. Do not crash into empty silence.
"""

# Fallback when the full JSON gatherer call is truncated/unparseable: only the
# two prose fields, so downstream agents still get a real filing summary.
DATA_GATHERER_PROSE_RETRY_PROMPT = """\
You are a forensic financial data analyst. A prior JSON pass failed or was
truncated. Using ONLY the data in the user message, return a SMALL valid JSON
object with exactly these two keys (both prose strings):
  "sec_filing_summary": risk factors, MD&A, segment trends, guidance, litigation
  "macro_context": short macro context from the search hits
No statement dicts. No markdown. Valid JSON only. Keep each field under ~2500 words.
"""


def data_gatherer_node(state: ResearchState) -> dict:
    """Fetch SEC statements + narrative, then normalize via Opus.

    Populates: income_statement, balance_sheet, cash_flow_statement,
    sec_filing_summary, macro_context.
    """
    if not _agent_enabled(state, "data_gatherer"):
        print("[data_gatherer] skipped (query_type routing)", flush=True)
        return {
            "income_statement": {},
            "balance_sheet": {},
            "cash_flow_statement": {},
            "sec_filing_summary": "",
            "macro_context": "",
        }
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
        "Using ONLY the data above, produce the requested JSON. "
        "Prioritize a complete, valid JSON close over exhaustive annotations."
    )
    raw = _run(
        DATA_GATHERER_SYSTEM_PROMPT,
        user_prompt,
        model=OPUS_MODEL,
        max_tokens=MAX_TOKENS_GATHERER,
        label="data_gatherer",
    )

    parsed = _parse_json_blob(raw)
    if parsed is None:
        print(
            "[data_gatherer] WARNING: JSON parse failed — "
            "retrying prose-only pass for sec_filing_summary / macro_context",
            flush=True,
        )
        prose_raw = _run(
            DATA_GATHERER_PROSE_RETRY_PROMPT,
            user_prompt,
            model=OPUS_MODEL,
            max_tokens=MAX_TOKENS_MEMO,
            label="data_gatherer_prose_retry",
        )
        prose_parsed = _parse_json_blob(prose_raw)
        if prose_parsed:
            parsed = {
                "sec_filing_summary": prose_parsed.get("sec_filing_summary") or "",
                "macro_context": prose_parsed.get("macro_context") or "",
            }
            print(
                "[data_gatherer] prose-only retry JSON parse ok "
                f"(summary_chars={len(str(parsed.get('sec_filing_summary') or ''))})",
                flush=True,
            )
        else:
            print(
                "[data_gatherer] WARNING: prose-only retry also failed JSON parse — "
                "falling back to Tavily narrative (not raw truncated JSON)",
                flush=True,
            )

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

    if parsed and (parsed.get("sec_filing_summary") or parsed.get("macro_context")):
        sec_filing_summary = parsed.get("sec_filing_summary") or ""
        macro_context = parsed.get("macro_context") or ""
        # If primary parse had statements, log full success; else prose-only.
        has_stmts = any(
            isinstance(parsed.get(k), dict)
            for k in ("income_statement", "balance_sheet", "cash_flow_statement")
        )
        print(
            f"[data_gatherer] JSON parse ok — "
            f"sec_filing_summary_chars={len(str(sec_filing_summary))} "
            f"statements_from_model={has_stmts}",
            flush=True,
        )
    else:
        # Never dump truncated raw JSON into sec_filing_summary — it poisons
        # every downstream agent. Prefer live Tavily narrative instead.
        sec_filing_summary = (
            f"(data_gatherer JSON unparseable; Tavily narrative digest "
            f"gathered {live['gathered_at_utc']} UTC)\n"
            f"{clip_search_digest(live.get('web_research') or '', 6000)}"
        )
        macro_context = ""

    if not macro_context:
        macro_context = (
            f"Live web research digest (gathered {live['gathered_at_utc']} UTC):\n"
            f"{clip_search_digest(live.get('web_research') or '', 4000)}"
        )

    # Audit fields stay in process memory only — not written to state prompts.
    # (Caller can inspect live dict during debugging if needed.)
    return {
        "income_statement": _stmt("income_statement"),
        "balance_sheet": _stmt("balance_sheet"),
        "cash_flow_statement": _stmt("cash_flow_statement"),
        "sec_filing_summary": sec_filing_summary,
        "macro_context": macro_context,
        "cik": live.get("cik"),
        "sic": live.get("sic"),
        "extraction_archetype": live.get("extraction_archetype") or "general",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1a. Canonical metrics — Python only; after data_gatherer
# ─────────────────────────────────────────────────────────────────────────────

def metrics_compute_node(state: ResearchState) -> dict:
    """Compute CanonicalMetrics from statements + live market.

    Populates: canonical_metrics. No LLM. Must run after data_gatherer and
    before capital_allocation / analysis agents.
    """
    if not _agent_enabled(state, "metrics"):
        print("[metrics] skipped (query_type routing)", flush=True)
        return {"canonical_metrics": {}}
    cm = compute_canonical_metrics(
        income_statement=state.get("income_statement") or {},
        balance_sheet=state.get("balance_sheet") or {},
        cash_flow_statement=state.get("cash_flow_statement") or {},
        live_market=None,  # pulled from statement live_market attach if present
        ticker=state.get("ticker"),
        sector=state.get("sector"),
        sic=state.get("sic"),
    )
    summ = cm.get("summary") or {}
    # Surface the buyback and net-cash contracts that previously failed QC.
    by_id = cm.get("by_id") or {}
    for mid in (
        "buyback_dollars_per_pct_point__current_annual_vs_prior_annual",
        "net_cash_incl_st_investments__current_quarter",
        "net_cash_incl_st_investments__current_annual",
        "net_cash_ex_st_investments__current_annual",
        "trailing_pe",
        "market_cap",
    ):
        m = by_id.get(mid)
        if m and m.get("headline"):
            print(f"[metrics] {mid}: {m['headline']}", flush=True)
    print(
        f"[metrics] computed {summ.get('metric_count', 0)} records "
        f"({summ.get('applicable_with_value', 0)} applicable, "
        f"{summ.get('unavailable', 0)} unavailable) "
        f"ticker={cm.get('ticker')} archetype={cm.get('archetype')}",
        flush=True,
    )
    return {"canonical_metrics": cm}


def validation_gate_node(state: ResearchState) -> dict:
    """Phase 3: pre-narration validation after metrics, before capital/analysis."""
    if not _agent_enabled(state, "metrics") or not _agent_enabled(state, "data_gatherer"):
        report = {
            "status": "PASS",
            "checks": [],
            "warnings": [],
            "failures": [],
            "summary": "validation skipped (query_type does not use statements/metrics)",
        }
        print(f"[validation] {report['summary']}", flush=True)
        return {"validation_report": report, "validation_status": "PASS"}

    report = validate_inputs(dict(state))
    status = report.get("status") or "PASS"
    print(f"[validation] {report.get('summary')}", flush=True)
    for w in report.get("warnings") or []:
        print(f"[validation] WARN: {w}", flush=True)
    for f in report.get("failures") or []:
        print(f"[validation] FAIL: {f}", flush=True)
    if status == "FAIL":
        print(
            "[validation] HARD STOP before analysis fan-out — "
            "refusing to spend narrative tokens on broken inputs",
            flush=True,
        )
    return {
        "validation_report": report,
        "validation_status": status,
    }


def validation_halt_node(state: ResearchState) -> dict:
    """Terminal node when validation FAILs."""
    report = state.get("validation_report") or {}
    print(
        f"[validation_halt] Run ended without analysis. "
        f"status={report.get('status')!r} summary={report.get('summary')!r}",
        flush=True,
    )
    from .cost import finalize_run_cost

    return finalize_run_cost(dict(state))


# ─────────────────────────────────────────────────────────────────────────────
# 1b. Capital Allocation — numbers-driven; after metrics + management
# ─────────────────────────────────────────────────────────────────────────────

CAPITAL_ALLOCATION_SYSTEM_PROMPT = f"""\
You are the capital allocation analyst. Your job is to assess, unbiasedly and using only the
numbers provided, how well this management team has actually deployed the company's cash over
the periods available in the data. This is a numbers-driven track record assessment — not a
narrative about strategy, and not a restatement of the management agent's qualitative read.

{CANONICAL_METRICS_SYSTEM_RULE}

FRAMEWORK — there are five uses of cash. Assess the company's historical mix and quality
across each. For every load-bearing figure (buyback spend, share-count change, dollars per
percentage point, R&D %, capex %, payout, debt/equity, goodwill increment), quote the matching
canonical metrics headline — do not recompute these from raw lines:

1. REINVESTMENT IN THE CORE BUSINESS: Capex and R&D relative to revenue (use canonical
   capex_pct_revenue / rd_pct_revenue headlines). Where ROIC-like approximations require
   combining operating-income change with capex+R&D, label that combination as an approximation
   and still quote the canonical component headlines.

2. M&A: Any acquisitions visible in the cash flow statement or referenced in the filing
   summary. Use canonical goodwill_increment headlines. Assess size relative to the balance
   sheet only with canonical totals. If no evidence exists either way, say so.

3. DIVIDENDS: Use canonical dividends_paid and dividend_payout_fcf headlines when present.
   If no dividend metric, state that plainly.

4. BUYBACKS: Use the canonical buyback_spend, share_count_change_pct, and especially
   buyback_dollars_per_pct_point headlines for the single annual pair provided. Never sum
   buybacks across FY + quarter. Never invent a $/pp figure.

5. DEBT MANAGEMENT: Use canonical total_debt, debt_to_equity, and net_cash headlines
   (respect ex-ST vs incl-ST qualifiers in the headline).

SCORING: for each of the five categories, state a brief verdict — disciplined / neutral /
concerning — grounded in the specific canonical headlines that justify it. Do not give a
category a verdict if the data provided doesn't actually support one; say the data is
insufficient instead of guessing.

ALIGNMENT CHECK: cross-reference against the management_assessment's compensation-alignment
read where relevant — e.g. if buybacks are heavy but insider selling is also heavy, or if
compensation is tied to metrics that don't match where capital is actually being deployed,
flag the inconsistency explicitly.

OUTPUT: one short section per category above with its verdict, followed by an overall summary
verdict on capital allocation quality and a confidence level (high / moderate / low) based on
how complete the underlying data was. Quote canonical headlines for numbers; never estimate a
figure that is not in the canonical metrics object or the filing summary narrative.
"""


def capital_allocation_node(state: ResearchState) -> dict:
    """Score capital deployment from metrics + statements + management alignment.

    Populates: capital_allocation_assessment.
    Depends on metrics_compute (canonical metrics) and management_track_record.
    Does not re-search the web.
    """
    if not _agent_enabled(state, "capital_allocation"):
        print("[capital_allocation] skipped (query_type routing)", flush=True)
        return {"capital_allocation_assessment": ""}
    user_prompt = (
        f"Ticker: {state.get('ticker') or 'N/A'}\n"
        f"Sector: {state['sector']}\n"
        f"User request: {state['user_query']}\n\n"
        f"{format_metrics_for_prompt(state.get('canonical_metrics'))}\n\n"
        f"{_json_block('INCOME STATEMENT', state.get('income_statement') or {})}\n\n"
        f"{_json_block('BALANCE SHEET', state.get('balance_sheet') or {})}\n\n"
        f"{_json_block('CASH FLOW STATEMENT', state.get('cash_flow_statement') or {})}\n\n"
        f"{_json_block('SEC FILING SUMMARY', state.get('sec_filing_summary') or 'Not provided.')}\n\n"
        f"{_json_block('MANAGEMENT ASSESSMENT', state.get('management_assessment') or 'Not provided.')}\n\n"
        "Using ONLY the data above, apply the five-use-of-cash framework and "
        "produce the capital allocation assessment. Quote canonical metric "
        "headlines for every load-bearing number. If data is insufficient for "
        "a category, say so."
    )
    return {
        "capital_allocation_assessment": _run(
            CAPITAL_ALLOCATION_SYSTEM_PROMPT,
            user_prompt,
            model=SONNET_MODEL,
            label="capital_allocation",
        )
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Bull Agent
# ─────────────────────────────────────────────────────────────────────────────

BULL_SYSTEM_PROMPT = """\
You are the bull analyst on an investment research team. Using only the LIVE
data provided (business overview + SEC financial statements + filing summary
+ macro context + macro regime assessment + management assessment + capital
allocation assessment), write the strongest good-faith case FOR the investment.

Focus on:
- Upside the market may be underpricing: optionality, product cycles, pricing
  power, sector tailwinds — grounded in the business overview's segment/
  geography/competitive-position picture.
- Where the macro regime assessment is TAILWIND or sector-cycle supportive,
  weave that in with evidence; if it is HEADWIND or NEUTRAL, do not invent
  macro support — lean on company-specific fundamentals instead.
- Leadership and capital-allocation strengths only when evidenced in the
  management / capital-allocation assessments (do not invent "great management").
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
    if not _agent_enabled(state, "bull"):
        print("[bull] skipped (query_type routing)", flush=True)
        return {"bull_thesis": ""}
    text = _run_with_shared_cache(
        _shared_research_payload(state),
        BULL_SYSTEM_PROMPT
        + "\n\nWrite the bull thesis. Cite specific statement line items.",
        model=SONNET_MODEL,
        label="bull",
    )
    return {"bull_thesis": text}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Bear Agent
# ─────────────────────────────────────────────────────────────────────────────

BEAR_SYSTEM_PROMPT = """\
You are the red team: the bear analyst whose job is to find every reason this
investment could fail. Using only the LIVE data provided (business overview +
SEC financial statements + filing summary + macro context + macro regime
assessment + management assessment + capital allocation assessment), write the
strongest good-faith case AGAINST the investment.

Hunt specifically for:
- Accounting red flags visible in the statements: revenue recognition stress,
  receivables growing faster than revenue, serial "one-time" charges, GAAP vs.
  adjusted gaps.
- Debt walls and balance-sheet pressure: maturities, leverage, covenant risk,
  off-balance-sheet obligations if disclosed in the filing summary.
- Macro / cycle headwinds from the regime assessment (debt-cycle position,
  reflexive loops turning negative, late-sector-cycle risk) when evidenced —
  do not invent macro doom if the assessment is TAILWIND or NEUTRAL.
- Leadership, governance, insider, or succession red flags from the management
  assessment when evidenced; capital-allocation concerns (value-destructive M&A,
  dilutive buybacks, leverage drift) from the capital allocation assessment.
- Business-model risks from the overview: customer concentration, secular
  decline, competitive erosion, geography concentration.
- Cash-flow deterioration (operating CF, FCF, buybacks funded by debt).

Ground every claim in the data you were given. Cite specific statement line
items by name and period. Do not invent figures. If a metric is missing, say
so. Be ruthless but fair — a weak bear case helps no one.
"""


def bear_agent_node(state: ResearchState) -> dict:
    """Write the bear thesis from gathered data. Populates: bear_thesis."""
    if not _agent_enabled(state, "bear"):
        print("[bear] skipped (query_type routing)", flush=True)
        return {"bear_thesis": ""}
    text = _run_with_shared_cache(
        _shared_research_payload(state),
        BEAR_SYSTEM_PROMPT
        + "\n\nWrite the bear thesis. Cite specific statement line items.",
        model=SONNET_MODEL,
        label="bear",
    )
    return {"bear_thesis": text}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Fundamental Valuation Agent
# ─────────────────────────────────────────────────────────────────────────────

FUNDAMENTAL_VALUATION_SYSTEM_PROMPT = """\
You are a fundamental valuation analyst. A DETERMINISTIC Python DCF engine has
already computed the base-case intrinsic value from SEC free-cash-flow history
and sector-default WACC / terminal growth. That engine block is the source of
truth for the math — you narrate and interpret it; you do not replace its
fair-value numbers with invented ones.

Write-up structure:
1. ARCHETYPE — one sentence classifying the business model and whether FCF DCF
   is the right primary method (flag banks/REITs/insurers if DCF is a poor fit).
2. ENGINE BASE CASE — restate fair value / share, range, implied upside vs live
   price, WACC, g_high, g_terminal, and base FCF. Quote the engine figures.
3. KEY SWING ASSUMPTIONS — what would most change the estimate (growth fade,
   WACC, margin mean-reversion). Qualitative sensitivities are fine; do not
   fabricate a second full DCF with made-up cash flows.
4. EPV / CROSS-CHECK — use the engine's EPV and trailing P/E if present.
5. CONFIDENCE & GAPS — engine confidence, warnings, and any missing inputs.

This is INTRINSIC value — independent of peer multiples (that is the relative
agent's job). If the engine reported errors, explain them and stop — do not
invent a substitute model from training memory.
"""


def fundamental_valuation_node(state: ResearchState) -> dict:
    """Intrinsic valuation: Python DCF + LLM narrative. Populates: fundamental_valuation."""
    if not _agent_enabled(state, "fundamental"):
        print("[fundamental] skipped (query_type routing)", flush=True)
        return {"fundamental_valuation": ""}
    dcf = compute_dcf_from_state(state)
    dcf_block = format_dcf_for_prompt(dcf)
    print(
        f"[valuation:dcf] ticker={state.get('ticker')} "
        f"archetype={dcf.get('archetype')} method={dcf.get('method')} "
        f"fv={dcf.get('fair_value_per_share')} upside={dcf.get('implied_upside_vs_price')} "
        f"errors={dcf.get('errors')}",
        flush=True,
    )

    # DCF engine block is agent-specific — place it AFTER the cache breakpoint
    # so bull/bear/relative still share an identical cached research packet.
    text = _run_with_shared_cache(
        _shared_research_payload(state),
        FUNDAMENTAL_VALUATION_SYSTEM_PROMPT
        + "\n\nProduce the fundamental valuation write-up from the engine "
        "output and packet.",
        model=SONNET_MODEL,
        label="fundamental",
        max_tokens=MAX_TOKENS_SONNET,
        extra_uncached=[dcf_block],
    )
    # Hard fallback: never ship an empty fundamental field if the engine has numbers.
    if not (text or "").strip():
        print("[valuation:dcf] LLM empty — falling back to engine block only", flush=True)
        text = (
            "## Fundamental valuation (engine only — narrative model failed)\n\n"
            + dcf_block
        )
    return {"fundamental_valuation": text}


# ─────────────────────────────────────────────────────────────────────────────
# 5. Relative Valuation Agent
# ─────────────────────────────────────────────────────────────────────────────

RELATIVE_VALUATION_SYSTEM_PROMPT = """\
You are a relative valuation analyst. A DETERMINISTIC peer-comps table has
already been pulled from yfinance for the subject and a sector peer set.
That table is the source of truth for trading multiples — you narrate it;
you do not invent peer P/Es or EV/EBITDAs from training memory.

Write-up structure:
1. ARCHETYPE — one sentence on which multiples are appropriate and why.
2. SUBJECT MULTIPLES — restate the subject's trailing/forward P/E, EV/EBITDA,
   P/S (as available) from the comps table.
3. PEER COMPARISON — name the peers, cite peer medians, and state whether the
   stock screens cheap / fair / rich on each key multiple.
4. JUSTIFIED PREMIUM/DISCOUNT — using growth, margins, and business quality
   from the company packet (not invented peer numbers), argue whether any
   premium or discount is deserved.
5. CONCLUSION — overall cheap / fair / rich vs peers. Explicitly state this
   says NOTHING about intrinsic value (that is the fundamental agent's job).

If a multiple is n/a in the table, say so — do not fill it from memory.
"""


def relative_valuation_node(state: ResearchState) -> dict:
    """Comps / multiples: yfinance peer table + LLM narrative.

    Populates: relative_valuation. Optional Tavily narrative is secondary
    color only — multiples come from the structured comps engine.
    """
    if not _agent_enabled(state, "relative"):
        print("[relative] skipped (query_type routing)", flush=True)
        return {"relative_valuation": ""}
    ticker = state.get("ticker") or ""
    sector = state["sector"]
    arch = None
    cm = state.get("canonical_metrics") or {}
    if isinstance(cm, dict):
        arch = cm.get("archetype")

    comps: dict = {}
    comps_block = ""
    if ticker:
        comps = fetch_peer_multiples(
            ticker,
            sector=sector,
            subject_archetype=arch,
            subject_sic=state.get("sic"),
        )
        comps_block = format_comps_for_prompt(comps)
        print(
            f"[valuation:comps] ticker={ticker} archetype={comps.get('subject_archetype')} "
            f"overall={comps.get('overall_vs_peers')} "
            f"peers={comps.get('peer_list')} "
            f"excluded={len(comps.get('peer_exclusions') or [])}",
            flush=True,
        )
        if not comps.get("relative_valuation_applicable", True):
            print(
                "[valuation:comps] fewer than 2 archetype-matched peers — "
                "relative valuation not applicable",
                flush=True,
            )

    # Light narrative search (optional color) — 1 query, not 2, to save tokens.
    peer_research = ""
    if ticker:
        peer_research = multi_search(
            [f"{ticker} vs peers valuation multiples {sector} AMD competitors"],
            max_results=4,
            topic="finance",
        )

    # Comps table + peer narrative are agent-specific — after the cache breakpoint.
    extra: list[str] = []
    if comps_block:
        extra.append(comps_block)
    if peer_research:
        extra.append(
            "=== PEER NARRATIVE WEB RESEARCH (Tavily, secondary) ===\n"
            + peer_research
        )

    text = _run_with_shared_cache(
        _shared_research_payload(state),
        RELATIVE_VALUATION_SYSTEM_PROMPT
        + "\n\nProduce the relative valuation write-up from the comps table "
        "and packet.",
        model=SONNET_MODEL,
        label="relative",
        max_tokens=MAX_TOKENS_SONNET,
        extra_uncached=extra or None,
    )
    if not (text or "").strip():
        print("[valuation:comps] LLM empty — falling back to comps table only", flush=True)
        text = (
            "## Relative valuation (comps table only — narrative model failed)\n\n"
            + (comps_block or "No peer comps available.")
        )
    return {"relative_valuation": text}


# ─────────────────────────────────────────────────────────────────────────────
# 6. Synthesis — Opus tier; final deliverable
# ─────────────────────────────────────────────────────────────────────────────

SYNTHESIS_SYSTEM_PROMPT = f"""\
You are the senior portfolio strategist and lead writer. You have received:
  (1) a descriptive business overview,
  (2) a macro/regime assessment (debt cycle, reflexivity, sector cycle,
      TAILWIND / HEADWIND / NEUTRAL verdict),
  (3) a management track-record assessment (people, governance, insiders),
  (4) a capital allocation assessment (five uses of cash + alignment),
  (5) a bull thesis,
  (6) a bear thesis,
  (7) a fundamental (intrinsic) valuation, and
  (8) a relative (comps) valuation,
  (9) the CANONICAL METRICS block (Python — source of truth for figures).

{CANONICAL_METRICS_SYSTEM_RULE}
If an upstream agent states a figure that contradicts a canonical metrics headline,
prefer the canonical headline and note the discrepancy. Never invent a "corrected"
numeric range that is not itself a canonical headline.

Your job is a single decision-ready investment memo.

Structure (in this order):
1. BUSINESS OVERVIEW — open with 2–4 concise paragraphs drawn directly from
   the business overview agent's output so a reader unfamiliar with the
   company understands what it does before any argument about the stock.
2. RECOMMENDATION — take an explicit stance (buy / hold / avoid or equivalent).
   No hedging that avoids a position. State what evidence would change it.
3. MACRO / CYCLE POSITIONING — briefly state how the regime assessment (and
   its confidence) informs the stance; do not invent rates or fiscal data
   beyond what upstream agents provided.
4. MANAGEMENT & CAPITAL ALLOCATION — weigh leadership quality and capital-
   deployment discipline as independent inputs; a leadership/capital concern
   the bear surfaces should be weighed like any financial red flag.
5. KEY DEBATE POINTS — weigh bull vs bear against the valuation picture, not
   just against each other. Where does the bear case land a blow? Where does
   the bull case survive contact?
6. VALUATION RECONCILIATION — explicitly reconcile disagreement between
   fundamental and relative calls (e.g. "DCF says overvalued, but cheap vs
   peers — which matters more here and why").
7. RISKS AND MONITORING TRIGGERS — what to watch next (include the regime
   assessment's key flip-factor and any management/capital flip-factors when present).

Rules:
- Build the stance strictly from the data assembled upstream. No outside
  numbers from training memory.
- Do not split the difference reflexively — take a view.
- Strip any claim none of the upstream agents supported with evidence.
"""


def _field_status(state: ResearchState) -> dict[str, int]:
    """Char lengths of critical upstream fields for the synthesis gate log."""
    keys = (
        "business_overview",
        "macro_regime_assessment",
        "management_assessment",
        "capital_allocation_assessment",
        "bull_thesis",
        "bear_thesis",
        "fundamental_valuation",
        "relative_valuation",
    )
    return {k: len((state.get(k) or "").strip()) for k in keys}


def _build_synthesis_user_prompt(
    state: ResearchState,
    *,
    qc_correction: Optional[str] = None,
) -> str:
    """Build the synthesis user packet; optional QC report for one retry."""
    qt = state.get("query_type") or "full_underwrite"
    mode = synthesis_mode_for_query_type(str(qt))
    mode_instructions = {
        "full_memo": (
            "Write the final investment memo in the required full structure. "
            "Quote canonical metric headlines verbatim for every load-bearing figure."
        ),
        "direct_answer": (
            "QUERY MODE = specific_question. Answer the user_query directly and "
            "concisely. Do NOT force a full buy/hold memo structure. Use "
            "canonical metrics headlines when citing numbers. End with sources used."
        ),
        "business_brief": (
            "QUERY MODE = business_understanding. Produce a clear business "
            "description brief only — no valuation, no buy/sell rating."
        ),
        "valuation_note": (
            "QUERY MODE = valuation_only. Produce a valuation note reconciling "
            "fundamental and relative engines. Quote engine + canonical metrics "
            "headlines. No full multi-section investment memo required."
        ),
        "risk_memo": (
            "QUERY MODE = risk_assessment. Focus on risks, bear case, macro, and "
            "management/governance. Explicit flip-factors. No need for a full "
            "bull case if empty."
        ),
    }.get(mode, "Write the final investment memo in the required structure.")

    base = (
        f"Target: {state.get('ticker') or state['sector']}\n"
        f"Sector: {state['sector']}\n"
        f"User request: {state['user_query']}\n"
        f"Query type: {qt} | Synthesis mode: {mode}\n\n"
        f"{format_metrics_for_prompt(state.get('canonical_metrics'))}\n\n"
        f"{format_validation_for_prompt(state.get('validation_report'))}\n\n"
        "NUMBER HIERARCHY (mandatory):\n"
        "1) Company financials, growth rates, margins, net cash, buybacks, share counts, "
        "trailing P/E, market cap → quote CANONICAL METRICS headlines only.\n"
        "2) DCF / residual-income fair value → quote the valuation engine block only; "
        "do not call engine EV the same thing as market enterprise value without labeling.\n"
        "3) Peer multiples → comps table only; if comps PE disagrees with canonical trailing "
        "P/E, say so and prefer canonical for the subject company.\n"
        "4) Never say 'currently' for an annual YoY headline; keep the basis period.\n"
        "5) If validation WARNINGs list stale metrics, do not use those lines for the thesis.\n\n"
        f"=== BUSINESS OVERVIEW ===\n{state.get('business_overview') or 'None provided.'}\n\n"
        f"=== MACRO REGIME ASSESSMENT ===\n"
        f"{state.get('macro_regime_assessment') or 'None provided.'}\n\n"
        f"=== MANAGEMENT ASSESSMENT ===\n"
        f"{state.get('management_assessment') or 'None provided.'}\n\n"
        f"=== CAPITAL ALLOCATION ASSESSMENT ===\n"
        f"{state.get('capital_allocation_assessment') or 'None provided.'}\n\n"
        f"=== BULL THESIS ===\n{state.get('bull_thesis') or 'None provided.'}\n\n"
        f"=== BEAR THESIS ===\n{state.get('bear_thesis') or 'None provided.'}\n\n"
        f"=== FUNDAMENTAL VALUATION ===\n{state.get('fundamental_valuation') or 'None provided.'}\n\n"
        f"=== RELATIVE VALUATION ===\n{state.get('relative_valuation') or 'None provided.'}\n\n"
        f"{mode_instructions} "
        "If a section above says None provided or is clearly incomplete, say so "
        "explicitly — do not invent DCF, peer multiples, rate/fiscal figures, "
        "or management biography to fill the gap. "
        "If validation WARNINGs are present, disclose them in the memo."
    )
    if qc_correction and qc_correction.strip():
        base += (
            "\n\n=== QC REPORT (prior synthesis FAILED institutional review) ===\n"
            f"{qc_correction.strip()}\n\n"
            "Rewrite the memo to correct every CRITICAL and MAJOR finding above. "
            "Do not invent new numbers — only quote canonical metric headlines or "
            "upstream text. Prefer disclosing a gap over fabricating a figure. "
            "Preserve a clear recommendation once integrity is restored."
        )
    return base


def synthesis_node(state: ResearchState) -> dict:
    """Synthesize overview + regime + management + capital + debate + valuations.

    Writes only final_memo (raw judgment). Style is a separate downstream node.

    Pre-synthesis gate (P0): log field lengths and warn if critical valuation
    or debate fields are empty. Retries for empty fields happen inside each
    analysis node; by this point we only surface remaining gaps honestly.
    """
    if not _agent_enabled(state, "synthesis"):
        print("[synthesis] skipped (query_type routing)", flush=True)
        return {"final_memo": ""}
    status = _field_status(state)
    print(f"[synthesis:gate] field_chars={status}", flush=True)
    weak = [k for k, n in status.items() if n < MIN_USEFUL_CHARS]
    if weak:
        print(
            f"[synthesis:gate] WARNING weak/empty upstream fields: {weak} "
            f"— memo will flag gaps rather than invent content",
            flush=True,
        )

    return {
        "final_memo": _run(
            SYNTHESIS_SYSTEM_PROMPT,
            _build_synthesis_user_prompt(state),
            model=OPUS_MODEL,
            max_tokens=MAX_TOKENS_MEMO,
            label="synthesis",
        )
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. Style pass — Sonnet tier; light touch (cover / headers / closing only)
# ─────────────────────────────────────────────────────────────────────────────

STYLE_PASS_SYSTEM_PROMPT = """\
You are a light writing-style pass on a completed investment memo.

SCOPE — rewrite ONLY these parts (leave the analytical body prose essentially intact):
1. COVER BLOCK at the top: Ticker / Rating (Buy-Hold-Avoid) / Price Target /
   Implied Upside / Time Horizon. Add this block if missing; sharpen if present.
2. SECTION HEADERS: plain, phrase-based titles (e.g. "Understanding the Business",
   "Variant Perception", "The Asymmetry", "Risks"). Rename headers for voice;
   do not delete sections.
3. CLOSING: ensure a binary framing sentence ("Either X or Y. Very little middle
   ground.") and a conditional recommendation ("If you believe X… If you think Y…").
   Rewrite only the final 1–3 paragraphs if needed to land that shape.

HARD CONSTRAINTS:
- Do NOT rewrite the full body paragraph-by-paragraph. Body analysis stays as-is
  except for light header renames and the cover/closing edits above.
- Do not alter the recommendation, price target, any figure, any valuation
  conclusion, or the overall stance.
- Do not add new claims, evidence, or numbers. Do not remove substantive content.
- No corporate hedge-language, no exclamation points, no "in conclusion".

Output the full memo (cover + body with updated headers + closing), not a diff.
"""


def style_pass_node(state: ResearchState) -> dict:
    """Light voice pass on final_memo → styled_memo.

    Only seasons cover block, section headers, and closing — not a full
    body rewrite (token-efficient; keeps synthesis judgment intact).
    """
    raw = state.get("final_memo") or ""
    if not raw.strip():
        return {"styled_memo": ""}

    user_prompt = (
        f"Target: {state.get('ticker') or state['sector']}\n"
        f"Sector: {state['sector']}\n\n"
        f"=== FINAL MEMO ===\n{raw}\n\n"
        "Apply the light style pass: cover block, headers, and closing only. "
        "Preserve every number and conclusion."
    )
    # Cap below full-memo rewrite budget: body is mostly copied, not regenerated.
    styled = _run(
        STYLE_PASS_SYSTEM_PROMPT,
        user_prompt,
        model=SONNET_MODEL,
        max_tokens=MAX_TOKENS_MEMO,
        label="style_pass",
    )
    # If style pass fails empty, ship the raw synthesis rather than a blank docx.
    if not (styled or "").strip():
        print("[style_pass] empty — falling back to final_memo", flush=True)
        styled = raw
    return {"styled_memo": styled}


# ─────────────────────────────────────────────────────────────────────────────
# 8. QC / Verification — institutional review (verify only; never silent edit)
# ─────────────────────────────────────────────────────────────────────────────

QC_SYSTEM_PROMPT = f"""\
You are the senior review analyst. Your job is verification, not improvement. You are the last
substantive check before this memo becomes a document someone acts on. Assume it will be read
by someone allocating real capital, and that any error in it is your responsibility to catch.

You will receive: the synthesized memo, the CANONICAL METRICS block (Python source of truth
for load-bearing figures), and the complete raw outputs of every upstream agent that fed it
(business overview, financial statements, macro/regime assessment, management assessment,
capital allocation assessment, bull thesis, bear thesis, fundamental valuation, relative
valuation).

{CANONICAL_METRICS_SYSTEM_RULE}
Additionally: flag as CRITICAL any figure in the memo that contradicts a canonical metrics
headline (value, unit, basis period, or stripped qualifier). Canonical headlines win over
any agent's re-expression.

Audit against all seven categories below. Be exhaustive. A missed error is a worse outcome than
a false flag.

1. NUMERICAL TRACEABILITY
Every figure in the memo must trace to a specific upstream source — prefer the canonical
metrics headline when the figure is a load-bearing company metric. For each number: does it
appear in the upstream data / canonical headlines, and does it match exactly? Flag any figure
that appears in the memo but not upstream, any figure that differs from its source, and any
figure presented as disclosed fact that was actually derived or estimated upstream (or that
strips a qualifier present in the canonical headline).

2. ARITHMETIC AND UNIT INTEGRITY
Recompute every calculation the memo performs — growth rates, margins, multiples, per-share
figures, implied upside. Check unit consistency obsessively: millions vs. billions, quarterly
vs. annual, basis points vs. percent, per-share vs. absolute. Check that annualized figures
are labeled as annualized. Unit errors are the single most common failure mode in this system's
history and must be treated as high-severity.

3. INTERNAL CONSISTENCY
Does any section contradict another? Common failure patterns: margins described as expanding
in one section and contracting in another; a risk described as near-term in one place and
long-horizon in another; a recommendation inconsistent with the valuation conclusion; a
confidence level stated in the cover block that doesn't match the hedging in the body; a price
target inconsistent with the scenario table.

4. CLAIM PROVENANCE
Every substantive analytical claim in the memo must originate in an upstream agent's output.
Synthesis is forbidden from introducing new claims. Flag anything asserted in the memo that no
upstream agent actually said. Distinguish clearly between: (a) claims properly sourced upstream,
(b) legitimate synthesis-level reasoning that combines two upstream claims, and (c) genuinely
novel assertions with no upstream basis — only (c) is a violation.

5. UPSTREAM COMPLETENESS AND HONEST GAP REPORTING
Check which upstream fields were populated and which were empty or truncated. If any agent
returned nothing or was cut off, the memo MUST disclose that gap explicitly. Flag as a
high-severity failure any case where an upstream field was empty but the memo reads as though
complete analysis was performed. Conversely, verify that any gap the memo does disclose is a
real gap — the memo should not claim missing data that actually arrived.

6. CONFIDENCE CALIBRATION
Does stated confidence match evidentiary strength? Flag: conclusions stated as settled fact
that rest on inference; historical analogies asserted without a stated causal mechanism or
disanalogy; a price target presented with false precision when the underlying model was
self-flagged as low-confidence; hedged upstream findings that became unhedged in the memo.
Also flag the reverse — a well-evidenced finding buried under excessive hedging.

7. RECOMMENDATION INTEGRITY
Does the stated rating follow from the evidence assembled? Does the memo state what would
change the view, and are those triggers specific and monitorable rather than vague? Is position
sizing or conviction language consistent with the actual strength and completeness of the
analysis? If the analysis has material gaps, does the conviction level reflect that?

SEVERITY — assign to every finding carefully (do not inflate):
- CRITICAL: a load-bearing number that contradicts a CANONICAL METRICS headline or engine
  table; fabricated figure with no upstream source; clear arithmetic error on a claim a
  reader would act on; recommendation that reverses the evidence without explanation.
  **Only real CRITICAL findings force STATUS: FAIL.** Do not label presentation issues CRITICAL.
- MAJOR: basis-period wording slips; internal tension that is disclosed elsewhere; de-hedging;
  missing a non-core disclosure. Prefer STATUS: PASS_WITH_FLAGS when numbers match canonical
  and the recommendation is coherent — attach MAJORs as notes rather than FAIL.
- MINOR: imprecise wording, weak sourcing on a non-load-bearing claim, formatting.
  MINOR findings alone = PASS_WITH_FLAGS.

STATUS RULES (strict):
- FAIL only if there is at least one standing CRITICAL after you finish (not withdrawn).
- PASS_WITH_FLAGS for MAJOR/MINOR only when the memo is usable (numbers grounded, gaps disclosed).
- PASS when clean.
- Do not invent CRITICAL findings to appear thorough. If a draft CRITICAL is wrong, delete it —
  do not leave "Withdrawn CRITICAL" noise in the report.
- Prefer fewer precise findings over a long list of nitpicks.

OUTPUT FORMAT:
Line 1: STATUS: PASS | PASS_WITH_FLAGS | FAIL
Then, for each *standing* finding only: severity, category number, the exact quoted text,
the specific problem, and the upstream source. No withdrawn items.
Then: a coverage note stating which upstream fields were populated and which were empty.
Then: one paragraph of overall assessment.
"""

QC_STYLE_SYSTEM_PROMPT = """\
You are verifying that a style/voice rewrite did not alter substance. You will receive two
versions of the same memo: the pre-style version and the post-style version.

Your only question: did anything substantive change?

Check specifically:
- Rating, price target, implied upside, time horizon — must be identical
- Every numerical figure — must be identical
- Every conclusion and its direction
- Every disclosed gap or caveat — must still be present and equally prominent
- Every risk and monitoring trigger — must still be present
- Confidence and hedging language — a hedged claim must not have become unhedged

Rewording, reordering, changed section headers, and altered sentence structure are expected and
fine. Changed meaning is not.

OUTPUT:
Line 1: STYLE_STATUS: CLEAN | DRIFT_DETECTED
If DRIFT_DETECTED, list each change: what the pre-style version said, what the post-style
version says, and why the change is substantive rather than stylistic.
"""


def _is_field_populated(value: Any, *, min_chars: int = 1) -> bool:
    """True when a field has usable content (min_chars default: any non-empty)."""
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, str):
        return len(value.strip()) >= min_chars
    return bool(value)


def _upstream_coverage(state: ResearchState) -> tuple[list[str], list[str], str]:
    """Return (populated, empty, coverage_note) for run-level console health."""
    fields: list[tuple[str, Any]] = [
        ("business_overview", state.get("business_overview")),
        ("income_statement", state.get("income_statement")),
        ("balance_sheet", state.get("balance_sheet")),
        ("cash_flow_statement", state.get("cash_flow_statement")),
        ("sec_filing_summary", state.get("sec_filing_summary")),
        ("canonical_metrics", state.get("canonical_metrics")),
        ("macro_context", state.get("macro_context")),
        ("macro_regime_assessment", state.get("macro_regime_assessment")),
        ("management_assessment", state.get("management_assessment")),
        ("capital_allocation_assessment", state.get("capital_allocation_assessment")),
        ("bull_thesis", state.get("bull_thesis")),
        ("bear_thesis", state.get("bear_thesis")),
        ("fundamental_valuation", state.get("fundamental_valuation")),
        ("relative_valuation", state.get("relative_valuation")),
        ("final_memo", state.get("final_memo")),
    ]
    populated = [k for k, v in fields if _is_field_populated(v)]
    empty = [k for k, v in fields if not _is_field_populated(v)]
    weak = [
        k
        for k, v in fields
        if isinstance(v, str)
        and _is_field_populated(v)
        and not _is_field_populated(v, min_chars=MIN_USEFUL_CHARS)
    ]
    note = (
        f"populated ({len(populated)}): {', '.join(populated) or 'none'}; "
        f"empty ({len(empty)}): {', '.join(empty) or 'none'}"
    )
    if weak:
        note += f"; short/weak (<{MIN_USEFUL_CHARS} chars): {', '.join(weak)}"
    return populated, empty, note


def _severity_counts(report: str) -> dict[str, int]:
    """Count severity labels in a QC report (best-effort, for console health)."""
    counts = {"CRITICAL": 0, "MAJOR": 0, "MINOR": 0}
    for line in (report or "").splitlines():
        # Skip rubric definitions and the STATUS line itself.
        stripped = line.strip()
        if not stripped or stripped.upper().startswith("STATUS"):
            continue
        if re.match(r"(?i)^-?\s*CRITICAL:\s*fabricated", stripped):
            continue
        if re.match(r"(?i)^-?\s*MAJOR:\s*internal", stripped):
            continue
        if re.match(r"(?i)^-?\s*MINOR:\s*imprecise", stripped):
            continue
        # One severity per line; prefer FINDING / bullet / em-dash labels.
        for sev in ("CRITICAL", "MAJOR", "MINOR"):
            if re.search(rf"(?i)\b{sev}\b", line):
                counts[sev] += 1
                break
    return counts


def _parse_qc_status(report: str) -> str:
    """Extract STATUS: PASS | PASS_WITH_FLAGS | FAIL from QC report line 1-ish.

    Fails closed: unparseable / empty reports default to FAIL so a broken QC
    gate cannot silently ship a memo (mirrors _parse_style_status posture).
    """
    text = report or ""
    for line in text.splitlines()[:15]:
        m = re.search(
            r"STATUS\s*:\s*(PASS_WITH_FLAGS|PASS|FAIL)\b",
            line,
            flags=re.IGNORECASE,
        )
        if m:
            return m.group(1).upper()
    upper = text.upper()
    if re.search(r"\bSTATUS\s*:\s*PASS_WITH_FLAGS\b", upper):
        return "PASS_WITH_FLAGS"
    if re.search(r"\bSTATUS\s*:\s*FAIL\b", upper):
        return "FAIL"
    if re.search(r"\bSTATUS\s*:\s*PASS\b", upper):
        return "PASS"
    # Severity heuristics when the STATUS line is missing but findings exist.
    if "CRITICAL" in upper:
        return "FAIL"
    if "MAJOR" in upper or "MINOR" in upper:
        return "PASS_WITH_FLAGS"
    # Unparseable / empty report — fail closed (do not export).
    print(
        "[qc] WARNING: could not parse STATUS from QC report — "
        "defaulting to FAIL (fail-closed)",
        flush=True,
    )
    return "FAIL"


def _parse_style_status(report: str) -> str:
    """Extract STYLE_STATUS: CLEAN | DRIFT_DETECTED."""
    text = report or ""
    for line in text.splitlines()[:15]:
        m = re.search(
            r"STYLE_STATUS\s*:\s*(CLEAN|DRIFT_DETECTED)\b",
            line,
            flags=re.IGNORECASE,
        )
        if m:
            return m.group(1).upper()
    upper = text.upper()
    if "DRIFT_DETECTED" in upper:
        return "DRIFT_DETECTED"
    if re.search(r"\bCLEAN\b", upper):
        return "CLEAN"
    return "DRIFT_DETECTED"


def _print_qc_console(
    *,
    status: str,
    report: str,
    coverage_note: str,
    label: str = "qc",
) -> None:
    """Always-on run-level health signal (status + severity counts + coverage)."""
    counts = _severity_counts(report)
    print(
        f"[{label}] status={status} "
        f"CRITICAL={counts['CRITICAL']} MAJOR={counts['MAJOR']} MINOR={counts['MINOR']}",
        flush=True,
    )
    print(f"[{label}] coverage: {coverage_note}", flush=True)
    if status == "FAIL":
        print(f"[{label}] === FULL QC REPORT (FAIL) ===", flush=True)
        print(report or "(empty report)", flush=True)
        print(f"[{label}] === END QC REPORT ===", flush=True)


def _build_qc_user_prompt(state: ResearchState) -> str:
    """Packet for qc_node: memo + every upstream source of truth."""
    return (
        f"Target: {state.get('ticker') or state['sector']}\n"
        f"Sector: {state['sector']}\n"
        f"User request: {state['user_query']}\n\n"
        f"=== SYNTHESIZED MEMO (final_memo) ===\n"
        f"{state.get('final_memo') or '(empty)'}\n\n"
        f"{format_metrics_for_prompt(state.get('canonical_metrics'))}\n\n"
        f"=== BUSINESS OVERVIEW ===\n{state.get('business_overview') or 'None provided.'}\n\n"
        f"{_json_block('INCOME STATEMENT', state.get('income_statement') or {})}\n\n"
        f"{_json_block('BALANCE SHEET', state.get('balance_sheet') or {})}\n\n"
        f"{_json_block('CASH FLOW STATEMENT', state.get('cash_flow_statement') or {})}\n\n"
        f"=== SEC FILING SUMMARY ===\n{state.get('sec_filing_summary') or 'None provided.'}\n\n"
        f"=== MACRO CONTEXT ===\n{state.get('macro_context') or 'None provided.'}\n\n"
        f"=== MACRO REGIME ASSESSMENT ===\n"
        f"{state.get('macro_regime_assessment') or 'None provided.'}\n\n"
        f"=== MANAGEMENT ASSESSMENT ===\n"
        f"{state.get('management_assessment') or 'None provided.'}\n\n"
        f"=== CAPITAL ALLOCATION ASSESSMENT ===\n"
        f"{state.get('capital_allocation_assessment') or 'None provided.'}\n\n"
        f"=== BULL THESIS ===\n{state.get('bull_thesis') or 'None provided.'}\n\n"
        f"=== BEAR THESIS ===\n{state.get('bear_thesis') or 'None provided.'}\n\n"
        f"=== FUNDAMENTAL VALUATION ===\n"
        f"{state.get('fundamental_valuation') or 'None provided.'}\n\n"
        f"=== RELATIVE VALUATION ===\n"
        f"{state.get('relative_valuation') or 'None provided.'}\n\n"
        "Audit the synthesized memo against all upstream sources and canonical metrics. "
        "Flag CRITICAL any memo figure that contradicts a canonical headline. "
        "Line 1 must be STATUS: PASS | PASS_WITH_FLAGS | FAIL."
    )


def _run_qc_audit(state: ResearchState, *, label: str = "qc") -> tuple[str, str, str]:
    """Run Opus QC once. Returns (report, status, coverage_note)."""
    _, _, coverage_note = _upstream_coverage(state)
    report = _run(
        QC_SYSTEM_PROMPT,
        _build_qc_user_prompt(state),
        model=OPUS_MODEL,
        max_tokens=MAX_TOKENS_MEMO,
        label=label,
    )
    status = _parse_qc_status(report)
    _print_qc_console(
        status=status,
        report=report,
        coverage_note=coverage_note,
        label=label,
    )
    return report, status, coverage_note


def qc_node(state: ResearchState) -> dict:
    """Full institutional audit of final_memo vs every upstream agent.

    Writes: qc_report, qc_status. Never silently edits the memo.

    On FAIL: retry synthesis once with the QC report as correction
    instructions, then re-audit. If still FAIL, status stays FAIL and
    the graph hard-stops before style/export.
    """
    if not _agent_enabled(state, "qc"):
        print("[qc] skipped (query_type routing)", flush=True)
        return {"qc_report": "QC skipped for this query_type.", "qc_status": "PASS"}
    report, status, _coverage = _run_qc_audit(state, label="qc")
    updates: dict[str, Any] = {
        "qc_report": report,
        "qc_status": status,
    }

    if status != "FAIL":
        return updates

    print(
        "[qc] FAIL on first pass — retrying synthesis once with QC report "
        "as correction instructions",
        flush=True,
    )
    corrected = _run(
        SYNTHESIS_SYSTEM_PROMPT,
        _build_synthesis_user_prompt(state, qc_correction=report),
        model=OPUS_MODEL,
        max_tokens=MAX_TOKENS_MEMO,
        label="synthesis_qc_retry",
    )
    if not (corrected or "").strip():
        print(
            "[qc] synthesis retry returned empty — keeping original memo; status FAIL",
            flush=True,
        )
        print(
            "[qc] HARD STOP: material integrity failure after empty retry. "
            "No docx will be exported.",
            flush=True,
        )
        return updates

    updates["final_memo"] = corrected
    # Re-audit against the corrected memo with the same upstream packet.
    retry_state: dict[str, Any] = dict(state)
    retry_state["final_memo"] = corrected
    report2, status2, _ = _run_qc_audit(retry_state, label="qc_retry")  # type: ignore[arg-type]
    updates["qc_report"] = report2
    updates["qc_status"] = status2

    if status2 == "FAIL":
        print(
            "[qc] HARD STOP: QC FAIL after one synthesis retry. "
            "No docx will be exported. See full report above.",
            flush=True,
        )
    else:
        print(
            f"[qc] synthesis retry recovered to status={status2} — proceeding",
            flush=True,
        )
    return updates


def qc_style_check_node(state: ResearchState) -> dict:
    """Narrow check: style pass must not change substance.

    Writes: qc_style_report, qc_style_status (CLEAN | DRIFT_DETECTED).
    On DRIFT_DETECTED the graph hard-stops before docx export.
    """
    pre = state.get("final_memo") or ""
    post = state.get("styled_memo") or ""
    if not pre.strip() and not post.strip():
        report = "STYLE_STATUS: CLEAN\nBoth pre-style and post-style memos are empty."
        print("[qc_style] status=CLEAN (empty memos)", flush=True)
        return {"qc_style_report": report, "qc_style_status": "CLEAN"}

    user_prompt = (
        f"Target: {state.get('ticker') or state['sector']}\n"
        f"Sector: {state['sector']}\n\n"
        f"=== PRE-STYLE MEMO (final_memo) ===\n{pre or '(empty)'}\n\n"
        f"=== POST-STYLE MEMO (styled_memo) ===\n{post or '(empty)'}\n\n"
        "Did anything substantive change? Line 1 must be "
        "STYLE_STATUS: CLEAN or STYLE_STATUS: DRIFT_DETECTED."
    )
    report = _run(
        QC_STYLE_SYSTEM_PROMPT,
        user_prompt,
        model=SONNET_MODEL,
        max_tokens=MAX_TOKENS_SONNET,
        label="qc_style",
    )
    status = _parse_style_status(report)
    print(f"[qc_style] status={status}", flush=True)
    if status == "DRIFT_DETECTED":
        print("[qc_style] === STYLE DRIFT REPORT ===", flush=True)
        print(report or "(empty)", flush=True)
        print("[qc_style] === END STYLE DRIFT REPORT ===", flush=True)
        print(
            "[qc_style] HARD STOP: substance drift in style pass. "
            "No docx will be exported.",
            flush=True,
        )
    return {
        "qc_style_report": report,
        "qc_style_status": status,
    }


def qc_halt_node(state: ResearchState) -> dict:
    """Terminal node after QC FAIL — no export; still emit cost accounting."""
    print(
        f"[qc_halt] Run ended without export. qc_status={state.get('qc_status')!r}",
        flush=True,
    )
    return finalize_run_cost(dict(state))


def qc_style_halt_node(state: ResearchState) -> dict:
    """Terminal node after style substance drift — no export; still emit cost."""
    print(
        f"[qc_style_halt] Run ended without export. "
        f"qc_style_status={state.get('qc_style_status')!r}",
        flush=True,
    )
    return finalize_run_cost(dict(state))
