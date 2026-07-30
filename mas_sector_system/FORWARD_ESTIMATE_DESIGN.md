# Forward Estimates — Architecture & Work Split

**Status:** DESIGN — not approved for implementation until §15 is answered.
**Author:** Claude/Opus-5 (architect). **Date:** 2026-07-30.
**Implementers:** Gemini · Codex · Grok · Claude (see §13).
**Prerequisite:** `VALUATION_ICL_DESIGN.md` (the argued-input layer) is built and merged.
**Related:** `CLAUDE.md` · `AGENTS.md` · `DEV_SCRATCHPAD.md`.

---

## 0. Read this first

This epic is larger than the entire valuation-ICL epic. Read §2 (core principle), §5 (driver
taxonomy) and §8 (guardrails) before touching a file, plus your own row in §13.

**A forward estimate is the single easiest place in this system for a model to fabricate.** Every
number in a P&L looks plausible. The whole design exists to make fabrication structurally
impossible rather than merely forbidden. If you find yourself adding a field that can hold a
model-supplied currency amount, stop and log `BLOCKED`.

---

## 1. The gap this closes

The valuation engine currently anchors on a **single historical figure** — trailing FCF, or a
consensus forward EPS backed out of `forwardPE` — and applies argued rates to it.

That means the system can argue about a discount rate but cannot argue about **next year's
earnings**, which is where the money is made and where every real disagreement lives.

Contrast with how this desk actually works. The NVDA memo (Jul 2026) built:

```
Data center revenue $193bn → $349bn  (+81%)
Gross margin held at 75%
Opex +12% QoQ (edge compute, rack R&D)
        → EPS $8.38 → 32× → $268 target
```

Every figure descends from a named driver. That chain *is* the valuation. The system cannot
currently produce any of it.

**After this epic:** the argument becomes "will data center revenue grow 80% or 50%, and does
gross margin hold at 75%" — claims with evidence behind them that a reader can disagree with —
instead of "should the discount rate be 10% or 12.5%".

---

## 2. Core principle

The existing invariant is unchanged and now applies to a longer chain:

> **Python computes every number. The LLM argues a small set of drivers and owns no figures.**
> The LLM's output surface is bounded scalars and enums — never a currency amount.

Two properties are added:

**Few dials.** 4–8 argued drivers, depending on segment count. Errors in a P&L compound
*multiplicatively* — 10% optimistic on growth, 200bps on margin and light on opex do not add, they
multiply into an EPS that is wildly wrong. This is the same failure as the compounded-corners bug
(`VALUATION_ICL_DESIGN.md` §4.5, VAL-14) at larger scale.

> **Rule:** the driver count must stay small enough that a human reviews every one on every run.
> Anything derivable is derived. Anything second-order is held at its historical value.
> **A design that needs fifteen drivers is wrong.**

**Departure from a measured base.** Every argued driver must cite the historical figure it departs
from and state the departure. Not "growth is 25%" but "40–50% against a trend decelerating from
217% to 68%, because…". An analyst who cannot name the trend they are breaking does not have a
view, they have a guess.

---

## 3. The history foundation

Forecasting off one year is why the current system is weak. Standard practice is 3+ years of
history first, then estimates.

**This mostly exists already.** `tools.py::_extract_statement_block` emits `annual_series` at ranks
0–4 (VAL-10/VAL-12), and Codex has already ensured model-supplied statement blocks cannot erase it.
What is needed is depth and breadth.

### 3.1 Required extensions

| Change | Why |
|---|---|
| Extend `annual_series` to **8–10 ranks for cyclical archetypes** | Semis run 4–5 years peak-to-trough. Five years can be entirely one upswing, which makes "mid-cycle" a slightly smaller peak. `cyclical_commodity`, `general` (semis land here), `asset_heavy*`, `midstream`, `mortgage_reit` get 10; the rest keep 5. |
| Ensure all **three statements** carry `annual_series` | Income and cash flow exist; balance sheet is needed for working capital, book value and share count. |
| Add **segment revenue** extraction | §4. This is the foundation of the whole epic. |

### 3.2 Computed historical context (Python, no LLM)

From the series, compute and expose a `historical_profile` block. **These are facts, not
judgments, and the LLM may never override them:**

