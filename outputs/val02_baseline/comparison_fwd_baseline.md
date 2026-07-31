# FWD-07 Full Eight-Ticker Baseline

Generated: 2026-07-31T04:17:57.131913+00:00
Commit base: pull of main @ 1ffa771 (bias detector + central-case redesign).
Artifact suffix: `_fwd_baseline`

## Per-ticker scores

| Ticker | Archetype (note) | Extracted | Method | Score | Critiques | Args p/a/r | FCF hist | Central FV | One-sided | Failures |
|--------|------------------|-----------|--------|------:|-----------|------------|----------|------------|:---------:|----------|
| NVDA | general / semis | general | multi_stage_fcf_dcf | 9/11 | f=True r=True | 6/6/0 | 5 | 224.58964404822868 | False | 0 |
| QCOM | general / semis | general | multi_stage_fcf_dcf | 10/11 | f=True r=True | 5/5/0 | 5 | 128.68944447875026 | True | 0 |
| CRM | software_saas | software_saas | multi_stage_fcf_dcf | 9/11 | f=True r=True | 5/5/0 | 5 | 397.3657621044434 | True | 0 |
| JPM | bank_lender — residual income; FCF DCF not primary | bank_lender | excess_return_on_equity | 8/11 | f=True r=True | 6/6/0 | 0 | 216.83180088938414 | None | 1 |
| PLD | equity_reit — FFO/NAV path | equity_reit | ffo_nav | 8/11 | f=True r=True | 1/1/0 | 0 | None | None | 1 |
| PGR | insurance — book-value path | insurance | excess_return_on_equity | 9/11 | f=True r=True | 6/6/0 | 5 | 182.07377088111548 | None | 1 |
| XOM | cyclical_commodity — mid-cycle normalization | cyclical_commodity | None | 7/11 | f=False r=False | 0/0/0 | 0 | None | None | 3 |
| KO | mature_dividend_payer — stable-assumption control | mature_dividend_payer | multi_stage_fcf_dcf | 10/11 | f=True r=True | 6/6/0 | 5 | 30.730791784545403 | True | 0 |

## Per-criterion × per-ticker (PASS/FAIL)

| # | Criterion | NVDA | QCOM | CRM | JPM | PLD | PGR | XOM | KO | Pass rate |
|---|-----------|---|---|---|---|---|---|---|---|----------|
| 1 | Archetype named and primary method justified | PASS | PASS | PASS | PASS | PASS | PASS | FAIL | PASS | 7/8 |
| 2 | Every argued input cites ≥1 resolvable evidence field | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 8/8 |
| 3 | No currency figure appears that is not traceable to an engine block | FAIL | FAIL | PASS | FAIL | FAIL | FAIL | PASS | FAIL | 2/8 |
| 4 | Terminal-value share of EV stated (DCF path) | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 8/8 |
| 5 | Valuation expressed as a range, not a point | PASS | PASS | PASS | PASS | PASS | PASS | FAIL | PASS | 7/8 |
| 6 | Each peer inclusion/exclusion justified individually | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 8/8 |
| 7 | Comparison windows consistent and stated (no YTD vs 1-yr mixing) | PASS | PASS | FAIL | PASS | PASS | PASS | PASS | PASS | 7/8 |
| 8 | ≥1 risk left explicitly unresolved (no self-neutralizing close) | PASS | PASS | PASS | FAIL | FAIL | PASS | FAIL | PASS | 5/8 |
| 9 | Both default and judgment cases present | PASS | PASS | PASS | PASS | PASS | PASS | FAIL | PASS | 7/8 |
| 10 | Band dissents flagged where applicable | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 8/8 |
| 11 | No internal numeric contradiction (same metric, two values) | FAIL | PASS | FAIL | FAIL | FAIL | FAIL | PASS | PASS | 3/8 |

## Per-criterion × archetype group

