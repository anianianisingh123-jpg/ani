# FWD-07 eight-ticker baseline — independent review

Reviewer: Claude/Opus-5 · Date: 2026-07-31
Scope: Grok's FWD-07 run (commit `aba7d6b`), the `_fwd_baseline` artifacts, and the
delivered memos for the three top-scoring tickers (QCOM 10/11, KO 10/11, NVDA 9/11 —
NVDA ties CRM and PGR at 9).

Every finding below was reproduced against the committed state slices or the code.
Numbers in this document were recomputed independently, not copied from the run.

---

## Bottom line

The run itself was executed carefully and the handoff is honest. But **the baseline is
not usable as it stands**, and the two biggest conclusions in Grok's handoff (C3 =
writer discipline, C11 = writer discipline) are **wrong** — both are grader bugs.

The most serious finding is not in the run at all, it's in the valuation engine
underneath it: two arithmetic bugs put wrong numbers into the client-facing memos with
confident disclosures attached. The KO memo — one of the two top-scoring deliverables —
names the wrong dominant valuation driver, carries a compliance disclosure describing
something that never happened, and publishes a range 3× too narrow while calling it too
wide. **It scored 10/11.** No rubric criterion checks arithmetic, so nothing caught it.

Ranked by severity:

| # | Finding | Severity | Type |
|---|---------|----------|------|
| 1 | Sensitivity deltas measured against the wrong baseline → KO memo names the wrong dominant driver, false bias disclosure | **Blocker** | Engine bug |
| 1b | Range corners aren't sign-aware → band is 3× too narrow while labelled "wider than the analysis supports" | **Blocker** | Engine bug |
| 2 | Every judgment-layer disclosure is dropped from the deliverables | **Blocker** | Plumbing gap |
| 3 | C11 "contradictions" are ~100% regex garbage, not writer errors | High | Grader bug |
| 4 | C3 "untraceable currency" is 83% false positives masking the 17% that are real | High | Grader bug |
| 4b | Nothing in the rubric checks whether the answer is plausible or coherent | High | Rubric gap |
| 5 | The 8 runs aren't a controlled experiment — 5 of 8 prompts hand the model the answer | High | Method |
| 6 | 4 of 8 re-runs ingested their own throwaway first pass as "prior desk memory" | High | Method |
| 7 | Non-FCF paths ship a fixed ±15% band; C5 passes it as a "range" | Medium | Design |
| 8 | Desk memory doesn't record the rating or price target for 6 of 7 runs | Medium | Bug |
| 9 | XOM is an entity-resolution failure, not a commodity-extraction failure | Medium | Design |
| 10 | PGR's memo mislabels its own valuation band | Medium | Writer fidelity |
| 11 | C8 is LLM-judged and non-deterministic — can't anchor a baseline | Medium | Method |
| 12 | Handoff says artifacts are gitignored; they're committed | Low | Housekeeping |

---

## 1. BLOCKER — the sensitivity table lies when the analyst changes the FCF basis

**Where:** `mas_sector_system/valuation_engine.py:1531` vs `1547-1552`

```python
default_fv = base.get("fair_value_per_share")      # engine's own base FCF
...
case = _recompute_dcf_case(base, base_fcf=normalized_fcf, ...)  # ARGUED base FCF
"delta_vs_default": fv - default_fv                 # comparing two different worlds
```

Each sensitivity row moves one parameter and recomputes using the **argued** base FCF,
but subtracts the fair value from a run that used the **engine's** base FCF. When the
analyst argues for a different base-FCF method, every delta is contaminated by a
constant offset that has nothing to do with the parameter being tested.

The tell is unmistakable in KO's output: three parameters whose argued midpoint
**equals** the engine default (`g_terminal` 2.5%→2.5%, `high_growth_years` 5→5,
`fade_years` 5→5) each report a **+$17.31** swing. A parameter that didn't move
cannot move the value.

A defensive reading — *"delta vs default means delta vs the engine's unargued answer,
base FCF included"* — does not survive that tell. Under **any** definition, a parameter
held at its default reporting movement is incoherent, and it is presented to the reader
as that parameter's effect.

`base_fcf_method` is also excluded from the sensitivity loop (line 1508), so its
effect is never shown on its own — it's smeared invisibly across every other row.

**Who is affected:** only when argued base-FCF method ≠ the engine's basis.
- NVDA, CRM — argued `ttm` matched the engine → clean, deltas are correct.
- **QCOM** (`avg_3y`) and **KO** (`avg_5y`) → corrupted.

