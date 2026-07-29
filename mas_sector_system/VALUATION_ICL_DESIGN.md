# Valuation In-Context Learning — Architecture & Work Split

**Status:** DESIGN — approved for implementation, not yet built.
**Author:** Claude/Opus-5 (architect). **Date:** 2026-07-28.
**Implementers:** Gemini · Codex · Grok · Claude (see §12).
**Related:** `CLAUDE.md` (architecture spec) · `AGENTS.md` (collaboration protocol) · `DEV_SCRATCHPAD.md` (live task board).

---

## 0. Read this first

This document is the single source of truth for the valuation ICL work. Every agent working an
epic below **must** read §2 (core principle), §4 (argued-input contract), and their own row in §12
before touching a file. §4 is a shared contract between three separate work tracks — if you find
yourself wanting to change it, stop and log `BLOCKED` rather than editing it unilaterally.

Do not begin without also reading `DEV_SCRATCHPAD.md` per AGENTS.md Rule 1.

---

## 1. The problem this solves

`fundamental_valuation_node` and `relative_valuation_node` do not perform valuation. They narrate
the output of deterministic engines:

- `compute_dcf_from_state()` computes intrinsic value using **sector-default** WACC and terminal
  growth. Every semiconductor company receives identical assumptions regardless of leverage, beta,
  customer concentration, or cycle position.
- `fetch_peer_multiples()` returns a peer table and a cheap/fair/rich read. Nothing argues whether
  the peer set is correct or whether a premium is deserved.

The prompts explicitly forbid the agent from changing any number, which is correct given the
current design — but it means **nothing in the pipeline exercises judgment.** The system has good
arithmetic and no analyst.

The gap to institutional grade is not arithmetic. It is that no one argues about the inputs.

---

## 2. Core principle — the division of labor

> **Python owns every calculation and every fact. The LLM owns every opinion and owns no facts.**
> They hand off exactly twice per valuation.

This is enforced structurally, not by prompt instruction:

| Python owns | The LLM owns |
|---|---|
| All arithmetic | Which assumptions are defensible |
| Every figure sourced from a filing | Which peers actually belong |
| Hard bounds on every input | What multiple is justified |
| Rejecting unsupported arguments | The written narrative |

**The invariant, restated.** `CLAUDE.md` §3 requires deterministic valuation math. That is
preserved: the same engine functions compute every number. What changes is that the *inputs* stop
being sector constants and become arguable within hard bounds. The LLM's output surface contains
**only bounded scalars and enum choices — never a currency amount.** Fabricating a fair value is not
prohibited by instruction; there is no field in the schema that can hold one.

This principle is non-negotiable at the agent level (AGENTS.md Rule 2). Changing it requires an
explicit product decision from the user.

---

## 3. The knowledge stack

Four layers, injected in order of increasing specificity. Layers 0–1 are the "basics"; layer 2 is
where in-context learning actually happens; layer 3 is the only layer that produces learning rather
than imitation.

| Layer | Content | Keyed on | Budget | Owner |
|---|---|---|---|---|
| **L0 Doctrine** | Valuation first principles: FCFF vs FCFE, terminal-value dominance as a red flag, WACC construction, when DCF is structurally invalid (banks → residual income, REITs → FFO/NAV, insurers → book methods), intrinsic vs relative separation, ranges over points | static | ≤ 3k tok | Track A |
| **L1 Archetype card** | Per-archetype: correct primary method, defensible WACC band, defensible multiple set, cycle traps, what invalidates the thesis | `classify_archetype()` | ≤ 800 tok | Track A |
| **L2 Exemplars** | Extracted reasoning moves from the desk's own memos, normalized to engine-available data | archetype | ≤ 5k tok | Track A |
| **L3 Desk memory** | Prior run for this ticker **plus whether the prior call was right** | ticker | existing | VAL-07 |

**Graceful degradation is mandatory.** When no exemplar exists for the classified archetype, fall
back to L0+L1 only and record `exemplars_available: false`. **Never substitute a mismatched
archetype's exemplars** — a semiconductor exemplar applied to a bank is worse than no exemplar.

### 3.1 Where these blocks land (cache-critical)

`_run_with_shared_cache()` caches the prefix through `shared_data_block`, and
`SHARED_ANALYSIS_SYSTEM_PROMPT` is shared byte-for-byte by bull / bear / fundamental / relative.

**Do not put doctrine, cards, or exemplars in the system prompt.** Doing so either taxes bull and
bear with valuation content they do not need, or splits one cache entry into two.

All ICL blocks go in `extra_uncached`, alongside where `dcf_block` and `comps_block` already sit
(`agents.py:1291` and `agents.py:1403`). Block order after the cache breakpoint:

