"""Graph orchestration for the LangGraph Multi-Agent Sector Research System.

Wires the agent nodes from agents.py into a LangGraph StateGraph over
ResearchState. Two pipelines share one graph, selected by the `mode`
input at the entry point:

    entry ──(mode == 'screener')──> screener ────────────────────────> END
      └───(mode == 'deep_dive')──> data_gatherer ─> bull ─> bear ─> synthesis ─> END

Usage:
    from mas_sector_system.main import app
    result = app.invoke({
        "ticker": "NVDA",
        "sector": "Semiconductors",
        "mode": "deep_dive",
        "user_query": "Is NVDA still a buy after the run-up?",
        # remaining fields start empty and are filled by the nodes
        "raw_financials": {}, "sec_filing_summary": "", "macro_context": "",
        "bull_thesis": "", "bear_thesis": "", "red_team_critique": "",
        "final_memo": "",
    })
    print(result["final_memo"])
"""

from langgraph.graph import END, StateGraph

from .agents import (
    _run,
    bear_agent_node,
    bull_agent_node,
    data_gatherer_node,
    synthesis_node,
)
from .state import ResearchState
from .tools import multi_search

# ─────────────────────────────────────────────────────────────────────────────
# Screener node
#
# The screener path surveys the whole sector instead of dissecting a single
# name, so it skips the adversarial debate entirely. It first pulls live
# Tavily research on the sector, then ranks candidates from that evidence.
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
    return {"final_memo": _run(SCREENER_SYSTEM_PROMPT, user_prompt)}


# ─────────────────────────────────────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────────────────────────────────────

def route_by_mode(state: ResearchState) -> str:
    """Entry-point router: pick the pipeline based on the `mode` input.

    Returns the key LangGraph uses to look up the target node in the
    conditional-entry mapping below. Raising on an unknown mode keeps a bad
    input from silently running the wrong (and expensive) pipeline.
    """
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

    # Register every node the router can reach.
    workflow.add_node("screener", screener_node)
    workflow.add_node("data_gatherer", data_gatherer_node)
    workflow.add_node("bull_agent", bull_agent_node)
    workflow.add_node("bear_agent", bear_agent_node)
    workflow.add_node("synthesis", synthesis_node)

    # Conditional entry point: the graph starts by calling route_by_mode on
    # the initial state, then jumps to whichever node its return value maps to.
    workflow.set_conditional_entry_point(
        route_by_mode,
        {
            "screener": "screener",        # broad sweep, no debate
            "deep_dive": "data_gatherer",  # full adversarial pipeline
        },
    )

    # Deep-dive assembly line: gather data, argue both sides, then have the
    # senior writer synthesize the debate into the final memo.
    workflow.add_edge("data_gatherer", "bull_agent")
    workflow.add_edge("bull_agent", "bear_agent")
    workflow.add_edge("bear_agent", "synthesis")
    workflow.add_edge("synthesis", END)

    # The screener report is terminal — no debate stage on this path.
    workflow.add_edge("screener", END)

    return workflow.compile()


# Compiled once at import time so callers can just `from ... import app`.
app = build_graph()


if __name__ == "__main__":
    # Smoke test: print the graph topology without calling any LLM.
    print(app.get_graph().draw_mermaid())
