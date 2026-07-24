"""State schema for the LangGraph Multi-Agent Sector Research System.

This module defines the shared state object that flows between every agent
node in the graph. Each agent reads the fields it needs and writes its
output back into the state, allowing downstream agents (and the final
synthesis step) to build on prior work.
"""

from typing import Literal, Optional

try:
    # LangGraph recommends typing_extensions.TypedDict for full feature
    # support across Python versions; fall back to the stdlib if absent.
    from typing_extensions import TypedDict
except ImportError:
    from typing import TypedDict


class ResearchState(TypedDict):
    # ------------------------------------------------------------------
    # Input parameters (set once at graph invocation, read-only thereafter)
    # ------------------------------------------------------------------

    # Stock ticker symbol to analyze (e.g. "NVDA"). Optional because in
    # 'screener' mode the system surveys a whole sector and no single
    # ticker is specified up front.
    ticker: Optional[str]

    # The market sector under investigation (e.g. "Semiconductors",
    # "Healthcare"). Always required — it scopes both screener sweeps
    # and single-name deep dives.
    sector: str

    # Operating mode for the graph:
    #   'screener'  — broad sweep across the sector to rank candidates.
    #   'deep_dive' — exhaustive analysis of a single ticker.
    # Routing nodes branch on this value.
    mode: Literal["screener", "deep_dive"]

    # The user's original natural-language request. Preserved verbatim so
    # every agent can ground its analysis in the user's actual intent
    # rather than a lossy paraphrase.
    user_query: str

    # ------------------------------------------------------------------
    # Quantitative / raw data fields (populated by data-gathering agents)
    # ------------------------------------------------------------------

    # Structured financial data pulled from market-data APIs: income
    # statement items, balance sheet figures, valuation multiples, etc.
    # Kept as a dict so downstream agents can query specific metrics.
    raw_financials: dict

    # Condensed summary of relevant SEC filings (10-K, 10-Q, 8-K) written
    # by the filings agent — risk factors, management discussion, and
    # notable disclosures distilled into prose.
    sec_filing_summary: str

    # Top-down macroeconomic backdrop relevant to the sector: rates,
    # inflation, FX, commodity trends, and policy developments that could
    # move the group. Produced by the macro agent.
    macro_context: str

    # ------------------------------------------------------------------
    # Adversarial debate fields (populated by the debate agents)
    # ------------------------------------------------------------------

    # The strongest good-faith case FOR the investment, written by the
    # bull agent using the raw data gathered above.
    bull_thesis: str

    # The strongest good-faith case AGAINST the investment, written by
    # the bear agent — same evidence base, opposite conclusion.
    bear_thesis: str

    # Independent critique from the red-team agent: attacks weak logic,
    # unsupported claims, and blind spots in BOTH the bull and bear
    # theses before anything reaches the final memo.
    red_team_critique: str

    # ------------------------------------------------------------------
    # Output field (populated by the synthesis agent, terminal node)
    # ------------------------------------------------------------------

    # The finished investment memo: synthesizes the data, the debate, and
    # the red-team critique into a balanced, decision-ready document.
    # This is the artifact returned to the user.
    final_memo: str