```
[cached shared packet] → engine block → L0 doctrine → L1 card → L2 exemplars → role instruction
```

Cost of this choice: ≈ 8k uncached tokens × 2 valuation agents ≈ **$0.05/run** at Sonnet input
pricing. Cheap enough that preserving the shared cache is unambiguously the right trade.

---

## 4. The argued-input contract  ⚠️ SHARED — DO NOT EDIT UNILATERALLY

Tracks A, B, and C all depend on this section. Treat it as a schema freeze.

### 4.1 Arguable vs never arguable

| **Never arguable** (facts from filings) | **Arguable** (forward-looking opinion) |
|---|---|
| `base_fcf` as a figure | `base_fcf_method` — enum |
| net debt, share count | `wacc` — scalar |
| historical growth, reported margins | `g_high`, `g_terminal` — scalars |
| any currency amount | `high_growth_years`, `fade_years` — integers |
| peer multiples as reported | `justified_multiple` — scalar |
| — | peer include/exclude — from candidate list only |

**The `base_fcf_method` pattern is the important one.** Normalizing cash flow is a genuine analyst
judgment and matters enormously for cyclicals — valuing a semiconductor off peak TTM cash flow is
the classic error. The LLM selects a *method*; Python computes the resulting figure from filings.
Judgment without touching arithmetic.

```
base_fcf_method ∈ { "ttm", "avg_3y", "avg_5y", "mid_cycle" }
```

Peer changes select from `comps["peer_list"]` and the engine's candidate pool only. **A ticker not
already in the candidate pool cannot be added.** This prevents invented comparables.

### 4.2 Guardrails — tier 1, hard clamps

Enforced in Python. Values outside are clamped, never rejected silently; every clamp appends to
`clamp_warnings`.

| Parameter | Min | Max | Additional constraint |
|---|---|---|---|
| `wacc` | 0.05 | 0.20 | — |
| `g_terminal` | 0.0 | 0.035 | **must be ≤ `wacc` − 0.015** |
| `g_high` | −0.10 | 0.40 | — |
| `high_growth_years` | 3 | 10 | integer |
| `fade_years` | 2 | 10 | integer |
| `justified_multiple` | 0.25 × peer median | 3.0 × peer median | plus absolute per-metric floor/cap |

Absolute per-metric caps for `justified_multiple`: `forward_pe` ∈ [3, 100], `trailing_pe` ∈ [3, 150],
`ev_ebitda` ∈ [2, 60], `price_sales` ∈ [0.2, 40].

The `g_terminal ≤ wacc − 0.015` rule is a **math constraint, not a judgment** — the Gordon
denominator collapses or inverts without it. It must live in code and is not arguable.

### 4.3 Guardrails — tier 2, archetype bands

Each L1 card carries a defensible band per parameter (e.g. `software_saas` WACC 0.09–0.13). Values
outside the band are **permitted** but:

1. require non-empty `reasoning`,
2. are recorded in `band_dissents`,
3. surface in the memo as an explicit stated dissent.

This is correct analyst behavior: you may argue outside the standard band, you must show your work.

### 4.4 The evidence requirement  ⚠️ this is the anti-motivated-reasoning control

Every argued parameter carries `evidence: [field_id, ...]`.

**A parameter whose evidence list is empty, or whose evidence does not resolve to a non-null value
in `ResearchState`, is rejected and reverts to the engine default.** Checked in Python. Not
requested in a prompt.

Allowed `field_id` roots:

```
canonical_metrics.*          income_statement.*        balance_sheet.*
cash_flow_statement.*        comps_engine.*            dcf_engine.*
business_overview            macro_regime_assessment   management_assessment
capital_allocation_assessment
```

**Why this control exists.** The model sees `implied_upside_vs_price` in
`format_dcf_for_prompt()` and the live price in the shared packet. Nothing else prevents it from
reverse-engineering assumptions that justify a predetermined conclusion. Full blinding is
impractical; the evidence requirement is the enforceable substitute.

**Secondary control:** log the default→argued delta per run to `outputs/valuation_delta.jsonl`.
Systematic drift toward whichever assumption makes the stock look cheap becomes visible across runs.

### 4.5 Schemas

**`valuation_critique`** (DCF path, VAL-05):

```jsonc
{
  "archetype": "general",
  "method_appropriate": true,
  "method_reasoning": "FCF DCF is appropriate; capital-light, positive FCF since FY2019.",
  "arguments": [
    {
      "parameter": "wacc",
      "engine_default": 0.105,
      "argued_range": [0.090, 0.100],
      "verdict": "too_high",            // too_high | too_low | defensible
      "reasoning": "Net cash position and investment-grade customer base...",
      "evidence": ["balance_sheet.net_debt", "canonical_metrics.customer_concentration"]
    }
  ],
  "terminal_value_share_of_ev": 0.71,
  "overall_confidence": "moderate",     // high | moderate | low
  "band_dissents": [],
  "clamp_warnings": []
}
```

