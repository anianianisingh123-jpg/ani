"""Graph orchestration for the LangGraph Multi-Agent Sector Research System.

Wires the agent nodes from agents.py into a LangGraph StateGraph over
ResearchState. Two pipelines share one graph, selected by the `mode`
input at the entry point:

    entry ──(mode == 'screener')──> screener ──────────────────────────────> END

    entry ──(mode == 'deep_dive')──> deep_dive_start
              ├─> data_gatherer → metrics → validation ──┐
              ├─> business_overview ─────────────────────┤
              ├─> macro_regime ──────────────────────────┼─> capital_ready (defer)
              └─> management_track_record ───────────────┘
                    → capital_allocation → bull
                         → bear / fundamental / relative  (parallel)
                         → synthesis_ready (defer) → synthesis → qc → style → docx
                                      │ FAIL
                                      └─> qc_halt → END

Single-parent analysis path (capital → bull only) prevents LangGraph
multi-parent fan-in from re-running bull/bear/valuation/synthesis twice.
Style QC was removed: style_pass writes styled_memo and exports directly.

Usage (library):
    from mas_sector_system.main import app, run_deep_dive, run_screener
    result = run_deep_dive(
        ticker="NVDA",
        sector="Semiconductors",
        user_query="Is NVDA still a buy after the run-up?",
    )
    print(result["styled_memo"])
    # result["final_memo"] is the unstyled audit copy

Usage (CLI — only the three inputs; worker fields default empty):
    python -m mas_sector_system.main \\
        --ticker NVDA --sector Semiconductors \\
        --query "Is NVDA still a buy after the run-up?"
    python -m mas_sector_system.main \\
        --mode screener --sector Financials \\
        --query "Rank high-conviction bank names"
    python -m mas_sector_system.main --print-graph
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Optional

from langgraph.graph import END, StateGraph

from .agents import (
    _run,
    bear_agent_node,
    bull_agent_node,
    business_overview_node,
    capital_allocation_node,
    data_gatherer_node,
    fundamental_valuation_node,
    macro_regime_node,
    management_track_record_node,
    metrics_compute_node,
    qc_halt_node,
    qc_node,
    relative_valuation_node,
    style_pass_node,
    synthesis_node,
    validation_gate_node,
    validation_halt_node,
)
from .cost import begin_run, finalize_run_cost
from .export_docx import docx_export_node
from .memory import load_prior_context_for_state
from .routing import classify_query, log_routing_decision
from .state import ResearchState
from .tools import multi_search

# ─────────────────────────────────────────────────────────────────────────────
# Screener node (unchanged pipeline — deep_dive rework only)
# ─────────────────────────────────────────────────────────────────────────────

SCREENER_SYSTEM_PROMPT = """\
You are a sector screener for an investment research team. You will be given
LIVE web research (Tavily) about the sector. Survey that evidence and produce
a ranked shortlist of the most interesting candidates for further research.

Rules:
- Prefer names and metrics that appear in the live research. Do not invent
  stale prices or valuation multiples from training memory.
- If a candidate is interesting but the live packet lacks a key metric, say
  so and flag it for a deep dive rather than fabricating the number.

