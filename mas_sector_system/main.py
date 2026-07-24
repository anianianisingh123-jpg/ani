"""Graph orchestration for the LangGraph Multi-Agent Sector Research System.

Wires the agent nodes from agents.py into a LangGraph StateGraph over
ResearchState, per the master spec (CLAUDE.md §3). Two pipelines share one
graph; the supervisor node routes on the `mode` input:

    supervisor ──(mode == 'screener')──> screener ──────────────────────────────┐
        └───────(mode == 'deep_dive')──> data_gatherer ─> bull ─> bear ─> red_team ─> synthesis ─> END
                                                                    (screener) ─────^

Usage:
    from mas_sector_system.main import app
    result = app.invoke({
        "ticker": "NVDA",
        "sector": "Technology",
        "mode": "deep_dive",
        "user_query": "Is NVDA still a buy after the run-up?",
        # remaining fields start empty and are filled by the nodes
        "sec_filings_summary": "", "earnings_sentiment": "",
        "quantitative_raw_data": {}, "raw_financials": {}, "macro_context": "",
        "normalized_metrics": {}, "bull_thesis": "", "bear_thesis": "",
        "red_team_critique": "", "final_memo": "",
    })
    print(result["final_memo"])
"""

from langgraph.graph import END, StateGraph

from .agents import (
    bear_agent_node,
    bull_agent_node,
    data_gatherer_node,
    red_team_node,
    screener_node,
    synthesis_node,
)
from .state import ResearchState

# ─────────────────────────────────────────────────────────────────────────────
# Supervisor / routing
# ─────────────────────────────────────────────────────────────────────────────

def supervisor_node(state: ResearchState) -> dict:
    """Supervisor router (spec §3): the graph's entry node.

    Routing itself happens on this node's conditional edges (route_by_mode
    below), so the node body validates the request and changes no state.
    """
    if not state.get("sector"):
        raise ValueError("sector is required")
    if state["mode"] == "deep_dive" and not state.get("ticker"):
        raise ValueError("deep_dive mode requires a ticker")
    return {}


def route_by_mode(state: ResearchState) -> str:
    """Pick the pipeline branch from the `mode` input.

    Returns the key LangGraph uses to look up the target node in the
    conditional-edge mapping below. Raising on an unknown mode keeps a bad
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

    # Register every node in the topology.
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("screener", screener_node)
    workflow.add_node("data_gatherer", data_gatherer_node)
    workflow.add_node("bull_agent", bull_agent_node)
    workflow.add_node("bear_agent", bear_agent_node)
    workflow.add_node("red_team", red_team_node)
    workflow.add_node("synthesis", synthesis_node)

    # The supervisor is the entry point; its conditional edges dispatch to
    # whichever branch route_by_mode selects.
    workflow.set_entry_point("supervisor")
    workflow.add_conditional_edges(
        "supervisor",
        route_by_mode,
        {
            "screener": "screener",        # "The Radar": broad sweep
            "deep_dive": "data_gatherer",  # "The Sniper": adversarial pipeline
        },
    )

    # Deep-dive assembly line: gather data, argue both sides, red-team the
    # debate itself, then have the senior writer synthesize the final memo.
    workflow.add_edge("data_gatherer", "bull_agent")
    workflow.add_edge("bull_agent", "bear_agent")
    workflow.add_edge("bear_agent", "red_team")
    workflow.add_edge("red_team", "synthesis")

    # The screener's draft shortlist also goes through the senior writer
    # for the final polish (spec §3: screener -> synthesis -> END).
    workflow.add_edge("screener", "synthesis")

    # Both branches converge on synthesis, which produces final_memo.
    workflow.add_edge("synthesis", END)

    return workflow.compile()


# Compiled once at import time so callers can just `from ... import app`.
app = build_graph()


if __name__ == "__main__":
    # Smoke test: print the graph topology without calling any LLM.
    print(app.get_graph().draw_mermaid())
