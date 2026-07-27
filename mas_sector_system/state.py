"""State schema for the LangGraph Multi-Agent Sector Research System.

This module defines the shared state object that flows between every agent
node in the graph. Each agent reads the fields it needs and writes its
output back into the state, allowing downstream agents (and the final
synthesis step) to build on prior work.
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
    # Business description (populated by business_overview_node)
    # ------------------------------------------------------------------

    # Plain-language description of what the company does: products,
    # segments, revenue model, geography, competitive position, history,
    # and strategic direction. Purely descriptive — no valuation opinion.
    business_overview: str

    # ------------------------------------------------------------------
    # Quantitative / filing fields (populated by data_gatherer_node)
    # ------------------------------------------------------------------

    # Parsed income statement: current + prior fiscal year and quarter
    # line items from SEC XBRL company facts (plus any LLM-normalized
    # adjustments nested under an "adjusted" key).
    income_statement: dict

    # Parsed balance sheet: current + prior periods from SEC XBRL.
    balance_sheet: dict

    # Parsed cash flow statement: current + prior periods from SEC XBRL,
    # including computed FreeCashFlow where Operating CF and CapEx exist.
    cash_flow_statement: dict

    # Condensed summary of relevant SEC filings and narrative context
    # (risk factors, MD&A themes, earnings-call takeaways) written by
    # the data gatherer from Tavily + filing search.
    sec_filing_summary: str

    # SEC identity (from submissions JSON during gather)
    cik: Optional[str]
    sic: Optional[str]
    extraction_archetype: str

    # Canonical metrics contract (metrics.py): every load-bearing figure
    # computed in Python with provenance, qualifiers, and a verbatim headline.
    # Populated immediately after data_gatherer; analytical agents must quote
    # headlines rather than recomputing from raw statement lines.
    canonical_metrics: dict

    # Phase 3 validation gate output (PASS/WARN/FAIL + checks).
    validation_report: dict
    validation_status: str

    # Phase 4 query routing.
    query_type: str
    routing_decision: dict

    # Top-down macroeconomic backdrop relevant to the sector: rates,
    # inflation, FX, commodity trends, and policy developments.
    # Written by data_gatherer_node as a short narrative digest.
    macro_context: str

    # Structured macro/cycle positioning assessment from macro_regime_node:
    # debt-cycle lens, reflexivity check, sector-cycle position, and an
    # explicit TAILWIND / HEADWIND / NEUTRAL verdict for this company.
    # Independent Tavily research — not derived from data_gatherer.
    macro_regime_assessment: str

    # Leadership / track-record assessment from management_track_record_node:
    # who the executives are, tenure and prior roles, decisions at this
    # company, insider activity, compensation alignment, governance/
    # succession, and red flags. People and leadership only — not cash
    # deployment (that is capital_allocation_assessment).
    management_assessment: str

    # Capital allocation quality from capital_allocation_node: reinvestment,
    # M&A, dividends, buybacks, and debt management scored against the
    # statement numbers, with an alignment cross-check vs management_assessment.
    capital_allocation_assessment: str

    # ------------------------------------------------------------------
    # Adversarial debate fields (populated by the debate agents)
    # ------------------------------------------------------------------

    # The strongest good-faith case FOR the investment, written by the
    # bull agent using the data gathered above.
    bull_thesis: str

    # The strongest good-faith case AGAINST the investment, written by
    # the bear agent — same evidence base, opposite conclusion.
    bear_thesis: str

    # ------------------------------------------------------------------
    # Valuation fields (independent of bull/bear)
    # ------------------------------------------------------------------

    # Intrinsic valuation write-up (DCF / DDM / FFO / etc. by archetype).
    fundamental_valuation: str

    # Relative / comps valuation write-up (multiples vs peers + history).
    relative_valuation: str

    # ------------------------------------------------------------------
    # Output fields
    # ------------------------------------------------------------------

    # Raw investment memo from synthesis — pure judgment, unstyled.
    # Never overwritten by the style pass; kept permanently so QC style
    # check can compare pre- vs post-style and so failures can be audited.
    final_memo: str

    # Voice-seasoned rewrite of final_memo from style_pass_node.
    # Reader-facing deliverable; substantive claims must match final_memo.
    styled_memo: str

    # ------------------------------------------------------------------
    # QC / institutional review (verification only — never silently edits)
    # ------------------------------------------------------------------

    # Full audit report from qc_node: findings by severity/category, coverage
    # note, and overall assessment. Does not rewrite the memo.
    qc_report: str

    # PASS | PASS_WITH_FLAGS | FAIL from qc_node. FAIL hard-stops export.
    qc_status: str

    # CLEAN | DRIFT_DETECTED from qc_style_check (style substance drift).
    qc_style_status: str

    # Style-check report: empty when CLEAN; lists substantive drifts otherwise.
    qc_style_report: str

    # ------------------------------------------------------------------
    # Cost / token accounting (estimate — not billed amount)
    # ------------------------------------------------------------------

    # Condensed run-cost block appended to every memo unconditionally.
    cost_report: str

    # Structured per-node figures for cross-run analysis (also JSONL-logged).
    cost_data: dict