| # | Criterion | bank_lender | cyclical_commodity | equity_reit | general | insurance | mature_dividend_payer | software_saas |
|---|-----------|---|---|---|---|---|---|---|
| 1 | Archetype named and primary method justified | 1/1 | 0/1 | 1/1 | 2/2 | 1/1 | 1/1 | 1/1 |
| 2 | Every argued input cites ≥1 resolvable evidence field | 1/1 | 1/1 | 1/1 | 2/2 | 1/1 | 1/1 | 1/1 |
| 3 | No currency figure appears that is not traceable to an engine block | 0/1 | 1/1 | 0/1 | 0/2 | 0/1 | 0/1 | 1/1 |
| 4 | Terminal-value share of EV stated (DCF path) | 1/1 | 1/1 | 1/1 | 2/2 | 1/1 | 1/1 | 1/1 |
| 5 | Valuation expressed as a range, not a point | 1/1 | 0/1 | 1/1 | 2/2 | 1/1 | 1/1 | 1/1 |
| 6 | Each peer inclusion/exclusion justified individually | 1/1 | 1/1 | 1/1 | 2/2 | 1/1 | 1/1 | 1/1 |
| 7 | Comparison windows consistent and stated (no YTD vs 1-yr mixing) | 1/1 | 1/1 | 1/1 | 2/2 | 1/1 | 1/1 | 0/1 |
| 8 | ≥1 risk left explicitly unresolved (no self-neutralizing close) | 0/1 | 0/1 | 0/1 | 2/2 | 1/1 | 1/1 | 1/1 |
| 9 | Both default and judgment cases present | 1/1 | 0/1 | 1/1 | 2/2 | 1/1 | 1/1 | 1/1 |
| 10 | Band dissents flagged where applicable | 1/1 | 1/1 | 1/1 | 2/2 | 1/1 | 1/1 | 1/1 |
| 11 | No internal numeric contradiction (same metric, two values) | 0/1 | 1/1 | 0/1 | 1/2 | 0/1 | 1/1 | 0/1 |

## Interpretation guide

- Criterion fails **all 8** → definition / grader problem.
- Criterion fails **only financials / REITs / insurers** → extraction or method-set gap.
- `Argued FCF inputs not applied` on JPM/PLD/PGR is **expected** until the next epic adds non-FCF argued parameters.

## Per-ticker detail

### NVDA
- Note: general / semis
- Extracted archetype: `general` method=`multi_stage_fcf_dcf`
- Score: **9/11** validation=`WARN` qc=`PASS_WITH_FLAGS`
- Critiques parseable: fund=True rel=True
- Args proposed/accepted/rejected: **6/6/0** `['g_high', 'wacc', 'g_terminal', 'base_fcf_method', 'high_growth_years', 'fade_years']` → `['g_high', 'wacc', 'g_terminal', 'base_fcf_method', 'high_growth_years', 'fade_years']` reject=`[]`
- FV range low/base/high: `168.89444106606823` / **`224.58964404822868`** / `305.70193803903385`
- Sensitivities n=5 dominant=`{'parameter': 'g_high', 'engine_default': 0.35, 'argued_midpoint': 0.27, 'fair_value_per_share': 213.2207080815118, 'delta_vs_default': -105.40540668092368}`
  - `g_high`: def=0.35 → mid=0.27 FV=213.2207080815118 Δ=-105.40540668092368
  - `fade_years`: def=5 → mid=6 FV=355.18813472582434 Δ=36.56201996338888
  - `g_terminal`: def=0.03 → mid=0.0275 FV=309.3858909288348 Δ=-9.24022383360068
  - `wacc`: def=0.1 → mid=0.1 FV=318.62611476243546 Δ=0.0
  - `high_growth_years`: def=5 → mid=5 FV=318.62611476243546 Δ=0.0
- Directional bias: share=0.758 dir=below default one_sided=False fired=False
- base_fcf_method requested/applied: `ttm` / `ttm` fcf_history_n=5 (≥3=True)
- DIRECTIONAL BIAS disclosures: `[]`
- Argued FCF not applied: `[]`
- Failures (0):
  - (none)
- Rubric fails:
  - **C3 no_untraceable_currency**: untraceable currency: $16.4B, $5.19B, $20.83B, $27.02B
  - **C11 no_numeric_contradiction**: contradictions: g_high: [0.05, 0.03] (not explained by argued shape: default/central/corners/sensitivities)

### QCOM
- Note: general / semis
- Extracted archetype: `general` method=`multi_stage_fcf_dcf`
- Score: **10/11** validation=`PASS` qc=`PASS_WITH_FLAGS`
- Critiques parseable: fund=True rel=True
- Args proposed/accepted/rejected: **5/5/0** `['g_high', 'base_fcf_method', 'wacc', 'g_terminal', 'high_growth_years']` → `['g_high', 'base_fcf_method', 'wacc', 'g_terminal', 'high_growth_years']` reject=`[]`
- FV range low/base/high: `123.86748233899961` / **`128.68944447875026`** / `133.8033285057957`
- Sensitivities n=4 dominant=`{'parameter': 'g_high', 'engine_default': 0.14864259474957442, 'argued_midpoint': 0.02, 'fair_value_per_share': 146.37849750684578, 'delta_vs_default': -189.453241892408}`
  - `g_high`: def=0.14864259474957442 → mid=0.02 FV=146.37849750684578 Δ=-189.453241892408
  - `wacc`: def=0.1 → mid=0.10750000000000001 FV=272.59340913343226 Δ=-63.2383302658215
  - `g_terminal`: def=0.03 → mid=0.0275 FV=297.88678136279833 Δ=-37.94495803645543
  - `high_growth_years`: def=5 → mid=5 FV=306.09566890193895 Δ=-29.736070497314813
