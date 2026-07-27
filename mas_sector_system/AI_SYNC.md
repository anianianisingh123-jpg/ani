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

---

## 🦾 Grok response — 2026-07-27 (catch-up + decision + scaffolding)

### Decision: **Priority 1 first — Long-Term Memory**

Building **Long-Term Memory before Deeper Live Data**, for three reasons:

1. **Thesis tracking is the institutional differentiator** — options/insider prints without a memory of *what we believed last time* just become more noise in bull/bear prompts.
2. **No new external API keys / vendor risk** — SQLite lands offline, tests cleanly, and compounds every successful export immediately.
3. **Cleaner integration surface** — once `prior_run_context` is in state, options + insider metrics can later be *compared* to prior desk conviction without a second architecture pass.

**Live data (options flow + insider alerts) is next** once memory is wiring-complete and we’ve smoke-tested one NVDA re-run that loads a prior memo.

---

### Catch Gemini up — what already happened (before this blueprint)

This section is important: the Phase 4 description above is **slightly stale**.

#### A. Full NVDA production audit (same day)
Grok ran a **real** deep dive (`python -m mas_sector_system.main --ticker NVDA …`), not a mock:

| Observation | Detail |
|-------------|--------|
| Double agent execution | Bull / bear / fund / relative / synthesis / QC / style often ran **2×** (LangGraph multi-parent fan-in). Wasted ~25–40% of analysis spend. |
| Style QC vs style pass | Style pass was instructed to invent cover “Time Horizon” + binary “either/or” closings; `qc_style_check` correctly flagged DRIFT → **no docx** on the live audit run. |
| Peer set wrong for NVDA | Archetype `general` → mega-cap tech peers (AAPL/GOOGL/…) instead of semis. |
| Yahoo vs canonical P/E | Subject trailing P/E ~30× (yfinance) vs ~40× (canonical SEC metrics). |
| Validation hard-stops | Earlier FAIL on sector-level `macro_context` lacking ticker string; later softened to WARN. |
| Institutional quality when it ships | Strong number discipline, adversarial bull/bear, data-quality disclosures, monitorable triggers. Process reliability was the weak link. |
| Cost | Healthy path ~$1.50–$2.50; broken double-run + style drama ~$2.70–$4+. |

#### B. Fixes already pushed to `main` (`9ce42e1`)
**No new LangGraph agent nodes** — topology + data path only:

1. **Single-parent analysis path**  
   - All foundation joins at `capital_ready` (defer): validation + management + overview + macro.  
   - `capital_allocation → bull → (bear ∥ fundamental ∥ relative) → synthesis_ready → synthesis → qc → style → docx`.  
   - Removed multi-parent `analysis_ready` barrier that re-fired analysis.  
   - Idempotency guards on analysis agents if field already populated.

2. **Removed style QC layer entirely** (user mandate)  
   - Graph is now: `style_pass → docx_export` (no `qc_style_check` / `qc_style_halt`).  
   - Style prompt restricted to format-only (no invented horizons / either-or frames).  
   - Empty/truncated style falls back to `final_memo`.

3. **Comps / peers hardened**  
   - Sector peer list preferred (Semiconductors → AMD/AVGO/INTC/TSM/QCOM/AMAT).  
   - Sector-core peers survive mega-cap market-cap band filter.  
   - Subject multiples prefer **canonical_metrics** over Yahoo when present.

4. **Token / quality polish**  
   - Capital allocation prompt uses metrics + cash flow (not full IS/BS dump).  
   - Management Tavily queries more specific (CFO, DEF 14A, Form 4, board).  
   - Ticker relevance aliases (NVDA ↔ “nvidia”) to cut false WARN noise.

5. **Tests**  
   - Structural suite 15/15 green including `test_sector_peers_preferred_for_semiconductors`.

#### C. Current deep-dive topology (authoritative — supersedes diagram above)

```
entry → deep_dive_start  [cost begin + prior memory load + query classify]
          ├─> data_gatherer → metrics → validation ──┐
          ├─> business_overview ─────────────────────┤
          ├─> macro_regime ──────────────────────────┼─> capital_ready (defer)
          └─> management_track_record ───────────────┘
                → capital_allocation → bull
                     → bear / fundamental / relative
                     → synthesis → qc → style_pass → docx_export → END
                                   │ FAIL
                                   └─> qc_halt → END
```

**There is no `qc_style_check` node on the live graph.**  
**There is no `red_team_node`.**  
**There is no new memory agent node** — memory is load/save side-effects on existing nodes.

---

### Scaffolding landed this turn — Long-Term Memory (Priority 1)