### KO, as reported vs. as it actually is

Recomputed from the committed inputs (base FCF avg_5y $8.1152B vs engine TTM $5.296B,
net debt $33.344B, 4.3025B shares):

| Lever | Reported FV | Reported Δ | **True Δ** (vs correct $42.07 baseline) |
|---|---|---|---|
| `wacc` 9.0% → 7.75% | $54.88 | **+$30.12** | **+$12.81** |
| `g_high` 11.7% → 3.25% | $23.29 | **−$1.47** | **−$18.78** |
| `g_terminal` (not moved) | $42.07 | +$17.31 | **$0.00** |
| `high_growth_years` (not moved) | $42.07 | +$17.31 | **$0.00** |
| `fade_years` (not moved) | $42.07 | +$17.31 | **$0.00** |
| `base_fcf_method` ttm→avg_5y | *never shown* | — | **+$17.31** |

**The single biggest lever in KO's whole valuation is the base-FCF method switch, and
it is the one lever the table never displays.**

### It reached the client deliverable, word for word

From `KO_2026-07-30_memo.docx`, §6 Valuation Reconciliation:

> "Sensitivities: WACC is the dominant lever (9.0% → 7.75% lifts FV to **$54.88**);
> g_terminal to argued midpoint lifts to **$42.07**; g_high moving to 3.25% barely
> matters (**$23.29**, −$1.47)."

Four errors in one sentence:
1. WACC is **not** the dominant lever — g_high is (−$18.78 vs +$12.81).
2. g_terminal was **never moved to a different midpoint**; it lifts nothing.
3. g_high does not "barely matter" — it is the **largest** lever, and it points **down**.
4. The memo then reasons off error #1: *"even under the engine's most generous
   defensible single-lever adjustment (WACC to 7.75%, giving $54.88)…"*

The writer did nothing wrong. It transcribed the engine faithfully. The engine lied.

### The one-sided bias disclosure is also false

`directional_bias` is computed from these same deltas, so KO's fires on corrupt input.

| | Reported | Correct |
|---|---|---|
| Material arguments | 5 | **2** |
| Dominant share | 98% | **59%** |
| Direction | above default | **below default** |
| `one_sided` fired? | **yes** | **no — gate needs ≥3 args and ≥80%** |

So the memo's claim that *"98% of argued parameter movement pushes fair value above
the default, i.e. a uniformly generous re-reading"* describes something that did not
happen. This is VAL-16's newest control producing a confident, wrong compliance
statement in a client document.

**QCOM survives directionally.** Correct baseline is $306.10, not $335.83. g_high
(−$159.72), wacc (−$33.50), g_terminal (−$8.21) — still 3 material arguments, still
100% downward, still g_high dominant, so `one_sided` correctly fires. But every
magnitude the memo quotes is wrong (reported −$189 / −$63 / −$38), and the count is 3,
not 4.

### Fix

1. Compute a neutral reference: `_recompute_dcf_case(base, base_fcf=normalized_fcf,
   **engine_defaults)` and use **that** as `default_fv` for all deltas.
2. Add `base_fcf_method` as its own sensitivity row (`neutral_fv − engine_fv`) so the
   largest lever is visible.
   *Product decision needed:* doing this also feeds it into `_material` and the
   directional-bias share. For KO that adds a +$17.31 "up" argument → 3 material args,
   share 0.616, still below the 0.80 gate. But someone should decide deliberately
   whether a **method selection** counts as a directional "argument" — it is the
   largest single lever, so arguably yes. Don't let it be inherited by accident.
3. Add a unit test asserting Δ == 0 for any parameter whose argued midpoint equals the
   engine default. That single assertion catches this whole class.
4. Re-run KO and QCOM before anyone uses these as a baseline.

---

## 1b. BLOCKER — the "compounded extremes" band isn't compounded, and the disclaimer is inverted

**Where:** `valuation_engine.py:1459-1502` (`_argued_corner`, corner loop)

The two corner cases are built by taking index `[0]` and index `[1]` of each
parameter's argued range. But **the low end of a range is not the pessimistic end for
every parameter.** A lower WACC *raises* value; a lower `g_high` *lowers* it. So
"corner 0" is a mixture in which the two effects partially cancel.

Recomputed on KO (argued ranges: wacc [0.070, 0.085], g_high [0.020, 0.045]):