- Directional bias: share=1.0 dir=below default one_sided=True fired=True
- base_fcf_method requested/applied: `avg_3y` / `avg_3y` fcf_history_n=5 (≥3=True)
- DIRECTIONAL BIAS disclosures: `['DIRECTIONAL BIAS: 100% of the argued movement across 4 material arguments pushes fair value below default. A view is normally one or two departures with the rest left at default; a one-sided set warrants a single stated reason or it is a thumb on the scale.']`
- Argued FCF not applied: `[]`
- Failures (0):
  - (none)
- Rubric fails:
  - **C3 no_untraceable_currency**: untraceable currency: $3.2B

### CRM
- Note: software_saas
- Extracted archetype: `software_saas` method=`multi_stage_fcf_dcf`
- Score: **9/11** validation=`WARN` qc=`PASS_WITH_FLAGS`
- Critiques parseable: fund=True rel=True
- Args proposed/accepted/rejected: **5/5/0** `['g_high', 'base_fcf_method', 'wacc', 'g_terminal', 'high_growth_years']` → `['g_high', 'base_fcf_method', 'wacc', 'g_terminal', 'high_growth_years']` reject=`[]`
- FV range low/base/high: `369.3988226920207` / **`397.3657621044434`** / `427.14343254870903`
- Sensitivities n=4 dominant=`{'parameter': 'g_high', 'engine_default': 0.15827569567315436, 'argued_midpoint': 0.095, 'fair_value_per_share': 427.7876142187724, 'delta_vs_default': -183.1275645617256}`
  - `g_high`: def=0.15827569567315436 → mid=0.095 FV=427.7876142187724 Δ=-183.1275645617256
  - `wacc`: def=0.09 → mid=0.0925 FV=583.7646060530386 Δ=-27.15057272745935
  - `g_terminal`: def=0.03 → mid=0.0275 FV=591.3018676778929 Δ=-19.613311102605053
  - `high_growth_years`: def=5 → mid=5 FV=610.915178780498 Δ=0.0
- Directional bias: share=1.0 dir=below default one_sided=True fired=True
- base_fcf_method requested/applied: `ttm` / `ttm` fcf_history_n=5 (≥3=True)
- DIRECTIONAL BIAS disclosures: `['DIRECTIONAL BIAS: 100% of the argued movement across 3 material arguments pushes fair value below default. A view is normally one or two departures with the rest left at default; a one-sided set warrants a single stated reason or it is a thumb on the scale.']`
- Argued FCF not applied: `[]`
- Failures (0):
  - (none)
- Rubric fails:
  - **C7 comparison_windows_consistent**: mixed comparison windows: ytd, 1y, 5y, yoy
  - **C11 no_numeric_contradiction**: contradictions: g_high: [0.688, 0.26] (not explained by argued shape: default/central/corners/sensitivities)

### JPM
- Note: bank_lender — residual income; FCF DCF not primary
- Extracted archetype: `bank_lender` method=`excess_return_on_equity`
- Score: **8/11** validation=`WARN` qc=`PASS_WITH_FLAGS`
- Critiques parseable: fund=True rel=True
- Args proposed/accepted/rejected: **6/6/0** `['wacc', 'g_high', 'g_terminal', 'high_growth_years', 'fade_years', 'base_fcf_method']` → `['wacc', 'g_high', 'g_terminal', 'high_growth_years', 'fade_years', 'base_fcf_method']` reject=`[]`
- FV range low/base/high: `184.3070307559765` / **`216.83180088938414`** / `249.35657102279174`
- Sensitivities n=0 dominant=`None`
- Directional bias: share=None dir=None one_sided=None fired=False
- base_fcf_method requested/applied: `avg_3y` / `None` fcf_history_n=0 (≥3=False)
- DIRECTIONAL BIAS disclosures: `[]`
- Argued FCF not applied: `['Argued FCF inputs not applied: the archetype does not use an FCF DCF.']`
- Failures (1):
  - **argued_fcf_inert**: Argued FCF inputs not applied: the archetype does not use an FCF DCF.