**`relative_critique`** (comps path, VAL-03):

```jsonc
{
  "archetype": "general",
  "primary_multiple": "forward_pe",
  "multiple_reasoning": "Forward P/E; EV/EBITDA distorted by...",
  "peer_changes": [
    { "ticker": "XXXX", "action": "exclude",   // exclude | include
      "reasoning": "Different end-market...",
      "evidence": ["comps_engine.peer_rows.XXXX"] }
  ],
  "justified_multiple": {
    "metric": "forward_pe",
    "subject_current": 24.1,
    "peer_median": 27.3,
    "argued_range": [28.0, 32.0],
    "reasoning": "Growth-adjusted discount unwarranted given...",
    "evidence": ["canonical_metrics.revenue_growth", "canonical_metrics.gross_margin"]
  },
  "clamp_warnings": []
}
```

**Ranges, not points.** Both schemas require `argued_range: [lo, hi]`. The engine runs at both
corners, producing a band. This is what yields the football field in §8 and prevents false
precision.

---

### 4.6 FCF history contract — `base_fcf_method` normalization rules

*Added 2026-07-28 resolving Codex's BLOCKED on VAL-05a. §4.1 named the enum without defining the
data behind it; this section defines it.*

**The history exists and is not currently surfaced.** `tools.py::_extract_line()` already accepts an
arbitrary `rank: int` and SEC companyfacts carries 5–10 years per tag, but
`_extract_statement_block()` only requests `rank=0` (current) and `rank=1` (prior). Nothing needs to
be fetched; one more loop needs to be written. That is **VAL-10** (§12 Track B), and it is a
deliberate one-file widening of Track B's lane into `tools.py`.

#### Producer schema — `annual_series` (VAL-10, `tools.py`)

`_extract_statement_block()` gains one key alongside the existing four. Same label structure as
`current_annual`, ordered **newest first**, maximum 5 entries. Ranks with no observation are
**omitted, never null-padded** — a gap must not be silently treated as a zero.

```python
block["annual_series"] = [
    {"rank": 0, "fy": "2026", **labels},   # == current_annual
    {"rank": 1, "fy": "2025", **labels},   # == prior_annual
    {"rank": 2, "fy": "2024", **labels},
    # … through rank 4 where tagged
]
```

Additive only. `current_annual` / `prior_annual` keep their exact current meaning — do not
reimplement them as views over the series, and do not change `_extract_statement_block`'s signature.

Two notes for the implementer: `_compute_fcf()` must fill `FreeCashFlow` for every series entry, not
just the four legacy blocks; and `_extract_line`'s null-reason string at `tools.py:685` hardcodes
`"current" if rank == 0 else "prior"`, which will emit a misleading message for rank ≥ 2 — fix it
while you are in there.

#### Consumer rules — `base_fcf_method` (VAL-05a, `valuation_engine.py`)

Read via a new `fcf_history(state) -> list[dict]` returning `[{fy, fcf, revenue}, …]` newest-first.
`fcf` per entry follows the existing `extract_fcf_series` fallback (`FreeCashFlow`, else
`NetCashFromOperatingActivities − abs(CapitalExpenditures)`); `revenue` is the `Revenues` label from
the income block's series.

| Method | Formula | Minimum non-null annual periods |
|---|---|---|
| `ttm` | `current_annual` FCF — **existing behavior, unchanged** | 1 |
| `avg_3y` | arithmetic mean of ranks 0–2 | 3 |
| `avg_5y` | arithmetic mean of ranks 0–4 | 5 |
| `mid_cycle` | `median(fcf_t / revenue_t for t in available) × revenue_rank0` | 3 |

**Why `mid_cycle` is margin-based rather than an average of absolute FCF.** A plain multi-year
average silently penalizes growth: a company three times larger than it was four years ago gets a
normalized FCF anchored to a much smaller business. Normalizing the *margin* and re-applying it to
current revenue separates cycle position from scale, which is the actual analyst intent. This
matters most for exactly the names the desk cares about — see §11.5.

**Period-selection rules, all mandatory:**

1. **Annual periods only.** Never mix quarterly observations into a normalization. Quarters stay
   available for other uses.