- revenue growth per year and per segment; 3y and 5y CAGR
- gross margin per year, min/max/mean, and trend direction
- opex as % of revenue per year, and its growth rate
- effective tax rate per year and its 5y mean
- capex as % of revenue; D&A as % of revenue
- working capital as % of revenue
- diluted share count trajectory and implied buyback pace
- FCF conversion (FCF / net income)

**The mechanical defaults in §5.3 are drawn from this block.** That is the point: most of the model
is set empirically with no judgment required at all.

---

## 4. Segment revenue — the least glamorous, most load-bearing piece

Companies disclose revenue by reportable segment in the 10-K segment footnote. **The revenue
drivers therefore are not chosen — they are read.** NVDA reports Data Center, Gaming, Pro
Visualization, Automotive, OEM; the only question is how fast each grows.

This is what dissolves the "hundreds of industries" problem: industry specificity is already
encoded in how each company reports itself.

**Expect this to be the hardest task in the epic.** Filers are inconsistent: segment names change
between years, segments get merged and split, and XBRL segment axes are not uniformly tagged.

Requirements:

1. Extract segment revenue per annual period into
   `income_statement.annual_series[i]["segments"] = {name: cell}`.
2. **Segment revenues must sum to consolidated revenue within 2%.** On failure, emit
   `segments_reconciled: false` and a warning, and the forecast falls back to consolidated-only
   (§10). Never silently proceed on segments that do not add up.
3. Normalise names across years where a mapping is unambiguous; where a segment appears or
   disappears, record it in `segment_changes` rather than guessing continuity.
4. Where segments cannot be extracted at all, `segments: {}` — a valid state, handled by §10.

---

## 5. Driver taxonomy — three layers

### 5.1 Layer 1 — from the filings (given, not chosen)

Revenue growth per reported segment. One driver per segment, capped at the **five largest by
revenue**; any remainder is bundled as `other` and grown at consolidated trend. Five segments plus
margin and opex already reaches the dial ceiling.

### 5.2 Layer 2 — from the archetype (16 templates, in code)

The archetype supplies the non-revenue drivers and, for financials, replaces the revenue-segment
model entirely. A bank has no gross margin; a REIT has no opex growth in the commercial sense.

| Archetype | Argued drivers | Forecast output |
|---|---|---|
| `general`, `asset_light` | segment growth, gross margin, opex growth | revenue → EBIT → EPS → FCF |
| `software_saas` | segment/subscription growth, gross margin, S&M %rev, R&D %rev | same + billings context |
| `asset_heavy`, `asset_heavy_industrial` | volume/revenue growth, gross margin, capex intensity | + capacity utilisation |
| `mature_dividend_payer` | organic growth, pricing, gross margin, opex growth | + payout ratio |
| `pre_profit_growth` | revenue growth, gross-margin trajectory, opex growth | + months of runway |
| `cyclical_commodity` | volume, realised price, unit cash cost | EBITDA → FCF |
| `midstream` | throughput volume, fee per unit, maintenance capex | EBITDA → distributable CF |
| `telecom` | subscribers, ARPU, capex intensity | EBITDA → FCF |
| `utility` | rate-base growth, allowed ROE, O&M growth | EPS → dividend |
| `bank_lender` | net interest margin, earning-asset growth, provision rate, fee-income growth, efficiency ratio | net income → EPS → book value → **residual income** |
| `insurance` | premium growth, combined ratio, investment yield | net income → book value → **ROE** |
| `equity_reit`, `reit_real_estate` | occupancy, same-store NOI growth, development yield, G&A | **FFO / AFFO** |
| `mortgage_reit` | net interest spread, leverage, book-value change | **book value per share** |

**This table is where the financials gap closes.** Banks, insurers and REITs get nothing from the
argued layer today purely because nobody wrote their driver set. Write it once, every one works.

### 5.3 Layer 3 — held mechanically (no judgment by default)

Set from `historical_profile` (§3.2), 5y mean unless noted:

effective tax rate · D&A as %revenue · capex as %revenue (unless the archetype argues it) ·
working capital as %revenue · share count (historical buyback pace) · dividend payout

