# MAS Development Scratchpad & Task Log

> **Purpose:** asynchronous, file-based coordination surface for every agent working in this repo
> (Claude, Gemini, Grok, sub-agents, humans). Read it before you start. Append to it when you finish.
>
> **Scope split:**
> - `DEV_SCRATCHPAD.md` (this file) — *live engineering state*: contracts, task queue, handoff logs.
> - `AI_SYNC.md` — *narrative cross-vendor design discussion* and run post-mortems (NVDA E2E, etc.). Do not duplicate long prose here; link to it.
> - `CLAUDE.md` / `AGENTS.md` (repo root) — *durable architecture spec + protocol rules*. Changes there require an explicit product decision, not a scratchpad note.

*Created: 2026-07-28 · Protocol version: 1.0*

---

## 📋 Active Architecture & Data Contracts

Quick reference for all agents. **Authoritative spec is `CLAUDE.md`; this is the working cheat sheet.**

### Module boundaries (own your lane — see Rule 2)

| Module | Owns | Do not edit unless assigned |
|--------|------|-----------------------------|
| `main.py` | LangGraph topology, node registration, CLI entry | **Core orchestration — assignment required** |
| `routing.py` | Deterministic mode/QC routers | **Core orchestration — assignment required** |
| `state.py` | `ResearchState` TypedDict | **Shared contract — announce before changing** |
| `agents.py` | All LLM node bodies + prompts (~98 KB) | Per-node edits OK |
| `tools.py` | SEC EDGAR / XBRL fetch, Tavily, yfinance, options, insider | Per-function edits OK |
| `metrics.py` | `compute_canonical_metrics`, prompt formatting | Per-function edits OK |
| `valuation_engine.py` | DCF, EPV, peer comps | Deterministic math only |
| `validate.py` | Hard validation gate | Per-rule edits OK |
| `memory.py` | SQLite long-term memory (`outputs/research_memory.sqlite`) | Per-function edits OK |
| `cost.py` | Token/USD accounting, `MODEL_PRICING`, JSONL log | Pricing table = product decision |
| `export_docx.py` | Markdown → `.docx` renderer + `docx_export_node` | Per-function edits OK |
| `archetype.py`, `concept_maps.py` | Sector archetypes, XBRL concept aliases | Per-entry edits OK |
| `tests/` (repo root) | pytest suite | Additive only — don't delete coverage |

### Deep-dive topology (authoritative, matches `main.py`)

```
entry → deep_dive_start
          ├─> data_gatherer → metrics_compute → validation_gate ─┬─> validation_halt → END
          │                                                      └─> post_validation ─┐
          ├─> business_overview ───────────────────────────────────────────────────────┤
          ├─> macro_regime ────────────────────────────────────────────────────────────┼─> capital_ready (defer=True)
          └─> management_track_record ─────────────────────────────────────────────────┘
                → capital_allocation → bull_agent
                     ├─> bear_agent ────────────┐
                     ├─> fundamental_valuation ─┼─> synthesis_ready (defer=True) → synthesis → qc
                     └─> relative_valuation ────┘                                              │
                                                    ┌── PASS / PASS_WITH_FLAGS ────────────────┤
                                                    │                                          │ FAIL
                                            style_pass → docx_export → END              qc_halt → END
```

Screener branch: `entry → screener → END`.

**Hard invariants — do not violate without a product decision:**
1. **No `red_team_node`.** Removed by design. Do not restore.
2. **No `qc_style_check` layer.** Style is format-only; export follows `style_pass`.
3. **Analysis path is single-parent after capital** (`bull_agent` has exactly one parent). Multi-parent fan-in previously caused 2× agent execution (~25–40% wasted spend). Barriers must stay `defer=True` passthroughs.
4. **QC never silently edits the memo.** It reports only. `FAIL` → one synthesis retry with the QC report as correction instructions → re-QC → hard stop (no docx) if still `FAIL`.
5. **Valuation math is deterministic Python.** Agents narrate `valuation_engine` + `canonical_metrics`; they never invent peer multiples or fair values from training memory.
6. **Market-structure data is free-source only** (yfinance chains, SEC Form 4 counts). No paid vendors.

### Data contracts

