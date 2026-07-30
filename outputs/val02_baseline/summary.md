# VAL-02 Baseline (subset: NVDA, CRM, JPM)

Generated: 2026-07-29T05:16:06.467303+00:00

## Scores

| Ticker | Score | Note |
|--------|------:|------|
| NVDA | 10/11 | general / semis |
| CRM | 7/11 | software_saas |
| JPM | 9/11 | bank_lender — DCF must be rejected as primary |

## Per-criterion

| # | Criterion | NVDA | CRM | JPM | Pass rate |
|---|-----------|:----:|:---:|:---:|----------:|
| 1 | Archetype named and primary method justified | PASS | PASS | PASS | 100% |
| 2 | Every argued input cites ≥1 resolvable evidence field | PASS | PASS | PASS | 100% |
| 3 | No currency figure appears that is not traceable to an engine block | PASS | FAIL | FAIL | 33% |
| 4 | Terminal-value share of EV stated (DCF path) | PASS | PASS | PASS | 100% |
| 5 | Valuation expressed as a range, not a point | PASS | PASS | PASS | 100% |
| 6 | Each peer inclusion/exclusion justified individually | PASS | PASS | PASS | 100% |
| 7 | Comparison windows consistent and stated (no YTD vs 1-yr mixing) | PASS | FAIL | PASS | 67% |
| 8 | ≥1 risk left explicitly unresolved (no self-neutralizing close) | PASS | PASS | PASS | 100% |
| 9 | Both default and judgment cases present | FAIL | FAIL | FAIL | 0% |
| 10 | Band dissents flagged where applicable | PASS | PASS | PASS | 100% |
| 11 | No internal numeric contradiction (same metric, two values) | PASS | FAIL | PASS | 67% |

## Fail details

### NVDA
- **9 default_and_judgment_cases**: missing: dcf_judgment, comps_judgment

### CRM
- **3 no_untraceable_currency**: untraceable currency: $23B, $46.0B, $57,000, $57.94B
- **7 comparison_windows_consistent**: mixed comparison windows: ytd, 1y, 5y, yoy
- **9 default_and_judgment_cases**: missing: dcf_judgment, comps_judgment
- **11 no_numeric_contradiction**: contradictions: g_high: [0.158, 0.05]; eps: [7.8, 11.7]

### JPM
- **3 no_untraceable_currency**: untraceable currency: $14.212B, $10.678B, $10B, $4.1T, $2.2B
- **9 default_and_judgment_cases**: missing: dcf_judgment, comps_judgment
