"""State schema for the LangGraph Multi-Agent Sector Research System.

This module defines the shared state object that flows between every agent
node in the graph. Each agent reads the fields it needs and writes its
output back into the state, allowing downstream agents (and the final
synthesis step) to build on prior work. Field layout follows the master
architecture specification in CLAUDE.md (§2).
"""

from __future__ import annotations

from typing import Literal, Optional

try:
    # LangGraph recommends typing_extensions.TypedDict for full feature
    # support across Python versions; fall back to the stdlib if absent.
    from typing_extensions import TypedDict
except ImportError:
    from typing import TypedDict


class ResearchState(TypedDict):
    # ------------------------------------------------------------------
    # Base inputs (set once at graph invocation, read-only thereafter)
    # ------------------------------------------------------------------

    # Stock ticker symbol to analyze (e.g. "NVDA"). Optional because in
    # 'screener' mode the system surveys a whole sector and no single
    # ticker is specified up front.
    ticker: Optional[str]

    # The market sector under investigation (e.g. "Technology",
    # "Financials"). Always required — it scopes screener sweeps and
    # deep dives, and drives the dynamic sector prompt injection.
    sector: str

    # Operating mode for the graph:
    #   'screener'  — "The Radar": broad sweep across the sector.
    #   'deep_dive' — "The Sniper": exhaustive analysis of one ticker.
    # The supervisor routes on this value.
    mode: Literal["screener", "deep_dive"]

    # The user's original natural-language request. Preserved verbatim so
    # every agent can ground its analysis in the user's actual intent
    # rather than a lossy paraphrase.
    user_query: str

    # ------------------------------------------------------------------
    # Worker scratchpads (populated by the data-gathering workers)
    # ------------------------------------------------------------------

    # Condensed summary of relevant SEC filings (10-K, 10-Q, 8-K) —
    # risk factors, management discussion, and notable disclosures.
    sec_filings_summary: str

    # Tone and takeaways from the latest earnings report / call: beats or
    # misses, guidance direction, and management's confidence level.
    earnings_sentiment: str

    # General-purpose quantitative scratchpad. In screener mode this holds
    # the ranked shortlist draft before the synthesis polish; deep-dive
    # workers may stash intermediate computations here.
    quantitative_raw_data: dict

    # Structured financial data pulled from market-data APIs: income
    # statement items, balance sheet figures, valuation multiples, plus
    # the untouched live feed under 'live_market_data'.
    raw_financials: dict

    # Top-down macroeconomic backdrop relevant to the sector: rates,
    # inflation, FX, commodity trends, and policy developments.
    macro_context: str

    # ------------------------------------------------------------------
    # Normalized ledger (the Fundamental Adjustment Ledger)
    # ------------------------------------------------------------------

    # Clean non-GAAP math: one-time items isolated and stripped (e.g.
    # non-cash tax distortions, impairments) with headline vs. adjusted
    # figures side by side — the true adjusted P/E lives here.
    normalized_metrics: dict

    # ------------------------------------------------------------------
    # Adversarial debate (populated by the debate agents)
    # ------------------------------------------------------------------

    # The strongest good-faith case FOR the investment, written by the
    # bull agent using the gathered and normalized data above.
    bull_thesis: str

    # The strongest good-faith case AGAINST the investment, written by
    # the bear agent — same evidence base, opposite conclusion.
    bear_thesis: str

    # Independent critique from the red-team agent: attacks weak logic,
    # unsupported claims, and cherry-picked data in BOTH theses before
    # anything reaches the final memo.
    red_team_critique: str

    # ------------------------------------------------------------------
    # Final output (populated by the synthesis agent, terminal node)
    # ------------------------------------------------------------------

    # The finished deliverable: the deep-dive investment memo, or the
    # polished screener shortlist memo, depending on mode.
    final_memo: str