For each candidate: ticker, one-line thesis, key metric that earns it the
spot (with source if possible), and the main risk. Rank by attractiveness
and say why the top pick is ranked first. Flag any candidate that deserves
a full deep dive.
"""


def screener_node(state: ResearchState) -> dict:
    """Broad sector sweep producing a ranked candidate list.

    Populates: final_memo (the screener report IS the deliverable on this
    path — no debate stage runs). Also finalizes cost accounting (screener
    has no docx export node).
    """
    begin_run(
        ticker=state.get("ticker"),
        sector=state.get("sector") or "",
        mode=state.get("mode") or "screener",
        user_query=state.get("user_query") or "",
    )
    sector = state["sector"]
    query = state["user_query"]
    web = multi_search(
        [
            f"{sector} sector stocks top performers valuation outlook latest",
            f"{sector} industry news earnings leaders laggards risks",
            f"{sector} {query}",
        ],
        max_results=6,
        topic="finance",
    )
    user_prompt = (
        f"Sector: {sector}\n"
        f"User request: {query}\n\n"
        f"=== LIVE WEB RESEARCH (Tavily) ===\n{web}\n\n"
        "Using the live research above, run the screen and produce the ranked shortlist."
    )
    # Screener stays on Sonnet (default) — lower individual stakes than deep-dive.
    memo = _run(SCREENER_SYSTEM_PROMPT, user_prompt)
    cost_update = finalize_run_cost({**dict(state), "final_memo": memo})
    from .cost import append_cost_to_memo

    memo = append_cost_to_memo(memo, cost_update.get("cost_report") or "")
    return {"final_memo": memo, **cost_update}


# ─────────────────────────────────────────────────────────────────────────────
# Deep-dive fan-out entry (passthrough so entry can branch to foundation nodes)
# ─────────────────────────────────────────────────────────────────────────────

def deep_dive_start_node(state: ResearchState) -> dict:
    """Entry for deep_dive: start cost tracker, load prior memory, classify, fan out."""
    begin_run(
        ticker=state.get("ticker"),
        sector=state.get("sector") or "",
        mode=state.get("mode") or "deep_dive",
        user_query=state.get("user_query") or "",
    )
    decision = classify_query(
        state.get("user_query") or "",
        mode=state.get("mode"),
        sector=state.get("sector"),
        ticker=state.get("ticker"),
    )
    log_routing_decision(decision)
    # Long-term memory: inject last desk memo/metrics for this ticker (no new node).
    memory = load_prior_context_for_state(
        ticker=state.get("ticker"),
        mode=state.get("mode") or "deep_dive",
    )
    return {
        "query_type": decision.get("query_type") or "full_underwrite",
        "routing_decision": decision,
        **memory,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────────────────────────────────────

def route_by_mode(state: ResearchState) -> str:
    """Entry-point router: pick the pipeline based on the `mode` input."""
    mode = state["mode"]
    if mode == "screener":
        return "screener"
    if mode == "deep_dive":
        return "deep_dive"
    raise ValueError(f"Unknown mode: {mode!r} (expected 'screener' or 'deep_dive')")


def route_after_qc(state: ResearchState) -> str:
    """After substantive QC: FAIL hard-stops; otherwise continue to style."""
    if (state.get("qc_status") or "").upper() == "FAIL":
        return "qc_halt"
    return "style_pass"


def route_after_validation(state: ResearchState) -> str:
    """Pre-narration gate: FAIL hard-stops before capital/analysis spend."""
    status = (state.get("validation_status") or "").upper()
    if status == "FAIL":
        return "validation_halt"
    return "continue"


# ─────────────────────────────────────────────────────────────────────────────
# Graph assembly
# ─────────────────────────────────────────────────────────────────────────────

def _passthrough_barrier(state: ResearchState) -> dict:
    """No-op join node. State is already fully merged by LangGraph."""
    return {}


def build_graph():
    """Assemble and compile the research graph.

    Double-execution fix (LangGraph multi-parent fan-in):
    Analysis used to re-fire when overview/macro completed in one wave and
    capital_allocation in a later wave. We now:
      1. Fold overview + macro into the *same* deferred capital_ready join as
         validation + management (all foundation work joins once).
      2. Give bull a *single* parent (capital_allocation) — no multi-parent
         analysis_ready barrier on the critical path.
      3. Join synthesis only from the three parallel analysis children
         (bear / fundamental / relative), not also from bull directly.
      4. Agents also skip if their output field is already populated
         (idempotency belt-and-suspenders).

    Style QC layer removed: style_pass → docx_export directly.
    """
    workflow = StateGraph(ResearchState)

    # Register every node the router / edges can reach.
    workflow.add_node("screener", screener_node)
    workflow.add_node("deep_dive_start", deep_dive_start_node)
    workflow.add_node("data_gatherer", data_gatherer_node)
    workflow.add_node("metrics_compute", metrics_compute_node)
    workflow.add_node("validation_gate", validation_gate_node)
    workflow.add_node("validation_halt", validation_halt_node)
    workflow.add_node("post_validation", _passthrough_barrier)
    workflow.add_node("business_overview", business_overview_node)
    workflow.add_node("macro_regime", macro_regime_node)
    workflow.add_node("management_track_record", management_track_record_node)
    # Deferred join: ALL foundation work must finish before capital/analysis.
    workflow.add_node("capital_ready", _passthrough_barrier, defer=True)
    workflow.add_node("capital_allocation", capital_allocation_node)
    workflow.add_node("bull_agent", bull_agent_node)
    workflow.add_node("bear_agent", bear_agent_node)
    workflow.add_node("fundamental_valuation", fundamental_valuation_node)
    workflow.add_node("relative_valuation", relative_valuation_node)
    # Deferred join of the three parallel analysis children only.
    workflow.add_node("synthesis_ready", _passthrough_barrier, defer=True)
    workflow.add_node("synthesis", synthesis_node)
    workflow.add_node("qc", qc_node)
    workflow.add_node("qc_halt", qc_halt_node)
    workflow.add_node("style_pass", style_pass_node)
    workflow.add_node("docx_export", docx_export_node)

    # Conditional entry: screener path vs deep-dive fan-out start.
    workflow.set_conditional_entry_point(
        route_by_mode,
        {
            "screener": "screener",
            "deep_dive": "deep_dive_start",
        },
    )

    # Parallel foundation at entry (each independent of the others).
    workflow.add_edge("deep_dive_start", "data_gatherer")
    workflow.add_edge("deep_dive_start", "business_overview")
    workflow.add_edge("deep_dive_start", "macro_regime")
    workflow.add_edge("deep_dive_start", "management_track_record")

    # Metrics contract: compute once from statements before any number-using agent.
    workflow.add_edge("data_gatherer", "metrics_compute")
    # Phase 3: validation gate after metrics, before capital/analysis spend.
    workflow.add_edge("metrics_compute", "validation_gate")
    workflow.add_conditional_edges(
        "validation_gate",
        route_after_validation,
        {
            "validation_halt": "validation_halt",
            "continue": "post_validation",
        },
    )
    workflow.add_edge("validation_halt", END)

    # Capital only after validation PASS/WARN *and* the three parallel foundation
    # writers, via one deferred join. Single downstream edge into analysis.
    workflow.add_edge("post_validation", "capital_ready")
    workflow.add_edge("management_track_record", "capital_ready")
    workflow.add_edge("business_overview", "capital_ready")
    workflow.add_edge("macro_regime", "capital_ready")
    workflow.add_edge("capital_ready", "capital_allocation")

    # Cache-friendly analysis order (single parent into bull):
    #   capital_allocation → bull (writes the shared-prefix cache)
    #                     ↘ bear / fundamental / relative in parallel (cache reads)
    # Those three join at synthesis_ready. Bull is NOT a direct parent of
    # synthesis_ready (that multi-parent pattern re-fired the fan-out).
    workflow.add_edge("capital_allocation", "bull_agent")
    for node in (
        "bear_agent",
        "fundamental_valuation",
        "relative_valuation",
    ):
        workflow.add_edge("bull_agent", node)
        workflow.add_edge(node, "synthesis_ready")

    workflow.add_edge("synthesis_ready", "synthesis")

    # Synthesis → QC (substantive) → style → docx (or hard stop on QC FAIL).
    workflow.add_edge("synthesis", "qc")
    workflow.add_conditional_edges(
        "qc",
        route_after_qc,
        {
            "style_pass": "style_pass",
            "qc_halt": "qc_halt",
        },
    )
    workflow.add_edge("qc_halt", END)
    workflow.add_edge("style_pass", "docx_export")
    workflow.add_edge("docx_export", END)

    # Screener report is terminal (no style pass on this path).
    workflow.add_edge("screener", END)

    return workflow.compile()


# Compiled once at import time so callers can just `from ... import app`.
app = build_graph()


def empty_state(
    *,
    ticker: Optional[str],
    sector: str,
    mode: str,
    user_query: str,
) -> dict:
    """Build a fully-keyed initial ResearchState dict for invoke()."""
    return {
        "ticker": ticker,
        "sector": sector,
        "mode": mode,
        "user_query": user_query,
        "business_overview": "",
        "income_statement": {},
        "balance_sheet": {},
        "cash_flow_statement": {},
        "sec_filing_summary": "",
        "cik": None,
        "sic": None,
        "extraction_archetype": "general",
        "canonical_metrics": {},
        "validation_report": {},
        "validation_status": "",
        "query_type": "full_underwrite",
        "routing_decision": {},
        "prior_run_id": None,
        "prior_run_meta": {},
        "prior_run_context": "",
        "macro_context": "",
        "macro_regime_assessment": "",
        "management_assessment": "",
        "capital_allocation_assessment": "",
        "bull_thesis": "",
        "bear_thesis": "",
        "fundamental_valuation": "",
        "relative_valuation": "",
        "final_memo": "",
        "styled_memo": "",
        "qc_report": "",
        "qc_status": "",
        "qc_style_status": "",
        "qc_style_report": "",
        "cost_report": "",
        "cost_data": {},
    }


def run_deep_dive(
    *,
    ticker: str,
    sector: str,
    user_query: str,
) -> dict[str, Any]:
    """Convenience entry: run deep_dive, style pass, and docx export.

    Only ticker / sector / user_query are required; every worker and output
    field is initialized to its empty default via empty_state().

    Returns the full result state. Prints the saved .docx path (via the
    export node). final_memo is unstyled audit copy; styled_memo is the
    reader-facing memo that was exported.
    """
    return app.invoke(
        empty_state(
            ticker=ticker,
            sector=sector,
            mode="deep_dive",
            user_query=user_query,
        )
    )


def run_screener(
    *,
    sector: str,
    user_query: str,
    ticker: Optional[str] = None,
) -> dict[str, Any]:
    """Convenience entry: run the sector screener pipeline.

    Only sector / user_query are required (ticker is optional and usually
    omitted). Worker fields are filled with empty defaults automatically.
    """
    return app.invoke(
        empty_state(
            ticker=ticker,
            sector=sector,
            mode="screener",
            user_query=user_query,
        )
    )


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mas_sector_system.main",
        description=(
            "Run the multi-agent research graph. Pass only ticker, sector, "
            "and query — all other ResearchState fields default to empty."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("deep_dive", "screener"),
        default="deep_dive",
        help="Pipeline to run (default: deep_dive).",
    )
    parser.add_argument(
        "--ticker",
        default=None,
        help="Ticker symbol (required for deep_dive; optional for screener).",
    )
    parser.add_argument(
        "--sector",
        default=None,
        help="Market sector (e.g. Semiconductors, Financials).",
    )
    parser.add_argument(
        "--query",
        dest="user_query",
        default=None,
        help="Natural-language research request.",
    )
    parser.add_argument(
        "--print-graph",
        action="store_true",
        help="Print the LangGraph Mermaid topology and exit (no LLM calls).",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

    if args.print_graph:
        print(app.get_graph().draw_mermaid())
        return 0

    if not args.sector or not args.user_query:
        parser.error("--sector and --query are required (unless --print-graph).")

    if args.mode == "deep_dive":
        if not args.ticker:
            parser.error("--ticker is required when --mode deep_dive.")
        result = run_deep_dive(
            ticker=args.ticker,
            sector=args.sector,
            user_query=args.user_query,
        )
        # Prefer the reader-facing styled memo; fall back to raw synthesis.
        output = result.get("styled_memo") or result.get("final_memo") or ""
    else:
        result = run_screener(
            sector=args.sector,
            user_query=args.user_query,
            ticker=args.ticker,
        )
        output = result.get("final_memo") or ""

    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