| | wacc | g_high | FV |
|---|---|---|---|
| Engine "low_case" (corner 0) | 0.070 | 0.020 | **$33.94** ← the *higher* number |
| Engine "high_case" (corner 1) | 0.085 | 0.045 | **$28.39** ← the *lower* number |
| **True pessimistic** (both against) | 0.085 | 0.020 | **$23.56** |
| **True optimistic** (both for) | 0.070 | 0.045 | **$40.66** |

The corners are scrambled — the case labelled "low" produces the high value — and the
engine then sorts them, so the reported band is $28.39–$33.94: **width $5.55 against a
true compounded width of $17.10. The published band is 3.1× too narrow.**

Now read the basis string the engine attaches to it:

> `"low/high = COMPOUNDED extremes (all parameters pessimistic / optimistic at once)
> and are wider than the analysis supports — not scenarios"`

Both clauses are false. The parameters are not stacked, and the band is dramatically
**narrower**, not wider. The disclaimer points readers in exactly the wrong direction.

**Both top-3 memos were misled by it.** KO: *"The compounded extremes of $28.39–$33.94
are explicitly not scenarios and are not headlined here"* — correctly suppressing a band
for being too wide when it is far too narrow. QCOM is more revealing:

> *"the compounded-extremes band ($123.87–$133.80) is artificially narrow because it
> stacks all-pessimistic then all-optimistic."*

The writer **noticed the narrowness** — good instinct — and then invented a wrong
explanation, because the engine's own label told it stacking was happening. Stacking
makes bands wider. The writer was reasoning correctly from a false premise.

**Fix:** select each corner by *direction of effect*, not by range index — invert for
`wacc` (and any parameter where higher = lower value) before picking the end. Same
function family as Finding 1; fix them together and re-run all four FCF-path tickers.
This also compounds Finding 10: PGR borrowed a label that is wrong twice over.

---

## 2. BLOCKER — every judgment-layer disclosure is generated and then thrown away

**Where:** `mas_sector_system/artifacts.py:517-544` (`collect_valuation_disclosures`)

The collector reads only `state["dcf_engine"]` and `state["comps_engine"]`. Everything
the judgment layer produces lives on `state["dcf_judgment"]["clamp_warnings"]` and is
never read.

Confirmed absent from **all** compliance audit logs and **all** memos:

| Disclosure | Fired on | Reaches deliverable? |
|---|---|---|
| `DIRECTIONAL BIAS: N% of argued movement…` | QCOM, CRM, KO | **No** |
| `Argued FCF inputs not applied: archetype does not use an FCF DCF` | JPM, PLD, PGR | **No** |
| `fade_years clamped from 12 to 10 within [2, 10]` | PGR | **No** |
| `band_dissents` | where applicable | **No** |

CLAUDE.md §3 states valuation-engine disclosures belong in the audit log. KO's log §5
carries exactly 3 entries — one net-debt note and two comps notes. The bias detector,
the inert-FCF notice, and the clamp record are all missing.

This means **the entire Epic V control layer (VAL-10 / VAL-15 / VAL-16) is invisible in
the deliverables.** It fires into a void. Where a disclosure *did* reach a memo (KO,
QCOM), it got there because the synthesis LLM happened to read the raw state — not
because the artifact pipeline delivered it. That is not a control; that's luck.

**Fix:** add `dcf_judgment` / `comps_judgment` to the key list in
`collect_valuation_disclosures`, with `clamp_warnings` and `band_dissents` in the
disclosure-field sets. Roughly a five-line change with large payoff.

---

## 3. HIGH — C11's "numeric contradictions" are almost entirely regex garbage

Grok's handoff: *"C11 contradictions ~half (NVDA/CRM/JPM/PLD/PGR) → **writer
discipline**; clusters on both FCF and non-FCF."*

That diagnosis is wrong. I pulled the actual matched text for every flagged
contradiction. Essentially none of them are writer errors.

**Root cause A — `high[- ]growth` is an alias for `g_high` in the label regex**
(`valuation_rubric.py:455`), so ordinary English gets captured as a growth-rate claim:

| Ticker | Flagged | What the regex actually matched |
|---|---|---|
| CRM | `g_high: 0.688` | `"high-growth names (NOW's **68.8**x"` — ServiceNow's P/E multiple |
| CRM | `g_high: 0.26` | `"high-growth rate is FY**26**"` — digits pulled out of "FY26" |
| NVDA | `g_high: 0.05` | `"g_high (**5**-year high-growth rate)"` — the label's own gloss |
| NVDA | `g_high: 0.03` | `"linear fade from high growth to **3**%"` — that's g_terminal |
| PGR | `eps: 202.0` | `"EPS ~flat vs FY**202**5"` — digits pulled out of a fiscal year |

**So NVDA's and CRM's C11 failures are 100% fabricated by the grader.** Their real
g_high values (35%/27% and 15.8%/9.5%) are perfectly consistent.

**Root cause B — no period scoping.** Annual and quarterly EPS are pooled as one
quantity, even when the memo labels them explicitly:

- JPM `eps: [20.02, 23.76, 5.94]` = FY2025 annual / annualized Q1 FY2026 / Q1 quarterly
- PGR `eps: [19.23, 4.80]` = FY2025 annual / Q1 FY2026 quarterly
- PLD `eps: [3.56, 1.05]` = tagged `[eps_diluted__current_annual]` vs `[..._current_quarter]`

PLD's memo tags each figure with its canonical metric ID. **The memo is more rigorous
than the grader that failed it.**

**Fixes:**
- Drop `high[- ]growth` from the label alternation, or require an adjacent `=`/`:`/`of`.
- Reject matches where the digits come from `FY\d{2,4}` / `Q\d` tokens.
- Exclude `unit == "x"` (a multiple) from rate labels.
- Scope by period: treat `eps@annual` and `eps@quarter` as different identities.
- Tighten the 16-character label→number gap; it is what lets "rate is FY" through.

Until fixed, C11 is noise. The real C11 pass rate is likely 8/8, not 3/8.

---

## 4. HIGH — C3 is ~75% false positives, and that's hiding the ~25% that are real

Grok's handoff: *"Do not treat C3 mass-fail as archetype extraction — **fix writers**
or C3 allowlist next."* Half right, but the split matters enormously.

C3's traceability universe (`valuation_rubric.py:365-372`) walks `dcf_engine`,
`comps_engine`, `dcf_judgment`, `comps_judgment`, `canonical_metrics` — but **not the
raw `income_statement` / `balance_sheet` / `cash_flow_statement`** the writers were
handed. I re-ran the check and split each flagged figure by whether it appears in
those raw statements:

Full count across all flagged figures, deduplicated by value (not by string — `$235B`
and `$235 billion` are one figure):

| Ticker | Flagged | In raw SEC statements (grader gap) | Genuinely unsourced |
|---|---|---|---|
| NVDA | 4 | 4 | **0** |
| KO | 3 | 3 | **0** |
| CRM | 0 | — | — |
| QCOM | 1 | 0 | **1** — `$3.2B` |
| JPM | 15 | 12 | **3** — `$900B`, `$118B`, `$4.8T` |
| PGR | 11 | 9 | **2** — `$95B`, `$5.1B` |
| PLD | 12 | 10 | **2** — `$5.5B`, `$235B` |
| **Total** | **46** | **38 (83%)** | **8 (17%)** |

**NVDA's and KO's C3 failures are pure grader noise** — every flagged figure is in the
filings, so both should pass. But JPM, PGR, PLD and QCOM each carry 1–3 figures that
appear **nowhere in the state** — plausibly model-recalled or externally sourced.

Those 8 are the institutionally dangerous ones, and right now an analyst has to sift
15 flags on JPM to find the 3 that matter. The false positives aren't just noise;
they're camouflage.

**Fix:** add the three raw statements to the traceability universe, then re-run. What
survives is the real list, and it should be treated as a hard stop, not a WARN.

One more note: C3 grades `fundamental_valuation + relative_valuation + the two critique
objects`. KO's three flags come **only from the Opus critique text**, not the narrative.
The critique isn't a client deliverable, so it's worth deciding whether it should be
inside C3's scope at all.

---

## 4b. HIGH — nothing in the rubric asks whether the answer is plausible or coherent

All eleven criteria check **form**: is the archetype named, is a range present, is
terminal-value share stated, are peers justified. Not one asks whether the number is
believable, or whether the recommendation follows from the analysis.

KO is the proof. Its primary intrinsic method returns **$24.76 default / $30.73
judgment against an $88.49 live price** — the model says Coca-Cola is 65–72%
overvalued. The memo then recommends **HOLD**, explicitly overriding its own primary
method in favour of comps.