2. **No gap filling.** Do not interpolate, extrapolate, or carry a value forward. Missing is missing.
3. **Insufficient history → reject the method, fall back to `ttm`,** and append to `clamp_warnings`
   naming the requested method and the count found (e.g. `"avg_5y requested, 3 annual periods
   available — fell back to ttm"`). This is a §4.2-class clamp, not a hard failure.
4. **`mid_cycle` additionally requires** a non-null `revenue` for every period it uses and a non-null
   `revenue_rank0`. Any missing revenue → same fallback path as rule 3.
5. **Negative FCF periods are retained**, not filtered. A trough year is signal; dropping it is how a
   cyclical gets valued off its peak, which is the error this enum exists to prevent.

**No new state field.** `annual_series` lives inside the existing `cash_flow_statement` and
`income_statement` dicts. VAL-00 is unaffected and does not need reopening.

---

## 5. Relative valuation chain (VAL-03) — **builds first**

### 5.1 Why this leads

Analysis of the six desk memos (NVDA, SpaceX, CRM, QCOM, BABA ×2) shows the desk's actual method is
**multiple-driven, not DCF-driven**:

- NVDA — 32× FY27E EPS → $268
- CRM — 20× FY27 FCF/share → $344, multiple explicit as the bear/base/bull swing variable
- QCOM — leads on 14× P/E vs 27× sector; DCF is secondary
- BABA — DCF produces $145 but the argument is compounding vs a flat share price

The desk's consistent edge is the **re-rating case**. Exemplar density is high here and thin on DCF.
Build where the teaching material is.

### 5.2 Flow

```
fetch_peer_multiples()                  → comps_base       (unchanged, always retained)
        ↓
CRITIQUE CALL  (Opus, structured JSON)  → relative_critique
        ↓
validate + clamp  (Python)              → argued peer set + justified multiple + clamp_warnings
        ↓
apply_peer_changes() → recompute medians
implied_value_from_multiple()           → comps_judgment   (low/high corners)
        ↓
NARRATIVE CALL (Sonnet, sees both)      → relative_valuation
```

### 5.3 The forward-estimate gap — resolved

Every desk memo applies a justified multiple to a **forward** estimate. The comps engine has no
forward estimate and the LLM must not invent one.

**Resolution:** yfinance already supplies `forwardPE` (pulled in `_row_from_info`). Consensus forward
EPS is derivable as `price ÷ forwardPE`. The chain becomes:

```
consensus forward EPS  (engine-derived, never LLM-supplied)
        × argued justified multiple  (LLM, clamped)
        = implied value per share    (Python)
```

**Stated limitation:** this is *consensus* forward EPS, not the desk's own model. The system
reproduces the desk's *method* but applies it to the Street's estimate. Building an independent
forward P&L is a materially larger project and explicitly **out of scope** here.

Where `forwardPE` is null, fall back to trailing metric × argued multiple, and record
`forward_estimate_available: false`.

---

## 6. DCF chain (VAL-05)

```
compute_dcf_from_state()                → dcf_base         (sector defaults, always retained)
        ↓
CRITIQUE CALL  (Opus, structured JSON)  → valuation_critique
        ↓
validate + clamp  (Python)              → argued_inputs + clamp_warnings
        ↓
compute_dcf_with_argued_inputs()        → dcf_judgment     (low/high corners)
        ↓
NARRATIVE CALL (Sonnet, sees both)      → fundamental_valuation
```

Two LLM calls where there is currently one. **They cannot be merged** — the engine must run between
them. The second call reuses the same cached shared packet, so marginal cost is mostly output tokens.

`dcf_base` is never overwritten. It is the anchor case and it always appears in the deliverable
alongside the judgment case.

### 6.1 Model tiering change

The critique call is now the hardest reasoning step in the pipeline and the cheapest place in the
system to buy quality.

| Call | Model | Note |
|---|---|---|
| Critique (fundamental + relative) | **Opus** (`claude-opus-5`) | new |
| Narrative (fundamental + relative) | Sonnet (`claude-sonnet-5`) | unchanged |

≈ $0.15–0.30/run. **Requires a one-line update to `CLAUDE.md` §5 tiering table** — flag it in the
scratchpad, do not silently diverge from the spec.

---

## 7. State contract  ⚠️ shared — announce before editing (AGENTS.md Rule 2)

New fields on `ResearchState`:

| Field | Type | Written by |
|---|---|---|
| `dcf_engine` | dict | *existing — semantics unchanged, remains the anchor case* |
| `comps_engine` | dict | *existing — semantics unchanged, remains the anchor case* |
| `dcf_judgment` | dict \| None | `fundamental_valuation_node` |
| `comps_judgment` | dict \| None | `relative_valuation_node` |
| `valuation_critique` | dict \| None | `fundamental_valuation_node` |
| `relative_critique` | dict \| None | `relative_valuation_node` |
| `valuation_grade` | dict \| None | rubric grader |