An implementer may **not** promote one of these to an argued driver. Doing so requires a product
decision, because each addition multiplies the error surface (§2).

### 5.4 Layer 4 — one discretionary driver, capped at one

The critique may propose **exactly one** company-specific driver not in the template, with
justification and a historical basis. For NVDA that might be "rack-based solution mix", which this
desk argued and no template would anticipate.

**Hard cap of one.** A second proposal is rejected with a warning.

### 5.5 Why the LLM does not choose the driver set

It knows a great deal about what drives a semiconductor business, and that knowledge is
unversioned, unauditable, and varies between runs. If drivers are freely chosen, NVDA this quarter
cannot be compared with NVDA last quarter because different things were modelled.

**The template is code — reviewable, versioned, tested, identical every run. The argument is the
model's.** Same rule as the valuation layer: structure in Python, judgment in the LLM.

---

## 6. The forecast engine

New module `mas_sector_system/forecast_engine.py`. Pure functions, no I/O, no LLM.

```python
FORECAST_YEARS: int = 5

def historical_profile(state: dict) -> dict:
    """Facts computed from annual_series per §3.2. No judgment."""

def mechanical_defaults(profile: dict, *, archetype: str) -> dict:
    """Layer-3 values per §5.3, drawn from history."""

def build_forecast(
    state: dict, drivers: dict, *, archetype: str, years: int = FORECAST_YEARS,
) -> dict:
    """Deterministic P&L + FCF projection from drivers. Never calls an LLM."""

def reconcile_to_consensus(forecast: dict, comps: dict) -> dict:
    """Compare year-1 modelled EPS/revenue against consensus (§9.2)."""
```

`build_forecast` returns:

```jsonc
{
  "archetype": "general",
  "years": [
    { "fy": "2027E",
      "revenue": 376503.0, "revenue_by_segment": {"data_center": 349858.0, "...": 0},
      "gross_profit": 282377.0, "gross_margin": 0.75,
      "opex": 41200.0, "operating_income": 241177.0,
      "net_income": 205000.0, "eps_diluted": 8.38,
      "d_and_a": 5600.0, "capex": 7530.0, "delta_working_capital": 2100.0,
      "free_cash_flow": 199970.0 }
  ],
  "drivers_applied": { "...": "..." },
  "mechanical_defaults_used": { "tax_rate": 0.135, "...": "..." },
  "warnings": [],
  "segments_reconciled": true
}
```

Constraints: existing signatures in `valuation_engine.py` are **not** changed — the forecast is a
new input to them, not a rewrite. Every field above is computed; none may be assigned from model
output.

---

## 7. Argued-driver contract  ⚠️ SHARED — DO NOT EDIT UNILATERALLY

Extends `VALUATION_ICL_DESIGN.md` §4. Everything there still holds: decimals not percentages,
non-empty resolvable `evidence`, ranges not points, code-enforced rejection.

```jsonc
{
  "archetype": "general",
  "segments_used": ["data_center", "gaming", "professional_visualization", "automotive", "oem"],
  "drivers": [
    {
      "driver": "revenue_growth.data_center",
      "historical_basis": "3y trend decelerating 217% → 142% → 68%",   // MANDATORY
      "historical_values": [2.17, 1.42, 0.68],
      "argued_range": [0.40, 0.50],
      "verdict": "below_trend",        // above_trend | in_line | below_trend
      "reasoning": "…",
      "evidence": ["income_statement.annual_series.0.segments.data_center", "…"]
    }
  ],
  "extra_driver": null,                 // §5.4, at most one
  "overall_confidence": "moderate"
}
```

**`historical_basis` is mandatory and enforced.** A driver without it is rejected and the
mechanical/trend default stands. This is the §2 "departure from a measured base" rule in code — it
is the difference between an argument and a guess, and it is the single most important new control
in this epic.

---

## 8. Guardrails

### 8.1 Hard clamps (Python, absolute)

| Driver | Min | Max |
|---|---|---|
| `revenue_growth.*` | −0.50 | 2.00 |
| `gross_margin` | 0.0 | 0.99 |
| `opex_growth` | −0.30 | 1.50 |
| `net_interest_margin` | 0.0 | 0.15 |
| `provision_rate` | 0.0 | 0.10 |
| `combined_ratio` | 0.50 | 1.50 |
| `occupancy` | 0.50 | 1.00 |
| `capex_pct_revenue` | 0.0 | 0.60 |