- **`ResearchState`** (`state.py`) — single dict passed between nodes. Key groups: base inputs (`mode`, `ticker`, `sector`, `user_query`); foundation (`business_overview`, statements, `sec_filing_summary`, `macro_context`, `macro_regime_assessment`, `management_assessment`, `capital_allocation_assessment`); debate (`bull_thesis`, `bear_thesis`); valuation (`fundamental_valuation`, `relative_valuation`); output (`final_memo` — *preserved permanently*, `styled_memo`); QC (`qc_report`, `qc_status` ∈ `PASS | PASS_WITH_FLAGS | FAIL`); cost (`cost_report`, `cost_data`); memory (`prior_run_id`, `prior_run_meta`, `prior_run_context`).
- **`canonical_metrics`** (`metrics.py`) — source of truth for every number an agent quotes. Each entry carries value + provenance + staleness. Subject multiples prefer canonical over Yahoo.
- **SEC layer** (`tools.py`) — `get_cik_for_ticker` → `fetch_sec_company_facts` (XBRL companyfacts) → `extract_statements_from_company_facts`. Rate-limited via `_sec_rate_limit()`; UA from `_sec_user_agent()`. Concept aliasing lives in `concept_maps.py`, archetype-derived lines in `archetype.py`.
- **Memory** — SQLite at `outputs/research_memory.sqlite`. Loaded at `deep_dive_start`, saved on export **and** on QC halt. Backfill: `python -m mas_sector_system.memory --backfill`. **Keep all runs forever.**
- **Cost** — every `_invoke` records tokens/cache/duration/USD; Tavily + SEC call counts tracked; console table each run; condensed block appended to every memo; cross-run lines to `outputs/cost_log.jsonl`. Estimates ≠ billed.

### Model tiering (Anthropic)

| Role | Nodes | Model |
|------|-------|-------|
| Heavy foundation | `data_gatherer` | `claude-opus-5` |
| Analytical writers | `business_overview`, `macro_regime`, `management_track_record`, `capital_allocation`, `bull`, `bear`, `fundamental`, `relative`, `screener`, `style_pass` | `claude-sonnet-5` |
| Senior writer / gate | `synthesis`, `qc` | `claude-opus-5` |
| Routers | entry / `route_by_mode` / QC routers | Deterministic code — no LLM |

Do **not** downgrade writers to Haiku without an explicit product decision (see the historical note in `CLAUDE.md`).

### Known open issues (carried from `AI_SYNC.md` NVDA E2E, 2026-07-28)

1. Stale XBRL tags persist (~15 lines) — structural SEC tag lag on STI/interest.
2. Routing keyword miss — "compare to prior desk view" defaults to `full_underwrite` (noisy, harmless).
3. `style_pass` costs ~$0.15 / ~12k output tokens because it re-emits the whole memo.
4. QC input packet ~77k tokens — largest cost/latency hotspot.
5. Docx filename uses local date; a 00:xx UTC run can be labeled the prior day.
6. Unusual-options flag fires on liquid mega-caps; agents must keep hedging it.
7. No Form 4 dollar parse — count-only by design for v1.

---

## 📌 Active Task Queue

Status legend: `TODO` · `IN_PROGRESS` · `BLOCKED` · `DONE`
Claim a task by putting your agent name in **Assignee** and setting `IN_PROGRESS`, then log it below when you stop.

### Epic A — PDF Generation Engine (`export_pdf.py`)

`fpdf2>=2.7.6` is already in `requirements.txt` but unused. `export_docx.py` is the reference implementation to mirror — same markdown subset, same node contract.

| ID | Task | Assignee | Status |
|----|------|----------|--------|
| PDF-01 | Create `mas_sector_system/export_pdf.py` skeleton: `markdown_to_pdf()`, `export_styled_memo_pdf()`, `pdf_export_node(state)`. Mirror `export_docx.py` signatures exactly. | _unassigned_ | TODO |
| PDF-02 | Port the markdown subset already handled by docx: ATX headings (levels 1–3), pipe tables w/ separator row, bullet/numbered lists, `**bold**` / `*italic*` inline runs, horizontal-rule skip. Reuse the regexes in `export_docx.py:19-21` — factor them into a shared `_markdown_common.py` rather than copy-pasting. | _unassigned_ | TODO |
| PDF-03 | Page furniture: 0.9"/1.0" margins to match docx, page numbers, memo header (ticker + as-of date), and a page-break-aware table renderer (fpdf2 tables do not auto-split — this is the main risk). | _unassigned_ | TODO |
| PDF-04 | Node parity: append `## QC Notes` on `PASS_WITH_FLAGS`, always append the cost block via `append_cost_to_memo`, call `finalize_run_cost` exactly **once** per run, and `save_run` for memory. **Do not double-finalize** if both docx and pdf nodes run. | _unassigned_ | TODO |
| PDF-05 | Wire into `main.py` — **core orchestration, requires assignment.** Proposal: keep `docx_export` as the terminal node and have it call the PDF writer inline, controlled by a `--pdf` CLI flag. Avoids adding a graph node and avoids the double-finalize hazard. | _unassigned_ | TODO |
| PDF-06 | Unicode: fpdf2's core fonts are latin-1 only. Memos contain em-dashes, arrows, and `≈`/`×`. Either register a DejaVu TTF or add a sanitizer. Decide and document. | _unassigned_ | TODO |