That may well be the right call — the memo argues it honestly and openly ("the DCF's
−72% is not a price target and I will not treat it as one… its value to this memo is
diagnostic"), and the depressed FCF base is real. **But the rubric gave it 10/11, tied
for the best score in the run**, while:

- its primary method is off by ~3× and nothing flags that as implausible,
- its recommendation contradicts its primary method and nothing flags the incoherence,
- its sensitivity paragraph is materially wrong (Finding 1),
- its bias disclosure describes something that never happened (Finding 1),
- its valuation band is 3× too narrow and mislabelled (Finding 1b).

**That is the headline institutional gap: the rubric grades form, not arithmetic and
not coherence.** A memo can be internally well-written, correctly structured, fully
compliant on all eleven criteria — and still ship wrong numbers with a confident
disclosure attached.

**Suggested additions:**
- **F-plausibility:** flag when the primary method's fair value diverges from live price
  by more than some threshold (say 50%) without an explicit stated reason. KO would
  trip it; the memo would pass on the strength of its own explanation.
- **F-coherence:** flag when the recommendation runs against the primary method's
  direction without naming which lens is being preferred and why. KO would trip it and
  pass; a lazier memo would trip it and fail.
- **F-arithmetic:** assert engine-internal consistency — unmoved parameter ⇒ zero delta;
  the compounded band must bracket every single-parameter case. Both Finding 1 and
  Finding 1b would have been caught pre-delivery by two assertions.

The third is the cheapest and highest-value of the three, and it is a unit test, not a
grader.

---

## 5. HIGH — this isn't a controlled experiment

The eight prompts (`tmp/run_fwd07_baseline.py:47-...`) are not held constant:

| Ticker | Prompt length | Names the archetype? | Prescribes the method? |
|---|---|---|---|
| NVDA / QCOM / CRM | 113–125 chars | No | No |
| KO | 178 | Yes ("mature dividend payer") | No |
| XOM | 213 | Yes | Partially ("mid-cycle normalization") |
| PLD | 217 | Yes | **Yes** ("FFO/NAV preferred over FCF DCF") |
| JPM | 236 | Yes | **Yes** ("residual income or P/B preferred") |
| PGR | 245 | Yes | **Yes** ("book-value / residual income preferred") |

Criterion 1 is *"Archetype named and primary method justified."* For JPM, PLD and PGR
**the prompt contains the answer.** They were graded on repeating an instruction;
NVDA/QCOM/CRM had to derive it. The longer prompts also pre-specify memo sections
("Cover business, management, macro, debate, and fair-value work"), which touches C8
and C9.

The comparison doc's own "Interpretation guide" says *"Criterion fails only financials
/ REITs / insurers → extraction or method-set gap."* That inference is unsafe here:
archetype is confounded with prompt length and method-prescription. **Any
archetype-clustered conclusion from this matrix needs a re-run on a single fixed prompt
template before FWD-01b uses it.**

---

## 6. HIGH — four of the eight re-runs ate their own contaminated first pass

`memory.py:310-319` selects the most recent prior run for a ticker, unconditionally.
Grok's first pass mis-routed JPM/PLD/PGR/XOM/KO to `valuation_only`, then re-ran four
of them as `full_underwrite`. The first pass was already saved to
`outputs/research_memory.sqlite`, so the re-run loaded it as prior desk memory.

Confirmed — two rows per ticker on 2026-07-31 (UTC), and the later memo cites the
earlier by row id:

- KO run #27 → `"## Thesis Evolution (vs. prior desk run #23, 2026-07-31T02:42:52+00:00)"`
- PGR run #26 → `"Prior run (id 22, saved 2026-07-31T02:30:44+00:00)"`
- PLD run #25 → `"prior desk run, id 21, saved 2026-07-31T02:22:01+00:00"`
- JPM run #24 → `"## 8. THESIS EVOLUTION vs. PRIOR DESK RUN"`

**Credit where due:** the memos handled it well. Each correctly identifies the prior run
as *"a valuation_only note, not a full underwrite"* and explains what changed. Nothing
was silently corrupted.

**But as a baseline it's still broken.** JPM/PLD/PGR/KO each spend a whole section
comparing against a phantom run that only exists because of a harness misconfiguration.
QCOM says *"none on file — this is a first pass."* NVDA compares against a real prior.
The eight memos are structurally different documents. FWD-01b and FWD-03 are blocked
pending these numbers, so it matters.

Two design gaps behind it:
- Throwaway/harness runs are written to permanent memory with no way to mark them
  "do not use as prior."
- `load_prior_run` has no mode/quality filter — a `valuation_only` stub can become the
  prior for a `full_underwrite`.

---

## 7. MEDIUM — the non-FCF paths ship a fixed ±15% band, and C5 accepts it

JPM and PGR (`excess_return_on_equity`) get their range from
`valuation_engine.py:985-990` — literally `fv * 0.85` and `fv * 1.15`. Verified exact
to 14 decimal places on both. There are **zero** sensitivities behind either
(`sensitivities.n = 0`).

C5 ("Valuation expressed as a range, not a point") **passes** on this. Its
implementation is prose pattern-matching — the grade detail literally reads
*"range language detected in valuation text."*

PLD is worse: `fair_value_range` is `null` at every level (low/base/high) and
`dcf_engine_fv` is `None` — the FFO/NAV path populates no fair value at all — and **C5
still passes**, on prose alone. Meanwhile XOM *failed* C5 for "a point estimate with no
range" on an empty document.

**Fix:** C5 should require the engine to have produced a range with a basis that isn't a
fixed multiplier, not just detect the word "range" in prose.

---

## 8. MEDIUM — the desk memory doesn't remember the call

`memory.py:101-123` extracts rating and price target with `r"\bRating:\s*(BUY|HOLD|AVOID)"`
and `r"Price Target:\s*\$?([0-9.]+)"`. The memos don't use those cover lines — they use
a `## 2. RECOMMENDATION` section with `**HOLD**` inside. The fallback only scans the
first 800 characters, and the recommendation sits far deeper.

Result in `research_memory.sqlite`: `rating` and `price_target` are **empty strings for
CRM, JPM, KO, PGR, PLD and QCOM**. Only NVDA populated (its memo happens to carry a
literal `Rating:` line).

Every future "Thesis Evolution vs prior desk run" section is therefore working without
the single most important fact about the prior run: what the desk actually concluded.
The prompt block even prints `"Prior rating (extracted): n/a"`. This silently degrades
the long-term memory feature the further back you go.

**Fix:** parse the recommendation section by heading, not by cover-line regex; or have
synthesis emit a structured `recommendation` field instead of recovering it from prose.

---

## 9. MEDIUM — XOM is an entity-resolution failure, and the framing matters

Grok's handoff: *"XOM CIK 0002115436: extract/SEC identity bug — fix before any
cyclical_commodity driver validation on XOM."* The resolver is not buggy. I checked the
cached SEC map: `XOM` has exactly **one** entry, and SEC itself maps it to CIK
`0002115436`, "**ExxonMobil Holdings Corp**."

That entity's submissions file shows **26 filings, all between 2026-07-01 and
2026-07-07**, forms `8-K`, `8-K12B`, `POSASR`, `S-8 POS`, and `formerNames: []`.
`8-K12B` is the successor-issuer form for a holding-company reorganization. Exxon
reorganized under a new holdco in early July 2026; SEC repointed the ticker; the new
entity has no XBRL financial history, and no link back to the predecessor filer.

The system followed the map correctly and hard-stopped. That's the right outcome — but
it happened by luck, not by design:

**The holdco had *zero* facts, so validation caught it. Had it filed a single 10-Q
post-reorg, the pipeline would have produced a complete, confident memo on one quarter
of data with no flag raised.** That is the finding, not "fix XOM."

There is no handling anywhere for corporate actions — holdco reorgs, spinoffs, ticker
reuse after bankruptcy, successor issuers. `get_cik_for_ticker` trusts
`company_tickers.json` with no check that the resolved entity has a filing history.

**Two consequences for the plan:**
- Fixing this teaches you **nothing** about commodity drivers. Reframing it as shaping
  "mid-cycle / commodity driver work" sends the next agent down the wrong path.
- FWD-01b and FWD-03 are blocked partly on a `cyclical_commodity` baseline that this
  ticker will never produce. **Substitute CVX or COP and unblock the archetype work
  now**; handle entity resolution as its own item.

**Fix:** after resolving a CIK, assert the entity has ≥1 annual XBRL fact and a 10-K in
its filing history. If not, walk `8-K12B` / `formerNames` / the predecessor filer before
failing. Also: the ticker cache has a 7-day TTL, and this reorg happened ~3 weeks ago —
worth confirming the cache isn't compounding the problem.

---

## 10. MEDIUM — PGR's memo mislabels its own valuation band

The engine labeled PGR's band: `"±15% band on residual-income base (not a full stress
test)"`. The memo says:

> "outer sensitivity band $154.76–$209.38 (**explicitly labeled compounded extremes,
> not scenarios**)"

It isn't. "Compounded extremes" is the *FCF-path* basis string. PGR has no sensitivities
and no compounded corners — it's a fixed ±15% ruler. The memo attributes to the engine a
label the engine did not emit, and calls a mechanical band a "sensitivity band," which
implies analytical work that never happened.

**JPM got this right** on the identical code path: *"the band $184.31–$249.36 is
explicitly disclaimed by the engine as a mechanical ±15% band."* So this is a one-off
writer-fidelity slip — but it's exactly the class of provenance error the audit log
exists to police, and QC passed it with flags.

---

## 11. MEDIUM — C8 is non-deterministic, so this isn't a baseline

Grok's own note: *"JPM 8–9/11 (LLM-judged C8 can flip on re-grade)."* Confirmed —
C1 and C8 both run through `make_llm_judge()` on every ticker.

A criterion that flips between identical runs cannot anchor a before/after comparison
that two epics are blocked on. C8 currently drives 3 of the 8 tickers' scores
(JPM, PLD, XOM).

**Fix:** either pin the judge and record the distribution over n runs, or split the
headline score into "mechanical (9)" and "judged (2, advisory)". The second is cheaper
and more honest.