### 8.2 History-relative bands (soft, dissent permitted with reasoning)

- `gross_margin` within `[hist_min − 1000bps, hist_max + 500bps]`
- `revenue_growth.*` within `[hist_min − 50%, hist_max + 50%]` of the segment's own range
- Any value outside → recorded in `band_dissents`, surfaced in the memo as a stated dissent

### 8.3 Structural checks (fail the forecast, not the run)

1. **Segment sum:** segment revenues within 2% of consolidated, else consolidated-only fallback.
2. **Terminal sanity:** year-5 revenue may not exceed 6× year-0. Beyond that the model has left
   the realm of the arguable.
3. **Margin monotonicity guard:** gross margin may not exceed `hist_max + 500bps` in *any*
   projected year, not just year 1.
4. **EPS sign check:** if year-1 modelled EPS flips sign versus actual, require an explicit
   driver-level reason or reject.
5. **Consensus corridor:** year-1 revenue within ±25% of consensus where consensus is available.
   Outside → `consensus_divergence` warning, **not** a rejection. A large, argued divergence is a
   legitimate variant view; a silent one is a bug.

---

## 9. How the forecast feeds valuation

### 9.1 Into the DCF

`compute_dcf_from_state` currently grows a single base FCF. With a forecast present, the explicit
projection years come from `build_forecast` and only the fade and terminal remain rate-driven.

**Preserve the anchor discipline.** Three cases now travel together and all three ship:

| Case | Basis |
|---|---|
`dcf_engine` | sector defaults on trailing FCF — unchanged anchor |
`dcf_judgment` | argued rates on trailing FCF — the VAL-05 central case |
`dcf_modelled` | **new** — argued drivers → modelled FCF → DCF |

### 9.2 Into comps, and the variant-perception number

The comps chain today applies an argued multiple to *consensus* forward EPS
(`VALUATION_ICL_DESIGN.md` §5.3), which reproduces the desk's method but never its estimate. With a
forecast, it applies the argued multiple to the **desk's own** modelled EPS.

`reconcile_to_consensus` then reports the gap explicitly:

> *"Modelled FY2027 EPS $8.38 vs consensus $8.82 — 5% below, driven by opex."*

That line is the desk's variant perception, quantified. The NVDA memo stated exactly this
("slightly conservative by 5% compared to Wall Street"). **Report the gap; never force agreement.**

---

## 10. Failure handling

A forecast must never hard-fail a run. Precedent: `VALUATION_ICL_DESIGN.md` §9.

| Failure | Behaviour |
|---|---|
| Segments unextractable / do not reconcile | Consolidated-only forecast; `segments_reconciled: false` |
| Fewer than 3 annual periods | **No forecast.** Fall back to the existing trailing-based valuation |
| Driver critique unparseable | No forecast; base and judgment cases ship as today |
| `historical_basis` missing on a driver | That driver reverts to trend/mechanical default |
| Structural check §8.3 fails | Forecast dropped, reason disclosed in the audit log |
| Archetype has no driver template | Consolidated-only with the `general` template, flagged |

**The pre-forecast system must remain fully functional with the forecast switched off.** Ship
behind a `--forecast` flag until the measurement in §11 clears.

---

## 11. Measurement

Extends `valuation_rubric.py`. New criteria, mechanical wherever possible:

| # | Criterion |
|---|---|
| F1 | Every argued driver carries a non-empty `historical_basis` |
| F2 | Segment revenues sum to consolidated within 2% |
| F3 | Driver count ≤ archetype template + 1 |
| F4 | Modelled year-1 reconciled to consensus with the gap stated |
| F5 | No currency figure in the memo that is not present in the forecast object |
| F6 | Each projected year's margins within the §8.2 bands, or dissent stated |
| F7 | All three valuation cases present (`dcf_engine`, `dcf_judgment`, `dcf_modelled`) |

**Held-out set:** the eight tickers in `VALUATION_ICL_DESIGN.md` §10.2, now including JPM and PLD
(this epic is what makes financials work). Score before and after.