### Epic B — SEC Data Parser hardening (`tools.py` / `concept_maps.py` / `metrics.py`)

| ID | Task | Assignee | Status |
|----|------|----------|--------|
| SEC-01 | Fix the ~15 stale XBRL tags (short-term investments, interest expense) flagged in the NVDA E2E. Add fallback aliases in `concept_maps.py` and confirm `_pick_period` isn't silently selecting an old frame. | _unassigned_ | TODO |
| SEC-02 | Add explicit staleness surfacing: when a canonical metric is > 1 reporting period old, make `format_metrics_for_prompt` label it inline so bull/bear cannot quote it as current. (`_staleness_for_line` already computes this — it needs to reach the prompt.) | _unassigned_ | TODO |
| SEC-03 | Harden `_extract_statement_block` / `_extract_line` against missing-tag companies (financials and energy differ most from the tech archetype). Add a golden-file test per sector archetype. | _unassigned_ | TODO |
| SEC-04 | Form 4 dollar-value parse (currently count-only, `_form4_from_sec_submissions`). Optional for v1 — parse transaction value from the Form 4 XML, keep the count as a fallback. | _unassigned_ | TODO |
| SEC-05 | Cache + rate-limit audit: confirm `_sec_rate_limit()` holds under the parallel foundation phase (four nodes can hit EDGAR concurrently) and that `.cache/` invalidation is correct. | _unassigned_ | TODO |

### Epic C — Test Harness (`tests/`)

Existing: `test_market_structure.py`, `test_memory.py`, `test_structural_phases.py`, `test_us_sector_coverage.py` at the **repo root** `tests/`. Note `mas_sector_system/tests/` exists but is empty — pick one location and kill the other.

| ID | Task | Assignee | Status |
|----|------|----------|--------|
| TEST-01 | Consolidate test location (recommend repo-root `tests/`, delete the empty `mas_sector_system/tests/`) and add `pytest.ini`/`pyproject` config with markers: `unit`, `integration`, `live` (network), `costly` (LLM). Default run must be offline and free. | _unassigned_ | TODO |
| TEST-02 | Fixture library: frozen SEC `companyfacts` JSON for one ticker per archetype (tech, financials, energy), plus a canned `ResearchState` at each phase boundary. Store under `tests/fixtures/`. | _unassigned_ | TODO |
| TEST-03 | Deterministic-core tests with **zero LLM calls**: `compute_canonical_metrics`, `valuation_engine` DCF/EPV/comps, `validate.py` gate outcomes, `routing.py` router table. | _unassigned_ | TODO |
| TEST-04 | Topology regression test — assert the graph has exactly one parent for `bull_agent`, that `capital_ready`/`synthesis_ready` are deferred, and that no node named `red_team`/`qc_style_check` exists. This is the guard against the 2× execution bug returning. | _unassigned_ | TODO |
| TEST-05 | Export golden tests: markdown → docx and markdown → pdf over a fixture memo covering headings, tables, bullets, bold/italic, and non-latin-1 characters. Assert QC Notes and cost block appear exactly once. | _unassigned_ | TODO |
| TEST-06 | Mock-LLM harness: a fake `_invoke` returning canned text per node so the full deep-dive graph can run end-to-end in CI with no API spend, asserting state keys are populated at every phase. | _unassigned_ | TODO |
| TEST-07 | Cost-accounting test: assert `finalize_run_cost` is called exactly once per run on all three terminal paths (`docx_export`, `qc_halt`, `validation_halt`) and that `outputs/cost_log.jsonl` gets exactly one line. | _unassigned_ | TODO |

---

## 📝 Agent Activity & Handoff Logs

*Newest entries at the bottom. Append only — never rewrite another agent's entry.*

### [2026-07-28] - [Claude/Opus-5] - [SETUP-00: Collaboration protocol bootstrap]
- **What I changed:** Created this scratchpad; added the Collaboration Protocol (Rules 1–3) to a new repo-root `AGENTS.md` and to `CLAUDE.md`. Populated the architecture cheat sheet from the live code (`main.py` graph edges, `state.py`, `tools.py`, `metrics.py`, `export_docx.py`) rather than from prose, and seeded Epics A–C.
- **Files modified:** `mas_sector_system/DEV_SCRATCHPAD.md` (new), `AGENTS.md` (new, repo root), `CLAUDE.md` (protocol section added).
- **Notes / Handoff for next agent:** Two things to know. (1) `AI_SYNC.md` already exists and overlaps — it stays the narrative/post-mortem doc, this file is the live task board; don't fork the architecture description across both, link instead. (2) `fpdf2` is already a declared dependency but no PDF module exists, so Epic A is greenfield — PDF-06 (latin-1 font limitation) is the trap worth resolving before writing the renderer. No source code was touched.
- **Status:** COMPLETED