- Rubric fails:
  - **C3 no_untraceable_currency**: untraceable currency: $308B, $113.35, $900B, $14.21B, $118B, $4.1T, $2.56T, $507.20B
  - **C8 unresolved_risk**: FAIL: All risks (ROE fade, reserve adequacy, provisions, thin equity/assets) are ultimately folded back into a 'both readings defensible, central debate' framing rather than left as a genuinely unresolved downside risk — the write-up systematically neutralizes each concern by balancing it against a bull-side offset instead of stating any single risk as unresolved.
  - **C11 no_numeric_contradiction**: contradictions: eps: [20.02, 23.76, 5.94] (not explained by argued shape: default/central/corners/sensitivities)

### PLD
- Note: equity_reit — FFO/NAV path
- Extracted archetype: `equity_reit` method=`ffo_nav`
- Score: **8/11** validation=`WARN` qc=`PASS_WITH_FLAGS`
- Critiques parseable: fund=True rel=True
- Args proposed/accepted/rejected: **1/1/0** `['base_fcf_method']` → `['base_fcf_method']` reject=`[]`
- FV range low/base/high: `None` / **`None`** / `None`
- Sensitivities n=0 dominant=`None`
- Directional bias: share=None dir=None one_sided=None fired=False
- base_fcf_method requested/applied: `avg_3y` / `None` fcf_history_n=0 (≥3=False)
- DIRECTIONAL BIAS disclosures: `[]`
- Argued FCF not applied: `['Argued FCF inputs not applied: the archetype does not use an FCF DCF.']`
- Failures (1):
  - **argued_fcf_inert**: Argued FCF inputs not applied: the archetype does not use an FCF DCF.
- Rubric fails:
  - **C3 no_untraceable_currency**: untraceable currency: $5.5B, $2.1B, $235B, $235 billion, $4.16B, $469.1M, $57.82B, $4.561B
  - **C8 unresolved_risk**: FAIL: All flagged risks (cap-rate opacity, decelerating mark-to-market runway, financing/development spread, data-center pivot, balance-sheet residual) are presented as checklist gaps for future work rather than left as open, unresolved risk to the current valuation stance; the write-up frames them as reasons the tool abstains rather than as unresolved threats to a stated view, effectively neutralizing them via 'not fabricated / undetermined' framing.
  - **C11 no_numeric_contradiction**: contradictions: eps: [3.56, 1.05] (not explained by argued shape: default/central/corners/sensitivities)

### PGR
- Note: insurance — book-value path
- Extracted archetype: `insurance` method=`excess_return_on_equity`
- Score: **9/11** validation=`WARN` qc=`PASS_WITH_FLAGS`
- Critiques parseable: fund=True rel=True
- Args proposed/accepted/rejected: **6/6/0** `['wacc', 'g_high', 'g_terminal', 'high_growth_years', 'fade_years', 'base_fcf_method']` → `['wacc', 'g_high', 'g_terminal', 'high_growth_years', 'fade_years', 'base_fcf_method']` reject=`[]`
- FV range low/base/high: `154.76270524894815` / **`182.07377088111548`** / `209.38483651328278`
- Sensitivities n=0 dominant=`None`
- Directional bias: share=None dir=None one_sided=None fired=False
- base_fcf_method requested/applied: `avg_3y` / `None` fcf_history_n=5 (≥3=True)
- DIRECTIONAL BIAS disclosures: `[]`
- Argued FCF not applied: `['Argued FCF inputs not applied: the archetype does not use an FCF DCF.']`
- Failures (1):
  - **argued_fcf_inert**: Argued FCF inputs not applied: the archetype does not use an FCF DCF.
- Rubric fails:
  - **C3 no_untraceable_currency**: untraceable currency: $950M, $1.24B, $90B, $54.83, $27.96B, $95B, $5.1B, $89B
  - **C11 no_numeric_contradiction**: contradictions: eps: [19.23, 4.8, 202.0] (not explained by argued shape: default/central/corners/sensitivities)