---

## 12. LOW — the handoff's housekeeping note is wrong

The handoff says *"Artifacts live under `outputs/val02_baseline/*_fwd_baseline*`
(gitignored); harness `tmp/run_fwd07_baseline.py` (gitignored)."*

Both paths **are** in `.gitignore`, but commit `aba7d6b` force-added all 24 of them.
`git ls-files` confirms they're tracked. The next agent will be told to hunt for local
untracked files that are actually in git, and edits to those paths will now show as
tracked modifications despite the ignore rules. Decide whether they should be tracked
and make `.gitignore` match.

---

## What's genuinely good — this shouldn't get lost

- **The run discipline was right.** Grok did not work around the XOM failure, flagged
  the routing mistake, and re-ran the affected tickers rather than papering over it.
- **The handoff is honest** about its own weak spots (the C8 flip, the inert-FCF
  expectation, the routing bug). The two wrong conclusions are analysis errors, not
  spin.
- **NVDA's and QCOM's valuation sections are genuinely institutional-grade.** QCOM's in
  particular: it labels every yfinance-vs-canonical multiple by provenance, refuses to
  conflate engine EV with market EV, names the terminal-value share, dismantles its own
  peer set (AMD's 161x on a depressed base, META not a semi at all, TSM cheaper than the
  subject), and states plainly that *"when one contested input dominates a model to that
  degree, the model is not producing a valuation; it is producing a bet on that input."*
  That is the bar.
- **NVDA's sensitivity narrative is correct** — and correct *because* its base-FCF
  method matched the engine default. It reads exactly like what KO's should have said.
- The memos consistently refuse to fabricate: management packets came back empty on
  KO/QCOM and both said so rather than inventing an assessment.

---

## Recommended order of work

1. **Fix the sensitivity baseline and the corner signs together** (§1, §1b) + the two
   arithmetic assertions from §4b. Re-run all four FCF-path tickers (NVDA, QCOM, CRM,
   KO) — NVDA and CRM are clean on §1 but **all four** are hit by §1b. Nothing
   downstream is trustworthy until this lands.
2. **Wire judgment disclosures into the audit log** (§2). ~5 lines, restores the whole
   Epic V control layer.
3. **Fix C11's regex and C3's traceability universe** (§3, §4), then re-grade the
   existing eight slices — no re-run needed, the state is on disk. Expect the scores to
   move materially. Only then decide what's writer discipline.
4. **Re-run the baseline on one fixed prompt template**, with the memory DB isolated or
   the prior-run lookup disabled (§5, §6). This is the version FWD-01b and FWD-03 should
   consume.
5. **Swap XOM → CVX/COP** to unblock cyclical_commodity now; file entity resolution
   (§9) separately.
6. Then the smaller ones: C5's range check (§7), rating/PT extraction (§8), C8 scoring
   split (§11).

Items 1–3 need no new API spend — they're code fixes plus a re-grade of the committed
state slices.
