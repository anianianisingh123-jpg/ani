# Master Architecture Specification: Financial Multi-Agent System (MAS)

## 0. Collaboration Protocol (MANDATORY — applies to every agent in this repo)

Full protocol: `AGENTS.md` (repo root). Live engineering state: `mas_sector_system/DEV_SCRATCHPAD.md`.

- **Rule 1 — Read First.** Before starting ANY task, read `mas_sector_system/DEV_SCRATCHPAD.md` for recent changes, active schemas/data contracts, the task queue, and notes left by other agents. Do not start from the code alone.
- **Rule 2 — Isolated Edits.** Stay within your assigned module boundary (ownership table is in the scratchpad). **Do not modify core orchestration logic — `main.py` graph topology/edges or `routing.py` — unless explicitly assigned.** Changing `state.py` is a shared-contract change: announce it in the scratchpad before editing. If a task seems to need an out-of-boundary edit, stop and log `BLOCKED` rather than widening scope. The hard invariants in this spec (no `red_team_node`, no `qc_style_check`, single-parent analysis path, QC-never-edits-the-memo, deterministic valuation math, free-source market data) require an explicit product decision to override.
- **Rule 3 — Log When Done.** On completing a task or hitting a blocker, append to the "Agent Activity & Handoff Logs" section of `mas_sector_system/DEV_SCRATCHPAD.md` (append at the bottom; never rewrite another agent's entry), and update the task's row in the Active Task Queue:

```markdown
### [TIMESTAMP] - [AGENT_NAME] - [TASK_ID/NAME]
- What I changed:
- Files modified:
- Notes / Handoff for next agent:
- Status: [COMPLETED / BLOCKED / IN_PROGRESS]
```

Related docs: `mas_sector_system/AI_SYNC.md` holds cross-vendor design discussion and run post-mortems (narrative); the scratchpad holds the live task board. Keep the architecture description in one place and link, rather than forking it across files.

## 1. System Objective & Architecture
The system operates in two distinct modes managed by a Supervisor Router:
- Mode 1: "The Radar" (Top-Down Screener): Takes sector-level queries (e.g., sector="Financials") and scans for high-conviction shortlists using financial APIs.
- Mode 2: "The Sniper" (Bottom-Up Deep Dive): Runs an adversarial deep-dive analysis on a single ticker (e.g., ticker="QCOM" / "NVDA").

## 2. State Schema (`state.py`)
`ResearchState` holds end-to-end memory for a run:
- Base Inputs: `mode` ("screener" | "deep_dive"), `ticker`, `sector`, `user_query`
- Foundation: `business_overview`, `income_statement`, `balance_sheet`, `cash_flow_statement`, `sec_filing_summary`, `macro_context`, `macro_regime_assessment`, `management_assessment`, `capital_allocation_assessment`
- Adversarial Debate: `bull_thesis`, `bear_thesis`
- Valuation: `fundamental_valuation` (Python DCF + narrative), `relative_valuation` (yfinance peer comps + narrative), plus the **structured engine output** the narratives are written from: `dcf_engine` (`compute_dcf_from_state`) and `comps_engine` (`fetch_peer_multiples`). These were previously computed, formatted into the prompt, and discarded; they are now kept so downstream artifacts can chart the numbers instead of re-deriving them from prose.
- Final Output: `final_memo` (raw synthesis, preserved permanently), `styled_memo` (light format pass)
- Split deliverables (`artifacts.py`): `clean_memo` / `clean_memo_path` (thesis-only JSON parsed deterministically from `final_memo`) and `compliance_audit_log` / `compliance_audit_log_path` (all data-quality disclosures). **Never merge these back into one document.**
- QC / Review: `qc_report`, `qc_status` (`PASS` | `PASS_WITH_FLAGS` | `FAIL`)
- Cost: `cost_report` (memo appendix), `cost_data` (structured per-node figures; also appended to `outputs/cost_log.jsonl`)
- Long-term memory (`memory.py` / SQLite `outputs/research_memory.sqlite`): `prior_run_id`, `prior_run_meta`, `prior_run_context` loaded at deep_dive start; saved on export / QC halt. Backfill: `python -m mas_sector_system.memory --backfill`. Keep all runs forever.
- Market structure (free sources only, via `metrics_compute`): options put/call (yfinance chains), insider open-market heuristic + SEC Form 4 filing count — no paid vendors.

## 3. Execution Pipeline Topology (`main.py` & `agents.py`)
- Screener Branch: entry → `screener` → END
- Deep Dive Branch:

```
entry → deep_dive_start
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

Notes:
- There is **no** `red_team_node` (dropped by design; do not restore).
- There is **no** `qc_style_check` layer (removed — style is format-only; export follows style_pass).
- Analysis path is **single-parent** after capital (bull has one parent). Multi-parent fan-in was causing 2× agent runs; do not reintroduce multi-parent analysis barriers without idempotency guards.
- `macro_regime` runs its **own** Tavily search (independent of `data_gatherer`) and writes `macro_regime_assessment` using a three-lens framework: debt-cycle positioning → reflexivity → sector-specific cycle, closing with TAILWIND / HEADWIND / NEUTRAL + confidence.
- `management_track_record` runs its **own** Tavily search in parallel at entry and writes `management_assessment` (people/leadership only — not cash deployment).
- `capital_allocation` waits for validation + management + overview + macro, scores five uses of cash from canonical metrics + cash-flow numbers, and writes `capital_allocation_assessment` (with alignment cross-check vs management).
- **QC never silently edits the memo.** It only reports.
  - `qc_node` (Opus): full audit of `final_memo` vs all upstream agents. Console always prints status, severity counts, and upstream coverage.
  - **PASS** → style pass → docx. **PASS_WITH_FLAGS** → style pass → docx; QC findings go to the compliance audit log, **not** appended to the memo body. **FAIL** → one synthesis retry with the QC report as correction instructions, then re-QC; if still FAIL, hard stop (no docx, audit log still written).
- **Output routing is split by audience** (`artifacts.py`, no graph node — called from the terminal nodes):
  - `outputs/{TICKER}_{DATE}_clean_memo.json` — **schema 1.1.** Thesis only: business overview, recommendation, macro positioning, management/capital allocation, key debate, valuation reconciliation, catalysts/risks. Parsed from **`final_memo`**, never `styled_memo` (the style pass renames headers, so heading-keyed parsing over it is nondeterministic). Absent sections are `null` + listed in `sections_missing`; unrecognized sections are preserved under `unmapped_sections`. Only `full_memo` synthesis mode yields all seven sections.
    - **Heading hierarchy:** the section boundary is the shallowest ATX depth used more than once. Sub-headings below it stay inside their parent's text and are indexed under `subsections`; a lone shallower heading is the document `title`, not a section. Treating every heading as a boundary orphaned real content into `unmapped_sections`.
    - **Numeric blocks:** `metrics` carries every canonical record that is applicable and has a value; `valuation` carries structured `dcf` + `comps`. **Metric values are thesis content; statements about their reliability are not.** A metric flagged stale is *omitted outright* rather than caveated, and engine warnings, peer exclusions, and methodology notes are stripped here and re-emitted in the audit log. Never caveat in the clean memo — drop, and disclose in the log.
  - `outputs/{TICKER}_{DATE}_compliance_audit_log.md` — stale XBRL tag warnings (walked from `canonical_metrics[*].staleness`), validation gate warnings/failures/checks, metric availability, QC report + status, style check, **valuation-engine disclosures (§5)**, run cost (§6). Written on export **and** on `qc_halt` / `validation_halt`, where it is the only artifact.
  - `pdf_generator.py` renders the clean memo as a designed deck (tearsheet, football-field valuation, peer dot-plots, capital/market structure, bull-vs-bear spread, long-form behind). Charts are native fpdf2 vector primitives — **no charting dependency**. It consumes `clean_memo.json` only and is currently CLI-only; no graph node calls it.
  - The .docx carries thesis content plus a one-line pointer to the audit log; the run-cost block stays appended per §7.
- Valuation math is **deterministic** (`valuation_engine.py`): multi-stage FCF DCF + yfinance peer comps. Peer lists prefer **sector** peers (e.g. Semiconductors → AMD/AVGO/TSM) over mega-cap tech. Subject standalone multiples prefer **canonical_metrics** over Yahoo when available.
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
| Analytical writers | `business_overview`, `macro_regime`, `management_track_record`, `capital_allocation`, `bull`, `bear`, `fundamental`, `relative`, `screener`, `style_pass` | Claude Sonnet (`claude-sonnet-5`) |
| Senior writer / gate | `synthesis`, `qc` | Claude Opus (`claude-opus-5`) |
| Router | entry / `route_by_mode` / QC routers | Deterministic code — no LLM |

**Historical note:** An earlier CLAUDE.md revision mapped workers to Claude Haiku 4.5 and included a Sonnet/Opus red-team critic. That mapping was from a pre–SEC/deep-dive rework compliance pass and is **not** current. Do not silently downgrade bull/bear/overview to Haiku without an explicit product decision. Red team was deliberately removed.

## 6. Valuation Engine (`valuation_engine.py`)
- **DCF:** Base FCF from SEC cash-flow tags → high-growth years (capped YoY) → linear fade → Gordon terminal. Sector-default WACC / terminal growth. Equity value = EV − net debt when tags allow. EPV cross-check.
- **Comps:** Sector peer list preferred (then archetype), yfinance peer multiples (`trailingPE`, `forwardPE`, `enterpriseToEbitda`, `priceToSales`, etc.), peer medians, cheap/fair/rich read. Subject trailing multiples prefer canonical SEC-derived metrics when present.
- Agents must treat engine tables + canonical metrics as source of truth for numbers; they may not invent peer multiples or substitute fair values from training memory.

## 7. Cost Accounting (`cost.py`)
- Configurable `MODEL_PRICING` ($/1M tokens: input, output, cache_write, cache_read) and `TAVILY_PRICE_PER_SEARCH`.
- Tracker starts at `deep_dive_start` / screener entry; every `_invoke` and Tavily/SEC call records usage.
- Finalize on docx export or QC halt paths: console table (cost-desc), state fields, JSONL append.
- Sonnet intro pricing caveat: update the table after 2026-08-31 if list prices move to $3/$15.