### XOM
- Note: cyclical_commodity — mid-cycle normalization
- Extracted archetype: `cyclical_commodity` method=`None`
- Score: **7/11** validation=`FAIL` qc=``
- Critiques parseable: fund=False rel=False
- Args proposed/accepted/rejected: **0/0/0** `[]` → `[]` reject=`[]`
- FV range low/base/high: `None` / **`None`** / `None`
- Sensitivities n=0 dominant=`None`
- Directional bias: share=None dir=None one_sided=None fired=False
- base_fcf_method requested/applied: `None` / `None` fcf_history_n=0 (≥3=False)
- DIRECTIONAL BIAS disclosures: `[]`
- Argued FCF not applied: `[]`
- Failures (3):
  - **validation_gate**: validation status=FAIL checks=13 warnings=2 failures=1 archetype=cyclical_commodity
  - **dcf_engine**: dcf_engine empty/missing
  - **fundamental_critique**: valuation_critique missing (parse fail / API / skipped / inert path)
- Rubric fails:
  - **C1 archetype_and_method**: empty valuation text
  - **C5 valuation_as_range**: valuation appears as a point estimate with no range expression
  - **C8 unresolved_risk**: empty valuation text
  - **C9 default_and_judgment_cases**: missing: dcf_engine

### KO
- Note: mature_dividend_payer — stable-assumption control
- Extracted archetype: `mature_dividend_payer` method=`multi_stage_fcf_dcf`
- Score: **10/11** validation=`WARN` qc=`PASS_WITH_FLAGS`
- Critiques parseable: fund=True rel=True
- Args proposed/accepted/rejected: **6/6/0** `['base_fcf_method', 'g_high', 'wacc', 'g_terminal', 'high_growth_years', 'fade_years']` → `['base_fcf_method', 'g_high', 'wacc', 'g_terminal', 'high_growth_years', 'fade_years']` reject=`[]`
- FV range low/base/high: `28.390768332477098` / **`30.730791784545403`** / `33.94248305504241`
- Sensitivities n=5 dominant=`{'parameter': 'wacc', 'engine_default': 0.09, 'argued_midpoint': 0.07750000000000001, 'fair_value_per_share': 54.88201628585144, 'delta_vs_default': 30.121103932211415}`
  - `wacc`: def=0.09 → mid=0.07750000000000001 FV=54.88201628585144 Δ=30.121103932211415
  - `g_terminal`: def=0.025 → mid=0.025 FV=42.06723190262557 Δ=17.306319548985545
  - `high_growth_years`: def=5 → mid=5 FV=42.06723190262557 Δ=17.306319548985545
  - `fade_years`: def=5 → mid=5 FV=42.06723190262557 Δ=17.306319548985545
  - `g_high`: def=0.11706391056739074 → mid=0.0325 FV=23.286615913428836 Δ=-1.4742964402111909
- Directional bias: share=0.982 dir=above default one_sided=True fired=True
- base_fcf_method requested/applied: `avg_5y` / `avg_5y` fcf_history_n=5 (≥3=True)
- DIRECTIONAL BIAS disclosures: `['DIRECTIONAL BIAS: 98% of the argued movement across 5 material arguments pushes fair value above default. A view is normally one or two departures with the rest left at default; a one-sided set warrants a single stated reason or it is a thumb on the scale.']`
- Argued FCF not applied: `[]`
- Failures (0):
  - (none)
- Rubric fails:
  - **C3 no_untraceable_currency**: untraceable currency: $21.71B, $14.81B, $2.9B

## Run hygiene notes

- Base: branch `fwd-07-baseline` with main@1ffa771 (VAL-16 bias detector + central-case) as ancestor; FWD-01 driver-template work sits on top and was **not** exercised by this baseline.
- All eight ran as **full_underwrite** on the clean pass (JPM/PLD/PGR/KO re-run after first-pass `valuation_only` routing from pre-fix queries).
- **XOM hard-stop (extraction, not grader):** data_gatherer bound CIK `0002115436`; every income concept returned null (`incomplete=True`); validation FAIL on `revenue_positive`; no DCF/comps/critique/judgment. Do not workaround — shapes mid-cycle / commodity driver work.
- **JPM / PLD / PGR inert FCF args (expected):** method is residual income / FFO-NAV; `Argued FCF inputs not applied: the archetype does not use an FCF DCF.` is correct until Epic F adds non-FCF argued parameters. PLD also has `fair_value_range` null (FFO/NAV FV not populated).
- **C3 fails 6/8 completed runs:** systemic currency-traceability (memo uses $ figures outside engine blocks) — grader definition / writer discipline, not archetype-specific.
- **C11 fails ~half:** residual numeric contradictions not covered by argued-shape allowlist — writer discipline with some archetype clustering on non-FCF methods.
- One-sided bias fired: QCOM, CRM, KO (full underwrite). NVDA dominant_share=0.758 (not one_sided). JPM/PLD/PGR inert (no FCF sensitivities).