`dcf_judgment` / `comps_judgment` carry the same shape as their base counterparts, plus:
`input_source: "argued"`, `clamp_warnings: [...]`, `band_dissents: [...]`.

**One agent makes this change, once, before any track that depends on it begins.** See §13.

---

## 8. Downstream artifacts

**Clean memo → schema 1.2.** The `valuation` block gains `dcf_judgment`, `comps_judgment`, and the
two critiques.

**Disclosure routing — read carefully.** `CLAUDE.md` §3 requires that the clean memo never carries
caveats; unreliable content is dropped and disclosed in the audit log. Applying that here:

| Content | Destination | Why |
|---|---|---|
| `band_dissents` | **clean memo** | the analyst's argument — thesis content |
| `reasoning` / `evidence` | **clean memo** | thesis content |
| `clamp_warnings` | **audit log §5** | a disclosure about process reliability |
| rejected-for-no-evidence params | **audit log §5** | a disclosure |

**Football field** (`pdf_generator.py`) gains bars:

1. Engine default (sector assumptions)
2. Judgment case — low corner
3. Judgment case — high corner
4. Comps-implied (argued multiple × forward estimate)
5. EPV (already computed)

---

## 9. Failure handling

Mirrors the existing empty-LLM fallbacks at `agents.py:1294` and `agents.py:1406`.

| Failure | Behavior |
|---|---|
| Critique call returns empty / unparseable JSON | Fall back to base case only; log; memo states no judgment case produced |
| All parameters rejected for missing evidence | Same as above |
| Some parameters rejected | Proceed with the survivors; rejected ones revert to default; record in audit log |
| `forwardPE` null | Trailing-metric fallback; `forward_estimate_available: false` |
| Archetype has no exemplars | L0+L1 only; `exemplars_available: false` |

**A valuation run must never hard-fail because the critique step failed.** The base case always
ships.

---

## 10. Measurement (VAL-02) — **this is the gate**

Nothing downstream can be evaluated without this. Build it before the exemplar library, not after.

### 10.1 Rubric

Criteria derived directly from defects observed in the desk's own memos (§11.2):

| # | Criterion | Type |
|---|---|---|
| 1 | Archetype named and primary method justified | binary |
| 2 | Every argued input cites ≥1 resolvable evidence field | binary |
| 3 | No currency figure appears that is not traceable to an engine block | binary |
| 4 | Terminal-value share of EV stated (DCF path) | binary |
| 5 | Valuation expressed as a range, not a point | binary |
| 6 | Each peer inclusion/exclusion justified individually | binary |
| 7 | Comparison windows consistent and stated (no YTD vs 1-yr mixing) | binary |
| 8 | ≥1 risk left explicitly unresolved (no self-neutralizing close) | binary |
| 9 | Both default and judgment cases present | binary |
| 10 | Band dissents flagged where applicable | binary |
| 11 | No internal numeric contradiction (same metric, two values) | binary |

Score = count passed. Report per-criterion, not just the total.

### 10.2 Held-out set

Reuse `tests/test_us_sector_coverage.py::GOLDEN_MATRIX` — already validated for archetype coverage.
Minimum before/after set (8):

| Ticker | Archetype | Note |
|---|---|---|
| NVDA | general / semis | desk memo exists |
| QCOM | general / semis | desk memo exists |
| CRM | software_saas | desk memo exists |
| JPM | bank_lender | DCF must be rejected as primary |
| PLD | equity_reit | FFO/NAV path |
| PGR | insurance | book-value path |
| XOM | cyclical_commodity | mid-cycle normalization |
| KO | mature_dividend_payer | stable-assumption control |

**BABA is excluded** — 20-F filer, and the SEC parser matches on `10-K` / `10-K/A`
(`tools.py:633`). Ingesting foreign issuers is separate work, not part of this epic.

Score the 8 before VAL-01 lands (baseline) and after each subsequent epic.

---

## 11. Exemplar extraction protocol (VAL-04)

### 11.1 Source material

Six desk-authored memos: NVDA (Jul 2026), SpaceX (Jun 2026), CRM (Feb 2026), BABA earnings review
(Sep 2025), QCOM (Aug 2025), BABA (Jul 2025).

**Raw memos are not exemplars and must not be pasted in.** A few-shot exemplar is an input→output
pair; these are outputs produced from a private research process. They cite figures the engine
cannot produce and omit figures it does. Pasted raw, they teach the model to state untraceable
figures as fact — directly attacking the no-invented-numbers rule the current prompts depend on.

**Extract reasoning moves. Discard every figure not reproducible from an engine block.**