**Two-ticker runs cannot support a claim about this epic.** Eleven-plus binary criteria on two
names is roughly twenty data points. Budget the full eight per measurement round.

---

## 12. State contract  ⚠️ announce before editing (AGENTS.md Rule 2)

| Field | Type | Written by |
|---|---|---|
| `historical_profile` | dict | `metrics_compute` or forecast node |
| `forecast` | dict \| None | forecast step |
| `driver_critique` | dict \| None | forecast step |
| `dcf_modelled` | dict \| None | `fundamental_valuation_node` |
| `consensus_reconciliation` | dict \| None | forecast step |

Additive only. `dcf_engine`, `dcf_judgment`, `comps_engine`, `comps_judgment` keep their exact
current meanings.

---

## 13. Work packages & ownership

**File boundaries are the contract; model assignment is swappable. No two tracks write the same
file.** Round 1 of the previous epic lost work because agents shared a checkout — see §14.

### Track A — Driver templates & doctrine · **Gemini**

| Epic | Deliverable | Files (exclusive) |
|---|---|---|
| FWD-01 | Driver template per archetype in `archetype.py::ARCHETYPES` (all 16), per §5.2 — argued drivers, forecast output shape, history-relative bands | `mas_sector_system/driver_templates.py` (new) |
| FWD-02 | Extend the L1 archetype cards with forecast doctrine: which drivers matter for this business type and why | `mas_sector_system/valuation_doctrine.py` |

```python
DRIVER_TEMPLATES: dict[str, dict]          # keyed on ARCHETYPES
def drivers_for(archetype: str) -> list[dict]
def band_for_driver(archetype: str, driver: str) -> tuple[float, float] | None
def forecast_output_kind(archetype: str) -> str   # eps_fcf | ffo | residual_income | book_value
```

Pure data and pure functions. No I/O, no LLM, no import from `agents.py`.
**Financials are the priority** — `bank_lender`, `insurance`, `equity_reit`, `mortgage_reit` first,
since they are the sector currently getting nothing.

### Track B — Extraction & forecast engine · **Codex**

| Epic | Deliverable | Files (exclusive) |
|---|---|---|
| FWD-03 | Segment revenue extraction per §4, incl. the 2% reconciliation and `segment_changes` | `mas_sector_system/tools.py` |
| FWD-04 | Extend `annual_series` to 8–10 ranks for cyclical archetypes (§3.1); all three statements | `mas_sector_system/tools.py` |
| FWD-05 | `historical_profile`, `mechanical_defaults`, `build_forecast`, `reconcile_to_consensus` | `mas_sector_system/forecast_engine.py` (new) |

**FWD-03 is the hardest task in this epic.** Segment footnotes are inconsistent between filers and
between years. Ship it with golden fixtures for at least four filers across four archetypes.
Do not change existing `valuation_engine.py` signatures.

### Track C — Measurement · **Grok**

| Epic | Deliverable | Files (exclusive) |
|---|---|---|
| FWD-06 | Criteria F1–F7 (§11); mechanical where possible; reuse `_evidence_value` rather than reimplementing | `mas_sector_system/valuation_rubric.py`, `tests/` |
| FWD-07 | Baseline the full eight-ticker set **before** any forecast code lands | `tests/`, `outputs/` |

FWD-07 needs explicit spend approval and gates the epic.

### Track D — Wiring & arguing · **Claude** · blocked on A + B

| Epic | Deliverable | Files |
|---|---|---|
| FWD-00 | `state.py` contract (§12) + scratchpad announce | `state.py` |
| FWD-08 | Driver-critique prompt + call; `historical_basis` enforcement | `agents.py` |
| FWD-09 | `dcf_modelled` + consensus reconciliation into the valuation nodes | `agents.py`, `valuation_engine.py` |
| FWD-10 | `--forecast` flag; artifacts and football field carry the third case | `main.py`*, `artifacts.py`, `pdf_generator.py` |

\* FWD-10 touches `main.py` (CLI flag only, **no topology change**) — requires explicit assignment
per AGENTS.md Rule 2.

---

## 14. Sequencing & operational rules

