# Master Architecture Specification: Financial Multi-Agent System (MAS)

## 1. System Objective & Architecture
The system operates in two distinct modes managed by a Supervisor Router:
- Mode 1: "The Radar" (Top-Down Screener): Takes sector-level queries (e.g., sector="Financials") and scans for high-conviction shortlists using financial APIs.
- Mode 2: "The Sniper" (Bottom-Up Deep Dive): Runs an adversarial deep-dive analysis on a single ticker (e.g., ticker="QCOM" / "NVDA").

## 2. State Schema (`state.py`)
`ResearchState` holds end-to-end memory for a run:
- Base Inputs: `mode` ("screener" | "deep_dive"), `ticker`, `sector`, `user_query`
- Foundation: `business_overview`, `income_statement`, `balance_sheet`, `cash_flow_statement`, `sec_filing_summary`, `macro_context`, `macro_regime_assessment`
- Adversarial Debate: `bull_thesis`, `bear_thesis`
- Valuation: `fundamental_valuation` (Python DCF + narrative), `relative_valuation` (yfinance peer comps + narrative)
- Final Output: `final_memo` (raw synthesis), `styled_memo` (light style pass)

## 3. Execution Pipeline Topology (`main.py` & `agents.py`)
- Screener Branch: entry → `screener` → END
- Deep Dive Branch:

```
entry → deep_dive_start
          ├─> data_gatherer ──────────┐
          ├─> business_overview ──────┼─> bull_agent ──────────────┐
          └─> macro_regime ───────────┤  bear_agent ──────────────┤
                                      ├─> fundamental_valuation ───┼─> synthesis → style_pass → docx_export → END
                                      └─> relative_valuation ──────┘
```

Notes:
- There is **no** `red_team_node` (dropped by design; do not restore).
- `macro_regime` runs its **own** Tavily search (independent of `data_gatherer`) and writes `macro_regime_assessment` using a three-lens framework: debt-cycle positioning → reflexivity → sector-specific cycle, closing with TAILWIND / HEADWIND / NEUTRAL + confidence.
- `macro_context` remains a short digest from `data_gatherer`; `macro_regime_assessment` is the structured cycle read. Downstream agents and synthesis consume both.
- Valuation math is **deterministic** (`valuation_engine.py`): multi-stage FCF DCF + yfinance peer multiples. LLM agents narrate those outputs.
- LLM calls disable extended thinking by default and retry once on empty / truncated text.

## 4. Dynamic Sector Prompt Injection
When an agent node runs, it may use `state["sector"]` for valuation defaults (WACC, peer sets) and narrative focus:
- Technology / Semiconductors: SaaS-like margins where applicable, R&D intensity, DCF, peer P/E and EV/EBITDA.
- Financials: NIM, loan-to-deposit, residual income / P/B (FCF DCF is a poor primary method for banks).
- Energy: NAV, reserve replacement, mid-cycle normalization, commodity correlations.

## 5. Multi-Model Tiering Logic (current — Anthropic)
| Role | Nodes | Model |
|------|--------|--------|
| Heavy foundation | `data_gatherer` | Claude Opus (`claude-opus-5`) |
| Analytical writers | `business_overview`, `macro_regime`, `bull`, `bear`, `fundamental`, `relative`, `screener`, `style_pass` | Claude Sonnet (`claude-sonnet-5`) |
| Senior writer | `synthesis` | Claude Opus (`claude-opus-5`) |
| Router | entry / `route_by_mode` | Deterministic code — no LLM |

**Historical note:** An earlier CLAUDE.md revision mapped workers to Claude Haiku 4.5 and included a Sonnet/Opus red-team critic. That mapping was from a pre–SEC/deep-dive rework compliance pass and is **not** current. Do not silently downgrade bull/bear/overview to Haiku without an explicit product decision. Red team was deliberately removed.

## 6. Valuation Engine (`valuation_engine.py`)
- **DCF:** Base FCF from SEC cash-flow tags → high-growth years (capped YoY) → linear fade → Gordon terminal. Sector-default WACC / terminal growth. Equity value = EV − net debt when tags allow. EPV cross-check.
- **Comps:** Subject + sector peer list via yfinance (`trailingPE`, `forwardPE`, `enterpriseToEbitda`, `priceToSales`, etc.), peer medians, cheap/fair/rich read.
- Agents must treat engine tables as source of truth for numbers; they may not invent peer multiples or substitute fair values from training memory.
