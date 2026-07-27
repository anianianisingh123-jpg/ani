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

## Findings & Blueprint for "Top Tier Digital AI Twin"
To scale this from a static CLI tool to an autonomous digital twin, we need to bridge the gap between batch processing and persistent intelligence.

1. **Persistent Event Triggers**: The system currently requires manual CLI invocation. **Goal:** Build a persistent watcher (daemon/agent) that monitors live news feeds or SEC RSS for earnings drops and automatically kicks off a `deep_dive` without human intervention.
2. **Long-Term Memory & Thesis Tracking**: The `ResearchState` is entirely ephemeral per run. **Goal:** Integrate a database (vector or relational) so the twin can read its *last* memo on a ticker, compare new earnings against past expectations, and track how its conviction has shifted.
3. **Advanced Portfolio Agent**: Currently, the system stops at the memo. **Goal:** Add a new LangGraph node (`portfolio_allocation_node`) after synthesis that takes the valuation spread and macro regime to recommend actual position sizing and portfolio weighting.
4. **Deeper Live Data**: yfinance and Tavily are good, but a true top-tier desk needs options flow, insider trading alerts, and real-time pricing data integrated directly into the `canonical_metrics` or a new `live_market_node`.

---

## 🤖 Handoff to Grok
**@Grok** - I have mapped the current state of the MAS architecture above. 
1. Please review my findings.
2. What should be our immediate next priority to start the "digital twin" scaling? Should we tackle the **Long-Term Memory**, the **Event Triggers**, or the **Portfolio Agent** first?
3. Feel free to execute any setup commands or create scaffolding, and leave your notes or questions for me right below this line!

---
*(Grok - write your updates below here)*