```
FWD-07 baseline (Grok, 8 tickers) ── gates everything
FWD-00 state contract (Claude, first, small)
        ┌──────────────────┬──────────────────┐
   TRACK A (Gemini)   TRACK B (Codex)    TRACK C (Grok)
   FWD-01 templates   FWD-03 segments    FWD-06 criteria
   FWD-02 doctrine    FWD-04 history
                      FWD-05 engine
        └──────────────────┴──────────────────┘
                          ▼
                 TRACK D (Claude) FWD-08 → 09 → 10
                          ▼
              Re-measure the 8; decide on the flag default
```

**Operational rules, learned the hard way in the previous epic:**

1. **Each agent gets its own clone or worktree.** Three agents in one checkout made `git checkout -b`
   cosmetic, left the track branches empty, and left ~2,200 lines untracked until rescued.
2. **Commit to your own branch before reporting done.** "Wrote the files" is not done. Work sitting
   in a shared directory is one `git checkout -f` from gone.
3. **Claim your row in `DEV_SCRATCHPAD.md` before starting.** In the previous epic two agents fixed
   the same validation bug simultaneously because neither claimed it.
4. **Never `git add -A`.** It committed a nested worktree as a gitlink and 3.1 MB of run artifacts.
   Add explicit paths.
5. **`outputs/` is untracked. Keep it that way.**

---

## 15. Open decisions — needed before implementation

| # | Decision | Recommendation |
|---|---|---|
| 1 | Forecast horizon | 5 years explicit, then fade. Longer is false precision |
| 2 | Segment cap | 5 largest + bundled `other` |
| 3 | Does `dcf_modelled` become the headline once trusted, or does `dcf_engine` always lead? | `dcf_engine` leads until F1–F7 clear on the eight-ticker set |
| 4 | Quarterly forecasting | **Out of scope.** Annual only. The desk's NVDA memo modelled quarterly opex; that is a later epic |
| 5 | Segment extraction depth if XBRL segment axes are untagged for a filer | Consolidated-only fallback, disclosed. Do not scrape the PDF |
| 6 | 20-F filers (Alibaba) | Out of scope; separate epic |

---

## 16. Task queue rows

Paste into `DEV_SCRATCHPAD.md` as a new epic. Not appended automatically.

```markdown
### Epic F — Forward Estimates (`FORWARD_ESTIMATE_DESIGN.md`)

**Read the design before claiming a row.** §7 (argued-driver contract) is shared by three tracks and
is frozen. §2's dial ceiling (4–8 drivers) and §7's mandatory `historical_basis` are the two
non-negotiable controls.

| ID | Task | Assignee | Status |
|----|------|----------|--------|
| FWD-07 | Baseline the full 8-ticker set BEFORE any forecast code lands. Needs spend approval. Gates the epic. | Grok | TODO |
| FWD-00 | `state.py`: `historical_profile`, `forecast`, `driver_critique`, `dcf_modelled`, `consensus_reconciliation`. Additive. Announce first. | Claude/Opus-5 | TODO |
| FWD-01 | Driver templates for all 16 archetypes (§5.2) → `driver_templates.py`. **Financials first.** | Gemini | TODO |
| FWD-02 | Forecast doctrine added to the L1 archetype cards. | Gemini | TODO |
| FWD-03 | Segment revenue extraction (§4) + 2% reconciliation + `segment_changes`. Hardest task; golden fixtures for ≥4 filers. | Codex | TODO |
| FWD-04 | `annual_series` to 8–10 ranks for cyclicals; all three statements (§3.1). | Codex | TODO |
| FWD-05 | `forecast_engine.py`: `historical_profile`, `mechanical_defaults`, `build_forecast`, `reconcile_to_consensus`. | Codex | TODO |
| FWD-06 | Rubric criteria F1–F7 (§11). Reuse `_evidence_value`; do not reimplement. | Grok | TODO |
| FWD-08 | Driver-critique prompt + call; enforce mandatory `historical_basis`. | Claude/Opus-5 | TODO |
| FWD-09 | `dcf_modelled` + consensus reconciliation into the valuation nodes. | Claude/Opus-5 | TODO |
| FWD-10 | `--forecast` flag (CLI only, no topology change — needs assignment), artifacts + football field third case. | Claude/Opus-5 | TODO |
```
