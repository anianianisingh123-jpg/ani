# Master Architecture Specification: Financial Multi-Agent System (MAS)

## 1. System Objective & Architecture
The system operates in two distinct modes managed by a Supervisor Router:
- Mode 1: "The Radar" (Top-Down Screener): Takes sector-level queries (e.g., sector="Financials") and scans for high-conviction shortlists using financial APIs.
- Mode 2: "The Sniper" (Bottom-Up Deep Dive): Runs an adversarial deep-dive analysis on a single ticker (e.g., ticker="QCOM" / "NVDA").

## 2. State Schema (`state.py`)
`ResearchState` holds end-to-end memory for a run:
- Base Inputs: `mode` ("screener" | "deep_dive"), `ticker`, `sector`, `user_query`
- Foundation: `business_overview`, `income_statement`, `balance_sheet`, `cash_flow_statement`, `sec_filing_summary`, `macro_context`, `macro_regime_assessment`, `management_assessment`, `capital_allocation_assessment`
- Adversarial Debate: `bull_thesis`, `bear_thesis`
- Valuation: `fundamental_valuation` (Python DCF + narrative), `relative_valuation` (yfinance peer comps + narrative)
- Final Output: `final_memo` (raw synthesis, preserved permanently), `styled_memo` (light style pass)
- QC / Review: `qc_report`, `qc_status` (`PASS` | `PASS_WITH_FLAGS` | `FAIL`), `qc_style_report`, `qc_style_status` (`CLEAN` | `DRIFT_DETECTED`)
- Cost: `cost_report` (memo appendix), `cost_data` (structured per-node figures; also appended to `outputs/cost_log.jsonl`)

## 3. Execution Pipeline Topology (`main.py` & `agents.py`)
- Screener Branch: entry → `screener` → END
- Deep Dive Branch:

```
entry → deep_dive_start
          ├─> data_gatherer ──────────────┐
          ├─> business_overview ──────────┤
          ├─> macro_regime ───────────────┼─> bull / bear / fundamental / relative
          └─> management_track_record ─┐  │
                                       └─> capital_allocation ─┘
              → synthesis → qc → style_pass → qc_style_check → docx_export → END
                            │ FAIL                          │ DRIFT
                            └─> qc_halt → END               └─> qc_style_halt → END
```

Notes:
- There is **no** `red_team_node` (dropped by design; do not restore).
- `macro_regime` runs its **own** Tavily search (independent of `data_gatherer`) and writes `macro_regime_assessment` using a three-lens framework: debt-cycle positioning → reflexivity → sector-specific cycle, closing with TAILWIND / HEADWIND / NEUTRAL + confidence.
- `management_track_record` runs its **own** Tavily search in parallel at entry and writes `management_assessment` (people/leadership only — not cash deployment).
- `capital_allocation` waits for `data_gatherer` + `management_track_record`, scores five uses of cash from statement numbers, and writes `capital_allocation_assessment` (with alignment cross-check vs management).
- **QC never silently edits the memo.** It only reports.
  - `qc_node` (Opus): full audit of `final_memo` vs all upstream agents. Console always prints status, severity counts, and upstream coverage.
  - **PASS** → style pass. **PASS_WITH_FLAGS** → style pass; QC Notes appended to the docx. **FAIL** → one synthesis retry with the QC report as correction instructions, then re-QC; if still FAIL, hard stop (no docx).
  - `qc_style_check` (Sonnet): compares pre-style `final_memo` vs post-style `styled_memo`. **CLEAN** → export. **DRIFT_DETECTED** → hard stop (no docx).
- Valuation math is **deterministic** (`valuation_engine.py`): multi-stage FCF DCF + yfinance peer multiples. LLM agents narrate those outputs.
- LLM calls disable extended thinking by default and retry once on empty / truncated text.
- **Cost accounting** (`cost.py`): every LLM call records tokens, cache, duration, and estimated USD via a configurable `MODEL_PRICING` table. Tavily search count and SEC EDGAR call count are tracked. Console prints a cost-sorted table every run; a condensed "Run Cost" block is appended to every memo (unconditional). Cross-run lines go to `outputs/cost_log.jsonl`. Estimates ≠ billed amounts.

## 4. Dynamic Sector Prompt Injection
When an agent node runs, it may use `state["sector"]` for valuation defaults (WACC, peer sets) and narrative focus:
- Technology / Semiconductors: SaaS-like margins where applicable, R&D intensity, DCF, peer P/E and EV/EBITDA.
- Financials: NIM, loan-to-deposit, residual income / P/B (FCF DCF is a poor primary method for banks).
- Energy: NAV, reserve replacement, mid-cycle normalization, commodity correlations.

## 5. Multi-Model Tiering Logic (current — Anthropic)
| Role | Nodes | Model |
|------|--------|--------|
| Heavy foundation | `data_gatherer` | Claude Opus (`claude-opus-5`) |
| Analytical writers | `business_overview`, `macro_regime`, `management_track_record`, `capital_allocation`, `bull`, `bear`, `fundamental`, `relative`, `screener`, `style_pass`, `qc_style_check` | Claude Sonnet (`claude-sonnet-5`) |
| Senior writer / gate | `synthesis`, `qc` | Claude Opus (`claude-opus-5`) |
| Router | entry / `route_by_mode` / QC routers | Deterministic code — no LLM |

**Historical note:** An earlier CLAUDE.md revision mapped workers to Claude Haiku 4.5 and included a Sonnet/Opus red-team critic. That mapping was from a pre–SEC/deep-dive rework compliance pass and is **not** current. Do not silently downgrade bull/bear/overview to Haiku without an explicit product decision. Red team was deliberately removed.

## 6. Valuation Engine (`valuation_engine.py`)
- **DCF:** Base FCF from SEC cash-flow tags → high-growth years (capped YoY) → linear fade → Gordon terminal. Sector-default WACC / terminal growth. Equity value = EV − net debt when tags allow. EPV cross-check.
- **Comps:** Subject + sector peer list via yfinance (`trailingPE`, `forwardPE`, `enterpriseToEbitda`, `priceToSales`, etc.), peer medians, cheap/fair/rich read.
- Agents must treat engine tables as source of truth for numbers; they may not invent peer multiples or substitute fair values from training memory.

## 7. Cost Accounting (`cost.py`)
- Configurable `MODEL_PRICING` ($/1M tokens: input, output, cache_write, cache_read) and `TAVILY_PRICE_PER_SEARCH`.
- Tracker starts at `deep_dive_start` / screener entry; every `_invoke` and Tavily/SEC call records usage.
- Finalize on docx export or QC halt paths: console table (cost-desc), state fields, JSONL append.
- Sonnet intro pricing caveat: update the table after 2026-08-31 if list prices move to $3/$15.
