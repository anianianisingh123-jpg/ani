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

    # ------------------------------------------------------------------
    # Long-term desk memory (loaded at deep_dive entry; no new graph nodes)
    # ------------------------------------------------------------------

    # SQLite row id of the most recent prior run for this ticker (if any).
    prior_run_id: Optional[int]

    # Compact meta: created_at, rating, price_target, qc_status, etc.
    prior_run_meta: dict

    # Bounded prompt block injected into foundation agents so the desk can
    # track thesis changes vs its own last memo / metrics.
    prior_run_context: str

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

    # Structured output of the deterministic valuation engine, kept alongside
    # the narratives above. The agents narrate these dicts; previously they
    # were computed, formatted into the prompt, and discarded, which left the
    # downstream artifacts with prose but no numbers to chart. Engine tables
    # remain the source of truth per CLAUDE.md §6 — agents do not invent them.
    #
    # dcf_engine: compute_dcf_from_state() — inputs, assumptions (wacc,
    # g_high, g_terminal), per-year projections, terminal/enterprise/equity
    # value, fair_value_per_share, fair_value_range, epv_per_share,
    # implied_upside_vs_price, plus warnings/errors (compliance content —
    # routed to the audit log, never the clean memo).
    dcf_engine: dict

    # comps_engine: fetch_peer_multiples() — subject row, peer rows, peer
    # medians, relative read per multiple, overall_vs_peers, peer_list, and
    # peer_exclusions/notes (compliance content — audit log only).
    comps_engine: dict

    # ------------------------------------------------------------------
    # Argued-input valuation (VALUATION_ICL_DESIGN.md) — the judgment layer
    #
    # dcf_engine / comps_engine above stay the ANCHOR case: sector-default
    # assumptions, never overwritten, always shipped alongside the fields
    # below. The engine math remains deterministic per CLAUDE.md §3 — what
    # these fields add is that the *inputs* stop being sector constants and
    # become arguable within hard clamps (design §4.2).
    #
    # The LLM's output surface here is bounded scalars and enums only. It
    # cannot emit a currency amount, so a fabricated fair value has nowhere
    # to live — that is a structural property, not a prompt instruction.
    # ------------------------------------------------------------------

    # Structured critique of the DCF engine's assumptions from the
    # fundamental node's critique call. Per-parameter: engine_default,
    # argued_range [lo, hi], verdict, reasoning, and evidence[] — field ids
    # that must resolve to non-null state values or the parameter is
    # rejected and reverts to default (design §4.4, the anti-motivated-
    # reasoning control). Also carries terminal_value_share_of_ev, which is
    # the fastest tell for a terminal-dominated DCF.
    valuation_critique: Optional[dict]

    # Same contract for the comps path: argued peer inclusions/exclusions
    # (candidate-pool only — an invented ticker cannot be added) and the
    # justified multiple with its argued range. This is where the desk's
    # re-rating case lives, and per design §5.1 it builds before the DCF
    # critique because that is where the memo corpus is dense.
    relative_critique: Optional[dict]

    # Engine re-run with the accepted argued inputs. Same shape as
    # dcf_engine, plus input_source="argued", clamp_warnings[] and
    # band_dissents[]. Runs at both corners of each argued range, so this
    # yields a band rather than a false-precision point. None when the
    # critique call failed or every parameter was rejected — the base case
    # always ships regardless (design §9).
    dcf_judgment: Optional[dict]

    # Comps counterpart: peer set after accepted changes, recomputed
    # medians, and implied value from the argued multiple applied to a
    # consensus forward estimate (price ÷ forwardPE — engine-derived, never
    # LLM-supplied; design §5.3). Carries forward_estimate_available=False
    # when forwardPE is null and the trailing fallback was used.
    comps_judgment: Optional[dict]

    # Rubric score for the valuation sections (valuation_rubric.py): the
    # 11 criteria in design §10.1, per-criterion rather than total-only.
    # Criteria that required an LLM judge are marked judged=True. This is
    # the measurement that makes "institutional grade" falsifiable — without
    # it there is no way to tell whether the ICL layers helped.
    valuation_grade: Optional[dict]

    # ------------------------------------------------------------------
    # Forward estimates (FORWARD_ESTIMATE_DESIGN.md) — the modelling layer
    #
    # Everything above values the company off a trailing figure with argued
    # rates. These fields carry a modelled forward P&L instead: history →
    # computed trends → 4–8 argued drivers → Python-built projection.
    #
    # The invariant is unchanged and now spans a longer chain: Python computes
    # every figure, the LLM argues only the drivers, and the LLM's output
    # surface holds bounded scalars and enums — never a currency amount. A
    # forecast is the easiest place in this system to fabricate, which is why
    # none of these fields may be assigned from model output.
    # ------------------------------------------------------------------

    # Facts computed from the five annual periods already carried on each
    # statement's `annual_series` (design §3.2): growth per segment and in
    # total, margin ranges and trend, opex/tax/capex/working-capital ratios,
    # share-count pace, FCF conversion. Judgment-free — the LLM may cite these
    # as evidence and argue *against* them, but may never overwrite one.
    # Also the source of the mechanical defaults (§5.3), which is how most of
    # a forecast gets set empirically with no judgment at all.
    historical_profile: dict

    # Deterministic 5-year projection from the accepted drivers
    # (`forecast_engine.build_forecast`): per-year revenue by segment, margins,
    # opex, operating and net income, EPS, and free cash flow. Annual only —
    # quarterly is deliberately out of scope. None when no forecast was
    # produced, which must leave the trailing-based valuation fully intact.
    forecast: Optional[dict]

    # Structured argument over the drivers, mirroring `valuation_critique` but
    # pointed at growth/margin/opex rather than WACC. Adds one mandatory field
    # the valuation critique does not have: every driver must carry a
    # `historical_basis` naming the trend it departs from. An argument that
    # cannot name what it is breaking is a guess, and is rejected in code.
    driver_critique: Optional[dict]

    # DCF run against the modelled cash flows rather than a grown trailing
    # figure. Travels ALONGSIDE `dcf_engine` (sector-default anchor) and
    # `dcf_judgment` (argued rates on trailing FCF) — three cases ship
    # together and none replaces another.
    dcf_modelled: Optional[dict]

    # Modelled year-1 revenue/EPS against consensus, with the gap stated
    # (§9.2). This is the desk's variant perception quantified: "modelled FY27
    # EPS $8.38 vs consensus $8.82, 5% below, driven by opex." Report the gap;
    # never force agreement — a large argued divergence is a legitimate view,
    # a silent one is a bug.
    consensus_reconciliation: Optional[dict]

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

    # ------------------------------------------------------------------
    # Split deliverables (artifacts.py) — thesis and compliance are separate
    # documents with separate audiences; never merge them back together.
    # ------------------------------------------------------------------

    # Reader-facing thesis only, parsed deterministically from final_memo:
    # business overview, recommendation, macro positioning, management/capital
    # allocation, key debate, valuation reconciliation, catalysts/risks.
    # Carries no QC findings, stale-tag warnings, or cost figures.
    clean_memo: dict

    # Absolute path of the written {TICKER}_{DATE}_clean_memo.json.
    clean_memo_path: str

    # Full data-quality disclosure document (markdown): stale XBRL tags,
    # validation warnings/failures, metric availability, QC report + status,
    # style check, and the run-cost block. Written on export AND on halt
    # paths — a halted run still owes an explanation.
    compliance_audit_log: str

    # Absolute path of the written {TICKER}_{DATE}_compliance_audit_log.md.
    compliance_audit_log_path: str
