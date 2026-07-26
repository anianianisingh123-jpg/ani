"""Graph orchestration for the LangGraph Multi-Agent Sector Research System.

Wires the agent nodes from agents.py into a LangGraph StateGraph over
ResearchState. Two pipelines share one graph, selected by the `mode`
input at the entry point:

    entry ──(mode == 'screener')──> screener ──────────────────────────────> END

    entry ──(mode == 'deep_dive')──> deep_dive_start
              ├─> data_gatherer ──────────┐
              └─> business_overview ──────┼─> bull_agent ──────────────────┐
                                          ├─> bear_agent ──────────────────┤
                                          ├─> fundamental_valuation ───────┼─> synthesis
                                          └─> relative_valuation ──────────┘
                                                → style_pass → docx_export → END

Usage:
    from mas_sector_system.main import app, run_deep_dive
    result = run_deep_dive(
        ticker="NVDA",
        sector="Semiconductors",
        user_query="Is NVDA still a buy after the run-up?",
    )
    print(result["styled_memo"])
    # result["final_memo"] is the unstyled audit copy
"""

from __future__ import annotations

from typing import Any, Optional

from langgraph.graph import END, StateGraph

from .agents import (
    _run,
    bear_agent_node,
    bull_agent_node,
    business_overview_node,
    data_gatherer_node,
    fundamental_valuation_node,
    relative_valuation_node,
    style_pass_node,
    synthesis_node,
)
from .export_docx import docx_export_node
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
    path — no debate stage runs).
    """
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
    return {"final_memo": _run(SCREENER_SYSTEM_PROMPT, user_prompt)}


# ─────────────────────────────────────────────────────────────────────────────
# Deep-dive fan-out entry (passthrough so entry can branch to two nodes)
# ─────────────────────────────────────────────────────────────────────────────

def deep_dive_start_node(state: ResearchState) -> dict:
    """No-op entry for deep_dive so the graph can fan out in parallel."""
    return {}


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


# ─────────────────────────────────────────────────────────────────────────────
# Graph assembly
# ─────────────────────────────────────────────────────────────────────────────

def build_graph():
    """Assemble and compile the research graph."""
    workflow = StateGraph(ResearchState)

    # Register every node the router / edges can reach.
    workflow.add_node("screener", screener_node)
    workflow.add_node("deep_dive_start", deep_dive_start_node)
    workflow.add_node("data_gatherer", data_gatherer_node)
    workflow.add_node("business_overview", business_overview_node)
    workflow.add_node("bull_agent", bull_agent_node)
    workflow.add_node("bear_agent", bear_agent_node)
    workflow.add_node("fundamental_valuation", fundamental_valuation_node)
    workflow.add_node("relative_valuation", relative_valuation_node)
    workflow.add_node("synthesis", synthesis_node)
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

    # Parallel foundation: statements + business narrative (independent).
    workflow.add_edge("deep_dive_start", "data_gatherer")
    workflow.add_edge("deep_dive_start", "business_overview")

    # Fan-out: both foundation nodes feed all four analysis branches.
    # LangGraph joins on multi-parent nodes — each analysis waits for both.
    analysis_nodes = (
        "bull_agent",
        "bear_agent",
        "fundamental_valuation",
        "relative_valuation",
    )
    for node in analysis_nodes:
        workflow.add_edge("data_gatherer", node)
        workflow.add_edge("business_overview", node)
        # Fan-in: synthesis waits for all four analysis branches.
        workflow.add_edge(node, "synthesis")

    # Synthesis (judgment) → style pass (voice only) → docx export → END
    workflow.add_edge("synthesis", "style_pass")
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
        "macro_context": "",
        "bull_thesis": "",
        "bear_thesis": "",
        "fundamental_valuation": "",
        "relative_valuation": "",
        "final_memo": "",
        "styled_memo": "",
    }


def run_deep_dive(
    *,
    ticker: str,
    sector: str,
    user_query: str,
) -> dict[str, Any]:
    """Convenience entry: run deep_dive, style pass, and docx export.

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


if __name__ == "__main__":
    # Smoke test: print the graph topology without calling any LLM.
    print(app.get_graph().draw_mermaid())