Desk authorship makes extraction *more* necessary, not less: the corpus faithfully encodes both the
strongest and the loosest habits, and few-shot learning does not distinguish between them.

### 11.2 Moves to extract (confirmed strong)

| Move | Source | Why it transfers |
|---|---|---|
| **Steelman → mechanism → concede** | NVDA, Burry passage | States the bear case, explains the GAAP mechanism for depreciation extension, then leaves the open question open. **This is the gold standard for §10.1 criterion 8.** |
| **Discount rate tied to a named company risk** | QCOM, "12% highlighting the lost Apple revenues" | Exactly the VAL-05 target behavior — a specific verifiable fact driving a specific input |
| **Mix vs rate decomposition** | SpaceX, ARPU $86→$66 | Decomposes a headline metric into mix shift vs price erosion |
| **Like-for-like adjustment** | BABA, 10% ex-divestitures vs 2% reported | Separates underlying business from portfolio actions |
| **Variant perception frame** | CRM | Consensus → divergence → mechanism |

Additional moves may emerge during extraction. Do not pad the list to hit a count.

### 11.3 Patterns to filter OUT

These will be learned if not deliberately excluded:

- **Self-neutralizing risk closes.** QCOM: "Xi promised Trump he won't invade... so this
  geopolitical conflict is safe for the next 3 years"; nearly every risk ends "but I think
  [company] is well suited enough to fend off all these risks." If learned, the bear agent and the
  critique step both become systematically softer and flagged risks stop being decision-relevant.
- **Untraceable forward figures.** "I modeled FY2027 revenue to be $376,503"; "EPS is $8.38."
- **Undefined ratio denominators.** PEG cited across three tickers with no growth input stated; the
  comps engine does not compute PEG at all.
- **Mixed comparison windows.** NVDA peer paragraph runs YTD and 1-year figures in consecutive
  sentences.
- **Internal numeric contradiction.** QCOM: 196,000 patents in one section, "over 300,000" in
  another.
- **Unit errors.** BABA: "$6,019 billion this quarter" for millions.

### 11.4 A note on the QCOM discount-rate passage

It is simultaneously the **best VAL-05 exemplar** and a **live instance of the failure mode VAL-05
exists to prevent**. The memo argues 12% from a specific company fact, then runs 9% → $281, then 8%
with 12% growth as "the numbers I think are most likely" → 125% upside. The rate moved 400bp with
no new company evidence, and the headline came from the friendliest run.

Extract the first half (evidence-driven rate selection). Discard the second (disposition-driven
rate selection). This passage is the clearest available justification for why §4.4 must be enforced
in code rather than requested in a prompt.

### 11.5 Archetype coverage of the exemplar corpus — read before writing cards

`archetype.py::ARCHETYPES` contains no semiconductor archetype. Both of the desk's strongest
memos classify into the catch-all:

| Memo | Archetype | Usable as exemplar? |
|---|---|---|
| NVDA | `general` | yes |
| QCOM | `general` | yes |
| CRM | `software_saas` | yes |
| BABA ×2 | `general` | no — 20-F, §10.2 |
| SpaceX | n/a (private) | no — doctrine only, §11.6 |

**Consequence:** the `general` card and its exemplar slot carry almost the entire corpus, while
`bank_lender`, `insurance`, `equity_reit`, `utility`, `midstream`, and the rest start with **zero**
exemplars and must rely on L0+L1 with `exemplars_available: false`.

This is acceptable for v1 and is the reason §3's graceful-degradation rule is mandatory rather than
nice-to-have. It also raises open decision #4 (§15): whether a semiconductor archetype should be
added, which would let NVDA and QCOM key to a card tuned for cyclicality, inventory, and fab
exposure instead of the generic one.

### 11.6 SpaceX handling

