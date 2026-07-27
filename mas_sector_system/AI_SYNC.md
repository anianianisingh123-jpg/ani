# MAS Sector System - Codebase Analysis & AI Sync
*Date: 2026-07-27*
*Initiated by: Gemini CLI*

## System Overview
The `mas_sector_system` is a highly structured, multi-agent equity research desk built on `LangGraph`. It is designed to process financial data deterministically and generate styled, adversarial investment memos.

### Core Architecture & Workflow
1. **State Management (`state.py`)**: Uses a strict `TypedDict` (`ResearchState`) to pass context between nodes. It clearly separates raw SEC data, computed metrics, macro assessments, adversarial debate (bull vs. bear), and final deliverables.
2. **Pipelines (`main.py`)**:
   - **`screener`**: A broad, single-agent sector sweep leveraging live web search (Tavily).
   - **`deep_dive`**: The primary pipeline. It is heavily parallelized. 
     - *Phase 1 (Foundation)*: Fetches SEC data, macro regime, business overview, and management track record simultaneously.
     - *Phase 2 (Validation)*: Computes canonical metrics in pure Python (no LLM math errors) and runs a hard validation gate.
     - *Phase 3 (Analysis)*: Runs Bull, Bear, Fundamental Valuation (DCF), and Relative Valuation (Comps) in parallel.
     - *Phase 4 (Deliverable)*: Synthesizes the memo, runs a substantive QC check, applies styling, and runs a final style-drift QC check before DOCX export.
3. **Model Tiering (`agents.py`)**: Smartly routes complex data extraction (like parsing XBRL JSON) to `Claude-Opus` (with large token buffers) and bounds analytical writing to `Claude-Sonnet`.
4. **Data & Math (`tools.py` & `valuation_engine.py`)**: 
   - Pulls directly from SEC EDGAR (XBRL facts) and Tavily.
   - Core valuations (DCF, WACC defaults, peer comps) are computed deterministically in Python. The LLMs are strictly instructed to narrate the math, not invent it.

## Findings & Blueprint for "Top Tier Equity Research Desk"
Per recent directives, we are focusing on hardening and elevating the current workflow into a top-tier system without introducing new agents or graph nodes right now. The immediate priorities are:

### 1. Long-Term Memory & Thesis Tracking (High Priority)
- **Current State:** The `ResearchState` is entirely ephemeral per run. The system treats every deep dive as a blank slate.
- **Goal:** Enable the desk to remember its past analysis.
- **Action Items:**
  - Introduce a database (vector or lightweight SQLite/JSON store) to archive past `final_memo`, `canonical_metrics`, and `macro_regime_assessment` outputs.
  - Inject a summary of the *previous* memo and conviction level into the `data_gatherer` or `business_overview` prompt so the agents can compare current earnings/guidance against past expectations and evaluate how the thesis has evolved over time.

### 2. Deeper Live Data Integration (High Priority)
- **Current State:** The desk uses SEC filings (XBRL), yfinance (price/market cap), and Tavily (web news).
- **Goal:** Give the analytical nodes institutional-grade context.
- **Action Items:**
  - Enhance `tools.py` to fetch Options Flow data (put/call ratios, unusual volume) and Insider Trading alerts.
  - Expand `metrics_compute_node` (and the `canonical_metrics` dictionary) to natively parse and include this real-time data.
  - Feed this richer context into the existing `fundamental_valuation`, `relative_valuation`, and `bull`/`bear` nodes to produce more sophisticated, market-aware arguments.

---

## 🤖 Handoff to Grok
**@Grok** - The strategic focus has shifted. We are strictly elevating the current desk architecture. No new agent nodes.
1. Please review the updated blueprint above focusing on **Long-Term Memory** and **Deeper Live Data**.
2. Which of these two areas should we build out the technical scaffolding for first?
3. Execute any necessary setup (e.g., scaffolding a local SQLite DB for memory or writing the API fetching stubs for options flow in `tools.py`), and leave your notes or questions below.

---
*(Grok - write your updates below here)*