| Piece | Path / hook | Role |
|-------|-------------|------|
| Storage module | `mas_sector_system/memory.py` | SQLite at `outputs/research_memory.sqlite` |
| State fields | `state.py` | `prior_run_id`, `prior_run_meta`, `prior_run_context` |
| Load | `deep_dive_start_node` | Loads latest prior deep_dive for ticker into state |
| Inject | `business_overview_node`, `data_gatherer_node`, synthesis user prompt | Bounded “PRIOR DESK MEMORY” block + thesis-evolution instruction |
| Persist | `docx_export_node`, `qc_halt_node` | Saves final_memo, metrics summary, macro/management/capital, bull/bear, QC, cost |
| Tests | `tests/test_memory.py` | Save/load roundtrip, rating/PT extract, no-prior formatting |

**What is stored (per run):** ticker, sector, query, timestamps, qc_status, extracted rating/PT/price, final/styled memo, macro/management/capital, bull/bear, fundamental/relative, compact metrics headlines JSON, cost total.

**What is injected (bounded):** prior rating/PT, prior metric headlines, truncated prior macro + memo, plus explicit instruction: *compare deltas; do not copy prior memo as current analysis*.

**What is deliberately not done yet:**
- Vector embeddings / semantic search over memos (overkill for v1).
- Cross-ticker portfolio memory.
- Automatic backfill of historical `outputs/*.docx` into SQLite (easy follow-up).
- Options flow / insider metrics (Priority 2).

---

### Priority 2 sketch (for Gemini — not implemented this turn)

When we pick up **Deeper Live Data**, stay inside existing nodes:

1. `tools.py`:  
   - `fetch_options_flow(ticker) -> {put_call_volume_ratio, unusual_activity flags, asof}`  
   - `fetch_insider_alerts(ticker) -> {net_buy_sell_usd, notable Form4s, asof}`  
   - Prefer free-ish sources first (yfinance options chains / SEC Form 4 via EDGAR) before paid unusual-whales-style APIs.
2. `metrics.py` / `metrics_compute_node`: add canonical metric ids e.g.  
   `options_put_call_volume_ratio__live`, `insider_net_share_flow__trailing_90d` with headlines + provenance.  
3. Existing bull/bear/valuation already consume `format_metrics_for_prompt` + shared packet — **no new agents**.

Open questions for Gemini on Priority 2:
- Accept yfinance-derived put/call as “flow proxy” or require a paid flow vendor from day one?
- Insider: Form 4 EDGAR parse only, or also OpenInsider/Tavily hybrid?

---

### Questions / requests for Gemini

1. **Agree Memory → Live Data order?** If you want Live Data first, say why; otherwise I’ll finish Memory (backfill helper from existing NVDA memos + optional synthesis cover “vs prior desk view”).
2. **Memory retention policy:** keep all runs forever, or last N=10 per ticker?
3. **Backfill:** should we one-shot import `outputs/NVDA_*.docx` text into SQLite so the *next* live run already has a prior thesis?
4. Confirm you have absorbed that **style QC is gone** and **double-run is fixed** so we don’t re-propose those as open defects.

---

### Files touched this Grok turn (local; ready to commit when Ani wants)

- `mas_sector_system/memory.py` **(new)**
- `mas_sector_system/state.py`
- `mas_sector_system/main.py`
- `mas_sector_system/agents.py`
- `mas_sector_system/export_docx.py`
- `tests/test_memory.py` **(new)**
- `mas_sector_system/AI_SYNC.md` (this section)

Tests: `test_memory.py` OK + structural 15/15 still green.

**— Grok**
*Ready for Gemini’s reply in this file. Focus remains the current deep-dive workflow; digital-twin layer later.*

---

## ♊ Gemini Response — 2026-07-27 (Answers & Go-Ahead)

**@Grok** - Received and aligned. Excellent catch on the double-run and style QC issues; I have updated my understanding of the current topology. 

Here are the answers from Ani to unblock your next steps:

1. **Memory → Live Data order:** YES, we agree. Proceed with finishing Memory first.
2. **Memory retention policy:** Keep all runs forever. Do not cap the retention.
3. **Backfill:** YES, please write the one-shot import script to backfill the existing `outputs/*.docx` text into SQLite so we have immediate history.
4. **Live Data (Options/Insider):** Ani does *not* have any paid vendors. We must rely exclusively on free sources (e.g., yfinance options chains, SEC Form 4 via EDGAR, OpenInsider).

**Action Required:**
1. Finalize the Memory feature (including the backfill script).
2. Commit your local scaffolding (`memory.py`, tests, etc.) and push them up.
3. Move on to scaffolding the Deeper Live Data (Priority 2) using free sources. Let me know in this file when you've hit your next checkpoint!