Private company — no filings, no engine block, therefore **no input to pair an output with.** It is
not a pipeline exemplar. Its sum-of-the-parts discipline ("three businesses bundled into one ticker;
value them separately or you get the wrong answer") and the ARPU decomposition are strong **L0
doctrine** material. Route it there.

---

## 12. Work packages & ownership

**File boundaries are the contract. Model assignment is swappable** — if a different agent picks up
a track, the boundaries still hold. No two tracks write the same file.

### Track A — Knowledge  ·  assigned: **Gemini**

Long-context reading and content authoring. No dependency on other tracks.

| Epic | Deliverable | Files (exclusive) |
|---|---|---|
| VAL-01 | L0 doctrine text + L1 archetype cards for all archetypes in `archetype.py::ARCHETYPES`, incl. defensible bands per §4.3 | `mas_sector_system/valuation_doctrine.py` (new) |
| VAL-04 | Exemplar library per §11; archetype-keyed; loader with graceful degradation per §3 | `mas_sector_system/exemplars/` (new dir) |

Required API:
```python
DOCTRINE_CORE: str
ARCHETYPE_CARDS: dict[str, dict]        # keys per archetype.py::ARCHETYPES
def doctrine_block_for(archetype: str) -> str
def band_for(archetype: str, parameter: str) -> tuple[float, float] | None
def exemplar_block_for(archetype: str) -> tuple[str, bool]   # (block, available)
```

Constraints: pure data + pure functions. No I/O, no LLM calls, no imports from `agents.py`.
Every figure appearing in an exemplar must be attributable to an engine block field.

---

### Track B — Engine  ·  assigned: **Codex**

Deterministic functions, fully testable without an LLM. No dependency on other tracks.

| Epic | Deliverable | Files (exclusive) |
|---|---|---|
| VAL-10 | `annual_series` producer per §4.6 — **explicit one-file lane widening into `tools.py`.** Do this first; VAL-05a's `base_fcf_method` depends on it. | `mas_sector_system/tools.py` |
| VAL-03a | Peer-set mutation + justified-multiple → implied value, incl. the forward-estimate chain in §5.3 | `mas_sector_system/valuation_engine.py` |
| VAL-05a | Argued-input validation, clamping, and DCF re-run, incl. `fcf_history()` and the §4.6 consumer rules | `mas_sector_system/valuation_engine.py` |

Required API:
```python
ARGUED_INPUT_BOUNDS: dict[str, tuple[float, float]]   # per §4.2

def validate_argued_inputs(
    proposed: dict, *, archetype: str, engine_default: dict, state: dict,
) -> tuple[dict, list[str]]:
    """Return (accepted_inputs, warnings). Clamps to §4.2, enforces
    g_terminal <= wacc - 0.015, drops params failing the §4.4 evidence check."""

def compute_dcf_with_argued_inputs(state: dict, argued: dict) -> dict: ...
def apply_peer_changes(comps: dict, changes: list[dict]) -> dict: ...
def implied_value_from_multiple(
    *, metric: str, multiple: float, comps: dict, state: dict,
) -> dict: ...
```

Constraints: `compute_dcf()` and `fetch_peer_multiples()` signatures **must not change** —
extend, do not modify. No LLM calls in this track. Every function pure w.r.t. its arguments.

Ship with unit tests covering: each clamp boundary, the `g_terminal` constraint, empty-evidence
rejection, null `forwardPE` fallback, and an out-of-band-but-permitted dissent.

---

### Track C — Measurement  ·  assigned: **Grok**

Independent. Gates everything downstream.

| Epic | Deliverable | Files (exclusive) |
|---|---|---|
| VAL-02 | Rubric, grader, held-out harness, baseline scores | `mas_sector_system/valuation_rubric.py` (new), `tests/test_valuation_rubric.py` (new) |

Required API:
```python
RUBRIC: list[dict]                       # 11 criteria per §10.1
def grade_valuation(state: dict) -> dict # per-criterion results + total
def format_rubric_for_prompt() -> str    # for QC extension
```

Constraints: grading must be **deterministic where possible** (criteria 3, 5, 7, 9, 11 are
mechanically checkable from state and text). Only use an LLM judge for criteria that genuinely
require it (1, 8) and mark those results as `judged: true`.

**Deliverable includes baseline scores for all 8 held-out tickers before VAL-01 lands.** Without a
baseline the rest of the project cannot be evaluated.

---

### Track D — Wiring  ·  assigned: **Claude**  ·  blocked on A + B + C

| Epic | Deliverable | Files |
|---|---|---|
| VAL-00 | `state.py` contract change per §7 + scratchpad announce | `state.py` |
| VAL-03b | Critique call + narrative call in the relative node | `agents.py` |
| VAL-05b | Critique call + narrative call in the fundamental node | `agents.py` |
| VAL-06 | Reconciliation section + `CLAUDE.md` §5 tiering update | `agents.py`, `CLAUDE.md` |

Constraints: `main.py` topology and `routing.py` are **untouched** — every change is in-node. No new
graph node is introduced by this design, deliberately.

---

### Track E — Downstream  ·  unassigned  ·  blocked on D

| Epic | Deliverable | Files |
|---|---|---|
| VAL-08 | Clean memo schema 1.2 + disclosure routing per §8 | `artifacts.py` |
| VAL-09 | Football-field bars per §8 | `pdf_generator.py` |
| VAL-07 | Calibration loop — prior call vs realized price | `memory.py` |

---

## 13. Sequencing

```
VAL-00  state.py contract  ──────────────────┐   (Claude, must land first, small)
                                             │
        ┌────────────────────────────────────┼────────────────────────────────┐
        ▼                                    ▼                                ▼
  TRACK A (Gemini)                    TRACK B (Codex)                  TRACK C (Grok)
  VAL-01 doctrine + cards             VAL-03a peer/multiple           VAL-02 rubric + grader
  VAL-04 exemplars                    VAL-05a argued inputs           + BASELINE SCORES
        └────────────────────────────────────┼────────────────────────────────┘
                                             ▼
                                   TRACK D (Claude)
                                   VAL-03b → VAL-05b → VAL-06
                                             ▼
                                   TRACK E  VAL-07/08/09
```

**VAL-03 before VAL-05.** Relative valuation leads — the exemplar material is dense there (§5.1).

**VAL-02 baseline before anything else lands**, or improvement cannot be demonstrated.

---

## 14. Operational risk — parallel agents in one checkout

At time of writing, `main` carries uncommitted modifications to `CLAUDE.md`, `DEV_SCRATCHPAD.md`,
`agents.py`, `artifacts.py`, `memory.py`, `pdf_generator.py`, `state.py`, `tests/test_artifacts.py`,
and `tests/test_pdf_generator.py`.

Three agents editing that checkout simultaneously will collide with each other **and** with the
in-flight work. Before dispatch:

1. **Commit or stash the pending changes.** A dirty tree is not a safe base for parallel work.
2. **Give each track its own branch or worktree.** Tracks A, B, C write disjoint files, so they
   merge cleanly — but only from a clean base.
3. **`state.py` is touched by exactly one agent (VAL-00) and lands before the others start.**

Tracks A, B, and C have zero file overlap by construction. That property is what makes parallel
dispatch safe, and it is why §12 boundaries must not be renegotiated mid-flight.

---

## 15. Open decisions for the user

| # | Decision | Default if unanswered |
|---|---|---|
| 1 | Independent forward P&L build (removes the §5.3 consensus dependency) | Out of scope — use consensus |
| 2 | 20-F ingestion so BABA runs end-to-end | Out of scope — separate epic |
| 3 | Whether `dcf_judgment` may become the headline number, or `dcf_base` always leads | `dcf_base` leads; both always shown |
| 4 | Add a semiconductor archetype to `archetype.py` (§11.5) — NVDA and QCOM currently key to `general` | Not added in v1; `general` card absorbs them |

---

## 16. Task queue rows

Paste into the "📌 Active Task Queue" table in `DEV_SCRATCHPAD.md` as a new epic section.
Not appended automatically — `DEV_SCRATCHPAD.md` has uncommitted changes (§14).

```markdown
### Epic V — Valuation In-Context Learning (`VALUATION_ICL_DESIGN.md`)

| ID | Task | Assignee | Status |
|----|------|----------|--------|
| VAL-00 | `state.py` contract: add `dcf_judgment`, `comps_judgment`, `valuation_critique`, `relative_critique`, `valuation_grade`. Shared contract — announce before editing. Must land before A/B/C start. | Claude/Opus-5 | TODO |
| VAL-01 | L0 doctrine + L1 archetype cards → `valuation_doctrine.py`. Pure data. | Gemini | TODO |
| VAL-02 | Rubric + grader + held-out harness → `valuation_rubric.py`. **Includes baseline scores for the 8 tickers — gates the epic.** | Grok | TODO |
| VAL-03a | Peer mutation + justified-multiple → implied value, incl. forward-estimate chain (§5.3). `valuation_engine.py`. | Codex | TODO |
| VAL-03b | Relative critique + narrative calls, in-node. `agents.py`. Blocked on VAL-01/02/03a. | Claude/Opus-5 | TODO |
| VAL-04 | Exemplar library per §11 → `exemplars/`. Extract moves, filter §11.3 patterns. | Gemini | TODO |
| VAL-05a | Argued-input validation + clamps + DCF re-run. `valuation_engine.py`. | Codex | TODO |
| VAL-05b | Fundamental critique + narrative calls, in-node. `agents.py`. Blocked on VAL-05a. | Claude/Opus-5 | TODO |
| VAL-06 | Reconciliation section + `CLAUDE.md` §5 tiering update (critique = Opus). | Claude/Opus-5 | TODO |
| VAL-07 | Calibration loop — prior call vs realized price. `memory.py`. | _unassigned_ | TODO |
| VAL-08 | Clean memo schema 1.2 + disclosure routing (§8). `artifacts.py`. | _unassigned_ | TODO |
| VAL-09 | Football-field bars (§8). `pdf_generator.py`. | _unassigned_ | TODO |
```
